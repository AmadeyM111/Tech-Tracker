"""Сервис учётных записей и ролей (plan §4.6, §4.4, §4.5; FR-4, FR-5, FR-5a, FR-12, FR-62,
FR-65, FR-66, FR-69, FR-73).

Сервис не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``; отклонённое действие
(исключение) откатывает и изменение, и событие (AC-67). Каждое действие пишет ровно одно
событие ``user.*`` через ``record_event`` в той же транзакции; в ``details`` и в логи пароли и
хеши не попадают (FR-57). Одноразовый пароль хранится только как Argon2id-хеш.

Порядок проверок (plan §4.5): права актора (403) -> проверка входных данных (422) -> загрузка
цели в пространстве актора (404) -> бизнес-правила (422). Чужое пространство и несуществующий
идентификатор неразличимы (404, FR-13). Сервис работает только с таблицами пользователей и
членства: разделов бизнес-данных не читает (BR-2).

Протокол блокировок (единый для всех действий над учётными записями, ``_lock_for_account_change``)
выполняется после проверок прав и входных данных и ДО любого изменения:

1. ``pg_advisory_xact_lock(_ACCOUNT_LOCK_NAMESPACE, hashtext(workspace_id))`` — действия
   администрирования учётных записей одного пространства выполняются строго по очереди;
2. одним запросом ``FOR NO KEY UPDATE ... ORDER BY user_id`` блокируются строки
   ``workspace_member`` и ``app_user`` объединения «активные администраторы пространства ∪
   цель»; затем проверяется, что актор входит в заблокированное множество активных
   администраторов (окно устаревшего актора, ревью T16a: между ``get_actor`` и блокировками
   актора могли заблокировать или лишить роли) — иначе 403 без изменений и без событий;
3. цель читается заново (``_load_target`` без блокировки — данные уже свежие и защищены), затем
   только изменения строк, удаление сессий цели и запись события.

Инвариант FR-69 («в пространстве всегда есть активный обладатель MANAGE_ACCOUNTS»): после
изменения число оставшихся проверяется ``ensure_account_admin_remains``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import load_only

from app.core.clock import utcnow
from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
)
from app.domain.access.roles import ACCOUNT_ADMIN_ROLES, Actor, Capability, Role
from app.domain.auth.provider import normalize_login
from app.domain.auth.sessions import SessionStore
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

_ADMIN_ROLE_VALUES = sorted(role.value for role in ACCOUNT_ADMIN_ROLES)

# Пространство ключей advisory-блокировок действий над учётными записями (ASCII «user»).
# Двухключевая форма ``pg_advisory_xact_lock(int4, int4)`` не пересекается с одноключевой
# (``bigint``), которой пользуются первый запуск и сериализация колонок доски (D-21, D-22).
_ACCOUNT_LOCK_NAMESPACE: Final = 0x75736572


@dataclass(frozen=True)
class UserAccount:
    """Учётная запись пользователя в пространстве (без хеша пароля и счётчиков входа)."""

    id: UUID
    login: str
    role: Role | None
    is_blocked: bool
    must_change_password: bool
    created_at: datetime


@dataclass(frozen=True)
class _Target:
    id: UUID
    login: str
    role: Role | None
    is_blocked: bool
    must_change_password: bool
    created_at: datetime

    @property
    def is_active_account_admin(self) -> bool:
        return self.role in ACCOUNT_ADMIN_ROLES and not self.is_blocked

    def to_account(self, *, role: Role | None) -> UserAccount:
        return UserAccount(
            id=self.id,
            login=self.login,
            role=role,
            is_blocked=self.is_blocked,
            must_change_password=self.must_change_password,
            created_at=self.created_at,
        )


def _require(actor: Actor, capability: Capability) -> None:
    """Права актора проверяются ДО загрузки цели (plan §4.5, п.4 раньше п.6)."""
    if not actor.can(capability):
        raise Forbidden()


def _parse_role(role: Role | None) -> Role | None:
    if role is None:
        return None
    try:
        return Role(role)
    except ValueError:
        raise Unprocessable("Недопустимая роль", code=ErrorCode.validation_error) from None


def _check_one_time_password(password: str) -> None:
    """Политика FR-52/FR-53 (422); значение пароля в исключения не попадает (ревью T08)."""
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        raise Unprocessable(code=ErrorCode.validation_error) from None
    try:
        validate_new_password(password)
    except PasswordPolicyError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


async def _load_target(db: AsyncSession, workspace_id: UUID, user_id: UUID) -> _Target:
    """Пользователь в пространстве актора; иначе ``NotFound`` (чужое пространство, нет id).

    Читает без блокировки: вызывается после ``_lock_for_account_change``, когда строки цели уже
    заблокированы этой транзакцией, поэтому видно последнее зафиксированное состояние.
    """
    stmt = (
        select(
            AppUser.id,
            AppUser.login,
            AppUser.is_blocked,
            AppUser.must_change_password,
            AppUser.created_at,
            WorkspaceMember.role,
        )
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(WorkspaceMember.workspace_id == workspace_id, AppUser.id == user_id)
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise NotFound()
    return _Target(
        id=row.id,
        login=row.login,
        role=Role(row.role) if row.role is not None else None,
        is_blocked=row.is_blocked,
        must_change_password=row.must_change_password,
        created_at=row.created_at,
    )


def _is_active_account_admin() -> ColumnElement[bool]:
    return and_(WorkspaceMember.role.in_(_ADMIN_ROLE_VALUES), AppUser.is_blocked.is_(False))


async def _lock_for_account_change(
    db: AsyncSession, workspace_id: UUID, target_id: UUID, actor_id: UUID
) -> None:
    """Единый протокол блокировок перед изменением учётной записи (см. docstring модуля).

    1. ``pg_advisory_xact_lock`` по пространству: все действия администрирования учётных
       записей одного пространства идут по очереди, поэтому между собой они не могут
       образовать цикл ожиданий, сколько бы строк (админы, цель, сессии, события) ни трогали
       дальше и в каком бы порядке. Блокировка снимается COMMIT/ROLLBACK транзакции
       (``get_db``). Действий администрирования мало (пилот: 12 пользователей, единицы
       админов), а держится блокировка миллисекунды: Argon2-хеширование выполняется ДО неё.
       Вход, смена своего пароля, ``get_actor`` и любые прочие запросы этот ключ не берут и
       им не ждут.
    2. Одним запросом ``FOR NO KEY UPDATE ... ORDER BY user_id`` (строки ``workspace_member``,
       затем ``app_user`` каждого пользователя) блокируется объединение «активные
       администраторы пространства ∪ цель»: состояние, на котором проверяется FR-69,
       не изменится до конца транзакции, а порядок по ``user_id`` единый для любого изменяющего
       кода. Отдельной блокировки цели после множества админов нет (она нарушала порядок и
       давала deadlock, ревью T16).
    3. Окно устаревшего актора (ревью T16a): права актора проверены в ``get_actor`` до этих
       блокировок, а он мог быть заблокирован или лишён роли параллельным действием, уже
       зафиксированным к моменту получения advisory-блокировки. Поэтому после блокировок актор
       должен входить в множество заблокированных активных администраторов (роль из
       ``ACCOUNT_ADMIN_ROLES``, не заблокирован); иначе ``Forbidden`` (403: актор был
       аутентифицирован на момент запроса, права он потерял в окне). Исключение откатывает
       транзакцию: изменений и событий нет.

    Почему не мешает FK и входу: вставки ``domain_event`` (``actor_id``), ``user_session``
    (``user_id``) и ``created_by`` проверяют ссылку на ``app_user`` блокировкой
    ``FOR KEY SHARE``, которая совместима с ``FOR NO KEY UPDATE`` (с ней конфликтует только
    ``FOR UPDATE``), а advisory-блокировка — объект другого типа и со строками не конфликтует.
    ``UPDATE app_user`` при входе и смене своего пароля (счётчик неудач, хеш) меняет только
    неключевые столбцы и берёт ту же ``FOR NO KEY UPDATE`` лишь на свою строку, после чего
    ничего, удерживаемого действием администратора, не ждёт: возможно короткое ожидание одной
    стороны, но не цикл.
    """
    await db.execute(
        select(
            func.pg_advisory_xact_lock(_ACCOUNT_LOCK_NAMESPACE, func.hashtext(str(workspace_id)))
        )
    )
    locked = (
        await db.execute(
            select(WorkspaceMember.user_id, WorkspaceMember.role, AppUser.is_blocked)
            .join(AppUser, AppUser.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                or_(_is_active_account_admin(), WorkspaceMember.user_id == target_id),
            )
            .order_by(WorkspaceMember.user_id)
            .with_for_update(key_share=True)
        )
    ).all()
    active_admin_ids = {
        row.user_id for row in locked if row.role in _ADMIN_ROLE_VALUES and not row.is_blocked
    }
    if actor_id in active_admin_ids:
        return
    raise Forbidden()


async def ensure_account_admin_remains(db: AsyncSession, workspace_id: UUID) -> None:
    """FR-69: в пространстве остался хотя бы один активный обладатель MANAGE_ACCOUNTS.

    Вызывается после изменения в той же транзакции. Строки активных администраторов
    блокируются ``FOR NO KEY UPDATE ORDER BY user_id`` (тот же режим и порядок, что в
    ``_lock_for_account_change``; внутри действий сервиса они уже заблокированы, повторная
    блокировка своих строк не ждёт). Ни одного — 422 ``last_account_admin``.
    """
    rows = await db.execute(
        select(WorkspaceMember.user_id)
        .join(AppUser, AppUser.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id, _is_active_account_admin())
        .order_by(WorkspaceMember.user_id)
        .with_for_update(key_share=True)
    )
    if not rows.all():
        raise Unprocessable(
            "В пространстве должен остаться хотя бы один активный администратор учётных записей",
            code=ErrorCode.last_account_admin,
        )


async def create_user(
    db: AsyncSession,
    actor: Actor,
    hasher: PasswordHasher,
    *,
    login: str,
    one_time_password: SecretStr,
) -> UserAccount:
    """Создаёт пользователя без роли с одноразовым паролем (FR-4, FR-66, FR-73, AC-121).

    Логин: только ASCII, нижний регистр, шаблон FR-73 (``login_invalid``), занят —
    ``login_taken`` (в том числе пользователем другого пространства: логин глобален).
    ``must_change_password = true``. Событие ``user.created``. Порядок проверок:
    ``login_invalid`` -> ``login_taken`` -> политика пароля (FR-52/FR-53). Протокол блокировок
    (с автором в роли цели) — после хеширования; одновременное создание того же логина
    отсекает ``ON CONFLICT DO NOTHING``.
    """
    _require(actor, Capability.MANAGE_ACCOUNTS)
    normalized = normalize_login(login)
    if normalized is None:
        raise Unprocessable("Недопустимый логин", code=ErrorCode.login_invalid)
    taken = (
        await db.execute(select(AppUser.id).where(AppUser.login == normalized))
    ).scalar_one_or_none()
    if taken is not None:
        raise Unprocessable("Логин уже занят", code=ErrorCode.login_taken)

    password = one_time_password.get_secret_value()
    _check_one_time_password(password)
    password_hash = await hash_in_thread(hasher, password)
    await _lock_for_account_change(db, actor.workspace_id, actor.user_id, actor.user_id)

    user_id = uuid4()
    now = utcnow()
    inserted = (
        await db.execute(
            pg_insert(AppUser)
            .values(
                id=user_id,
                login=normalized,
                password_hash=password_hash,
                must_change_password=True,
                is_blocked=False,
                failed_login_count=0,
                password_changed_at=now,
                created_at=now,
                updated_at=now,
                created_by=actor.user_id,
            )
            .on_conflict_do_nothing(index_elements=[AppUser.login])
            .returning(AppUser.created_at)
        )
    ).one_or_none()
    if inserted is None:  # параллельное создание того же логина
        raise Unprocessable("Логин уже занят", code=ErrorCode.login_taken)
    await db.execute(
        pg_insert(WorkspaceMember).values(
            workspace_id=actor.workspace_id,
            user_id=user_id,
            role=None,
            created_at=now,
            updated_at=now,
            created_by=actor.user_id,
        )
    )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_CREATED,
        entity_id=user_id,
    )
    return UserAccount(
        id=user_id,
        login=normalized,
        role=None,
        is_blocked=False,
        must_change_password=True,
        created_at=inserted.created_at,
    )


async def block_user(
    db: AsyncSession, actor: Actor, sessions: SessionStore, user_id: UUID, /
) -> None:
    """Блокирует пользователя и завершает все его сессии (FR-5, FR-69, AC-44).

    Повторная блокировка заблокированного — без ошибки и без события. Счётчик неудач и
    срок блокировки входа не трогаются.
    """
    _require(actor, Capability.MANAGE_ACCOUNTS)
    await _lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await _load_target(db, actor.workspace_id, user_id)
    if target.is_blocked:
        return
    await db.execute(
        update(AppUser)
        .where(AppUser.id == target.id)
        .values(is_blocked=True, blocked_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if target.is_active_account_admin:
        await ensure_account_admin_remains(db, actor.workspace_id)
    await sessions.delete_all_for_user(db, target.id)
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_BLOCKED,
        entity_id=target.id,
    )


async def unblock_user(db: AsyncSession, actor: Actor, user_id: UUID, /) -> None:
    """Разблокирует пользователя (FR-5a): вход проходит, сессии не восстанавливаются.

    Сбрасывает ``failed_login_count`` и ``login_locked_until``. Разблокировка активного —
    без ошибки и без события.
    """
    _require(actor, Capability.MANAGE_ACCOUNTS)
    await _lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await _load_target(db, actor.workspace_id, user_id)
    if not target.is_blocked:
        return
    await db.execute(
        update(AppUser)
        .where(AppUser.id == target.id)
        .values(
            is_blocked=False,
            blocked_at=None,
            failed_login_count=0,
            login_locked_until=None,
        )
        .execution_options(synchronize_session=False)
    )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_UNBLOCKED,
        entity_id=target.id,
    )


async def reset_password(
    db: AsyncSession,
    actor: Actor,
    hasher: PasswordHasher,
    sessions: SessionStore,
    user_id: UUID,
    /,
    *,
    one_time_password: SecretStr,
) -> None:
    """Сброс пароля администратором (FR-65, AC-45, AC-113).

    Новый одноразовый пароль проходит политику FR-52/FR-53; ``must_change_password = true``;
    счётчик неудач и блокировка входа сброшены; все сессии пользователя завершены.
    """
    _require(actor, Capability.MANAGE_ACCOUNTS)
    await _load_target(db, actor.workspace_id, user_id)  # 404 раньше политики пароля
    password = one_time_password.get_secret_value()
    _check_one_time_password(password)
    # медленный Argon2 — до протокола блокировок: ничего не удерживается на время хеширования
    password_hash = await hash_in_thread(hasher, password)
    await _lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await _load_target(db, actor.workspace_id, user_id)
    await db.execute(
        update(AppUser)
        .where(AppUser.id == target.id)
        .values(
            password_hash=password_hash,
            must_change_password=True,
            password_changed_at=utcnow(),
            failed_login_count=0,
            login_locked_until=None,
        )
        .execution_options(synchronize_session=False)
    )
    await sessions.delete_all_for_user(db, target.id)
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_PASSWORD_RESET,
        entity_id=target.id,
    )


async def revoke_sessions(
    db: AsyncSession, actor: Actor, sessions: SessionStore, user_id: UUID, /
) -> int:
    """Завершает все сессии пользователя (FR-62, AC-39); событие пишется и при 0 сессий."""
    _require(actor, Capability.MANAGE_ACCOUNTS)
    await _lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await _load_target(db, actor.workspace_id, user_id)
    removed = await sessions.delete_all_for_user(db, target.id)
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_SESSIONS_REVOKED,
        entity_id=target.id,
    )
    return removed


async def set_role(
    db: AsyncSession, actor: Actor, user_id: UUID, role: Role | None, /
) -> UserAccount:
    """Назначает, меняет или снимает роль (FR-12, FR-66, FR-69, AC-75).

    Та же роль — без изменений и без события. Событие: ``role_assigned`` (было «без роли»),
    ``role_changed``, ``role_removed``; ``details`` — ``role_from``/``role_to``. Сессии не
    затрагиваются: роль читается из БД на каждый запрос (FR-67). Недопустимое значение — 422.
    """
    _require(actor, Capability.ASSIGN_ROLES)
    new_role = _parse_role(role)
    await _lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await _load_target(db, actor.workspace_id, user_id)
    if target.role == new_role:
        return target.to_account(role=new_role)

    await db.execute(
        update(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == actor.workspace_id,
            WorkspaceMember.user_id == target.id,
        )
        .values(role=None if new_role is None else new_role.value)
        .execution_options(synchronize_session=False)
    )
    if target.is_active_account_admin and new_role not in ACCOUNT_ADMIN_ROLES:
        await ensure_account_admin_remains(db, actor.workspace_id)

    if target.role is None:
        action = EventAction.USER_ROLE_ASSIGNED
    elif new_role is None:
        action = EventAction.USER_ROLE_REMOVED
    else:
        action = EventAction.USER_ROLE_CHANGED
    details = UserEventDetails(
        role_from=None if target.role is None else target.role.value,
        role_to=None if new_role is None else new_role.value,
    )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=action,
        entity_id=target.id,
        details=details,
    )
    return target.to_account(role=new_role)


async def list_accounts(
    db: AsyncSession, actor: Actor, params: PageParams
) -> tuple[list[UserAccount], bool]:
    """Страница учётных записей пространства актора (FR-4, AC-2, D-34).

    Сортировка ``login ASC, id ASC`` (``id`` — тай-брейкер, страницы не пересекаются). Роль
    читается вторым запросом по идентификаторам страницы: ``paginate`` работает с одной
    сущностью. Второй элемент — признак следующей страницы.
    """
    _require(actor, Capability.MANAGE_ACCOUNTS)
    stmt = (
        select(AppUser)
        # ревью T17/T18: password_hash и счётчики входа в выборку не попадают
        .options(
            load_only(
                AppUser.id,
                AppUser.login,
                AppUser.is_blocked,
                AppUser.must_change_password,
                AppUser.created_at,
            )
        )
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(WorkspaceMember.workspace_id == actor.workspace_id)
        .order_by(AppUser.login, AppUser.id)
    )
    users, has_next = await paginate(db, stmt, params)
    if not users:
        return [], has_next
    role_rows = await db.execute(
        select(WorkspaceMember.user_id, WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == actor.workspace_id,
            WorkspaceMember.user_id.in_([user.id for user in users]),
        )
    )
    roles = {row.user_id: row.role for row in role_rows}
    items = [
        UserAccount(
            id=user.id,
            login=user.login,
            role=None if roles[user.id] is None else Role(roles[user.id]),
            is_blocked=user.is_blocked,
            must_change_password=user.must_change_password,
            created_at=user.created_at,
        )
        for user in users
    ]
    return items, has_next


async def get_account(db: AsyncSession, actor: Actor, user_id: UUID, /) -> UserAccount:
    """Учётная запись в пространстве актора; чужая и несуществующая — ``NotFound`` (FR-13)."""
    _require(actor, Capability.MANAGE_ACCOUNTS)
    target = await _load_target(db, actor.workspace_id, user_id)
    return target.to_account(role=target.role)
