"""Фикстуры обновления spec 002 (AC-20...AC-23, AC-25, AC-26, AC-29), R3-T13. Не тест-модуль.

Схема D-12 (plan 002): ``committed``-тест стартует на head, ``to_schema_0005`` делает
``alembic downgrade 0005``, данные «предыдущей версии» создаются фабриками в схеме 0005
(роль ``mixed`` ставится чистым SQL, сессии - через ``SessionStore``, а не входом), затем
``to_head`` / ``try_upgrade`` применяют миграцию 0006 подпроцессом alembic, после каждого шага
движок пересоздаётся (``dispose``): asyncpg кэширует подготовленные выражения по схеме.

Логины синтетические и валидные по ``ck_app_user_login_format`` (минимум 3 символа): короткие
имена из spec (``m1``, ``u1``) получают префикс ``u002.``: ``u002.m1``. Ключ в словаре
``World.users`` - короткое имя из spec (``"m1"``).

Сбой AC-29 внедряется триггерами БД (plan D-8), в коде поставки крючков нет.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text

from tests.db_support import database_url_from_env, run_alembic

if TYPE_CHECKING:
    from collections.abc import Collection

    from sqlalchemy.engine import Row

    from tests.conftest import ApiEnv
    from tests.factories import UserRow, WorkspaceRow

__all__ = [
    "FAILURE_MARK",
    "PREFIX",
    "World",
    "alembic_ok",
    "alembic_versions",
    "audit_rows",
    "data_fingerprint",
    "db_now",
    "install_failure",
    "make_ac20_world",
    "make_ac22_world",
    "make_mixed",
    "make_plain",
    "member_updated_at",
    "mixed_ids",
    "remove_failure",
    "roles_by_login",
    "seed_journal",
    "to_head",
    "to_schema_0005",
    "try_upgrade",
]

PREFIX = "u002."
FAILURE_MARK = "gt_test_injected_failure"
_FAIL_FUNCTION = "gt_test_fail_0006"
_PAST = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)

# таблицы, которые миграция 0006 не должна менять ни одним байтом (FR-14)
UNTOUCHED_TABLES = (
    "app_user",
    "project",
    "project_member",
    "task",
    "comment",
    "user_session",
    "workspace",
)


@dataclass(frozen=True)
class World:
    """Фикстура AC-20 / AC-22: пространство, пользователи по коротким именам и объекты данных."""

    ws: WorkspaceRow
    users: dict[str, UserRow]
    tokens: dict[str, str] = field(default_factory=dict)
    project_p: uuid.UUID | None = None
    project_pm: uuid.UUID | None = None
    task_t2: uuid.UUID | None = None
    comment_id: uuid.UUID | None = None

    def uid(self, name: str) -> uuid.UUID:
        return self.users[name].id


# --- alembic ----------------------------------------------------------------------------


async def _dispose(env: ApiEnv) -> None:
    engine = env.sessionmaker.kw["bind"]
    await engine.dispose()


async def try_upgrade(env: ApiEnv) -> subprocess.CompletedProcess[str]:
    """``alembic upgrade head`` подпроцессом без проверки кода возврата (AC-29)."""
    result = await asyncio.to_thread(run_alembic, database_url_from_env(), "upgrade", "head")
    await _dispose(env)
    return result


async def alembic_ok(env: ApiEnv, *args: str) -> subprocess.CompletedProcess[str]:
    """Команда alembic подпроцессом; код возврата 0 обязателен."""
    result = await asyncio.to_thread(run_alembic, database_url_from_env(), *args)
    await _dispose(env)
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    return result


async def to_schema_0005(env: ApiEnv) -> None:
    """head -> ``downgrade 0005``: схема предыдущей версии (CHECK с ``mixed``), версия 0005."""
    await alembic_ok(env, "downgrade", "0005")
    assert await alembic_versions(env) == ["0005"]


async def to_head(env: ApiEnv) -> None:
    """``alembic upgrade head`` с проверкой кода возврата и ``dispose`` движка."""
    await alembic_ok(env, "upgrade", "head")


async def alembic_versions(env: ApiEnv) -> list[str]:
    rows = await env.execute(text("SELECT version_num FROM alembic_version"))
    assert rows is not None
    return [str(r[0]) for r in rows]


async def db_now(env: ApiEnv) -> datetime:
    """Реальное время сервера БД (``clock_timestamp``): граница окна ``[t0, t1]`` (D-7)."""
    rows = await env.execute(text("SELECT clock_timestamp()"))
    assert rows is not None
    value: datetime = rows[0][0]
    return value


# --- данные в схеме 0005 -----------------------------------------------------------------


async def make_plain(
    env: ApiEnv,
    ws: WorkspaceRow,
    login: str,
    role: str | None,
    *,
    blocked: bool = False,
    must_change_password: bool = False,
    session: bool = False,
) -> tuple[UserRow, str | None]:
    """Пользователь с ролью трёх значений или ``None`` (без роли); сессия по желанию."""
    from tests.factories import make_user

    async with env.sessionmaker() as s:
        user = await make_user(
            s,
            workspace=ws,
            login=login,
            role=role,
            blocked=blocked,
            must_change_password=must_change_password,
        )
        token = await _maybe_session(env, s, user, session)
        await s.commit()
    return user, token


async def make_mixed(
    env: ApiEnv,
    ws: WorkspaceRow,
    login: str,
    *,
    blocked: bool = False,
    must_change_password: bool = False,
    session: bool = False,
) -> tuple[UserRow, str | None]:
    """Бывший СМ в схеме 0005: фабрика с ролью ``NULL`` + ``UPDATE ... role = 'mixed'`` (D-12).

    Возвращает ``UserRow`` (роль ``mixed``) и сырой токен сессии (если ``session=True``).
    """
    from tests.factories import make_user

    async with env.sessionmaker() as s:
        user = await make_user(
            s,
            workspace=ws,
            login=login,
            role=None,
            blocked=blocked,
            must_change_password=must_change_password,
        )
        result = await s.execute(
            text(
                "UPDATE workspace_member SET role = 'mixed' "
                "WHERE workspace_id = :w AND user_id = :u"
            ),
            {"w": ws.id, "u": user.id},
        )
        assert result.rowcount == 1  # type: ignore[attr-defined]
        token = await _maybe_session(env, s, user, session)
        await s.commit()
    return replace(user, role="mixed"), token


async def _maybe_session(env: ApiEnv, s: Any, user: UserRow, session: bool) -> str | None:
    if not session:
        return None
    from app.core.secrets import ensure_secret_key
    from app.domain.auth.sessions import SessionStore

    store = SessionStore(
        ensure_secret_key(env.settings),
        idle_timeout=env.settings.session_idle_timeout,
        absolute_timeout=env.settings.session_absolute_timeout,
    )
    now = env.clock.now()
    token: str = await store.create(s, user_id=user.id, workspace_id=user.workspace_id, now=now)
    return token


async def seed_journal(
    env: ApiEnv, ws: WorkspaceRow, users: dict[str, UserRow], actor: str | None
) -> int:
    """Прежний журнал: ``user.created`` на каждого пользователя + история ``mixed`` (FR-20).

    Автор - ``actor`` (короткое имя) или «система». Возвращает число записей журнала (N).
    Времена фиксированные и в прошлом, чтобы окно ``[t0, t1]`` их не захватывало.
    """
    from tests.factories import make_domain_event

    async with env.sessionmaker() as s:
        for i, (_, user) in enumerate(sorted(users.items())):
            await make_domain_event(
                s,
                workspace_id=ws.id,
                actor_id=None if actor is None else users[actor].id,
                entity_type="user",
                entity_id=user.id,
                action="user.created",
                in_audit=True,
                occurred_at=_PAST + timedelta(minutes=i),
            )
            if user.role == "mixed":
                await make_domain_event(
                    s,
                    workspace_id=ws.id,
                    actor_id=None if actor is None else users[actor].id,
                    entity_type="user",
                    entity_id=user.id,
                    action="user.role_assigned",
                    in_audit=True,
                    details={"role_from": None, "role_to": "mixed"},
                    occurred_at=_PAST + timedelta(hours=1, minutes=i),
                )
        await s.commit()
    return len(await audit_rows(env))


async def _project_data(
    env: ApiEnv,
    ws: WorkspaceRow,
    owner_p: UserRow,
    members_p: list[UserRow],
    task_author: UserRow,
    task_assignee: UserRow,
    comment_author: UserRow,
    owner_pm: UserRow,
    members_pm: list[UserRow],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    from tests.factories import make_comment, make_project, make_project_member, make_task

    async with env.sessionmaker() as s:
        p = await make_project(s, workspace_id=ws.id, owner_id=owner_p.id, name="P")
        for m in members_p:
            await make_project_member(s, project_id=p.id, user_id=m.id, workspace_id=ws.id)
        t2 = await make_task(
            s,
            project_id=p.id,
            workspace_id=ws.id,
            created_by=task_author.id,
            assignee_id=task_assignee.id,
            title="T2",
        )
        c = await make_comment(
            s, task_id=t2.id, workspace_id=ws.id, created_by=comment_author.id, body="c"
        )
        pm = await make_project(s, workspace_id=ws.id, owner_id=owner_pm.id, name="PM")
        for m in members_pm:
            await make_project_member(s, project_id=pm.id, user_id=m.id, workspace_id=ws.id)
        await s.commit()
    return p.id, pm.id, t2.id, c.id


async def make_ac20_world(env: ApiEnv) -> tuple[World, int]:
    """Фикстура AC-20 в схеме 0005. Возвращает ``(World, N)``, N - записей в журнале.

    ``ta1`` (активный ТА), ``ba.owner``, ``ba.pm``, ``u1``; ``m1`` (mixed, активный,
    постоянный пароль, сессия S), ``m2`` (mixed, заблокирован), ``m3`` (mixed, активный,
    одноразовый пароль не сменён); проект P (владелец ``ba.owner``; участники ``ba.owner``,
    ``m1``, ``u1``), задача T2 (автор ``ba.owner``, исполнитель ``m1``), комментарий (автор
    ``m1``); проект PM (владелец ``m1``; участники ``m1``, ``ba.pm``).
    """
    from tests.factories import make_workspace

    await to_schema_0005(env)
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        await s.commit()
    users: dict[str, UserRow] = {}
    tokens: dict[str, str] = {}
    for name, role in (
        ("ta1", "tech_admin"),
        ("ba.owner", "business_admin"),
        ("ba.pm", "business_admin"),
        ("u1", "user"),
    ):
        users[name], _ = await make_plain(env, ws, f"{PREFIX}{name}", role)
    users["m1"], tok = await make_mixed(env, ws, f"{PREFIX}m1", session=True)
    assert tok is not None
    tokens["m1"] = tok
    users["m2"], _ = await make_mixed(env, ws, f"{PREFIX}m2", blocked=True)
    users["m3"], _ = await make_mixed(env, ws, f"{PREFIX}m3", must_change_password=True)

    p, pm, t2, c = await _project_data(
        env,
        ws,
        owner_p=users["ba.owner"],
        members_p=[users["ba.owner"], users["m1"], users["u1"]],
        task_author=users["ba.owner"],
        task_assignee=users["m1"],
        comment_author=users["m1"],
        owner_pm=users["m1"],
        members_pm=[users["m1"], users["ba.pm"]],
    )
    n = await seed_journal(env, ws, users, actor="ta1")
    world = World(
        ws=ws, users=users, tokens=tokens, project_p=p, project_pm=pm, task_t2=t2, comment_id=c
    )
    return world, n


async def make_ac22_world(env: ApiEnv, *, with_active_ta: bool) -> tuple[World, int]:
    """Фикстура AC-22 в схеме 0005. Возвращает ``(World, N)``.

    Единственный ТА ``ta.b`` заблокирован; ``m1`` (mixed, активный, постоянный пароль,
    владелец PM, участник PM вместе с ``ba.pm``); ``m3`` (mixed, активный, одноразовый пароль
    не сменён); ``m2`` (mixed, заблокирован). ``with_active_ta=True`` добавляет активного ТА
    ``ta.new`` с несменённым одноразовым паролем (вторая ветка AC-22).
    """
    from tests.factories import make_workspace

    await to_schema_0005(env)
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        await s.commit()
    users: dict[str, UserRow] = {}
    users["ta.b"], _ = await make_plain(env, ws, f"{PREFIX}ta.b", "tech_admin", blocked=True)
    users["ba.pm"], _ = await make_plain(env, ws, f"{PREFIX}ba.pm", "business_admin")
    if with_active_ta:
        users["ta.new"], _ = await make_plain(
            env, ws, f"{PREFIX}ta.new", "tech_admin", must_change_password=True
        )
    users["m1"], _ = await make_mixed(env, ws, f"{PREFIX}m1")
    users["m2"], _ = await make_mixed(env, ws, f"{PREFIX}m2", blocked=True)
    users["m3"], _ = await make_mixed(env, ws, f"{PREFIX}m3", must_change_password=True)
    _, pm, _, _ = await _project_data(
        env,
        ws,
        owner_p=users["ba.pm"],
        members_p=[users["ba.pm"]],
        task_author=users["ba.pm"],
        task_assignee=users["ba.pm"],
        comment_author=users["ba.pm"],
        owner_pm=users["m1"],
        members_pm=[users["m1"], users["ba.pm"]],
    )
    n = await seed_journal(env, ws, users, actor=None)
    return World(ws=ws, users=users, project_pm=pm), n


# --- чтение состояния -------------------------------------------------------------------


async def audit_rows(env: ApiEnv) -> list[Row[Any]]:
    """Все строки ``domain_event`` по возрастанию ``id``, все столбцы (сравнение побайтно)."""
    rows = await env.execute(
        text(
            "SELECT id, workspace_id, occurred_at, actor_id, entity_type, entity_id, action, "
            "changed_fields, project_id, deal_id, in_audit, changes, details "
            "FROM domain_event ORDER BY id"
        )
    )
    assert rows is not None
    return list(rows)


async def roles_by_login(env: ApiEnv) -> dict[str, str | None]:
    """``{login: role}`` по всем строкам ``workspace_member`` (``None`` - без роли)."""
    rows = await env.execute(
        text("SELECT u.login, m.role FROM workspace_member m JOIN app_user u ON u.id = m.user_id")
    )
    assert rows is not None
    return {str(r[0]): r[1] for r in rows}


def mixed_ids(world: World) -> list[uuid.UUID]:
    """Идентификаторы бывших СМ фикстуры (роль ``mixed`` в схеме 0005)."""
    return [u.id for u in world.users.values() if u.role == "mixed"]


async def member_updated_at(env: ApiEnv) -> dict[tuple[uuid.UUID, uuid.UUID], datetime]:
    """``{(workspace_id, user_id): updated_at}`` по всем строкам ``workspace_member``."""
    rows = await env.execute(text("SELECT workspace_id, user_id, updated_at FROM workspace_member"))
    assert rows is not None
    return {(r[0], r[1]): r[2] for r in rows}


async def data_fingerprint(
    env: ApiEnv, *, skip_updated: Collection[uuid.UUID] = ()
) -> dict[str, list[str]]:
    """Текст каждой строки таблиц, которые миграция не трогает, + ``workspace_member`` без
    ``role``. ``updated_at`` строки ``workspace_member`` входит в отпечаток, кроме строк
    пользователей ``skip_updated`` (бывшие СМ: миграция вправе менять у них ``role`` и
    ``updated_at``, plan §4.5; их ``updated_at`` проверяется отдельно)."""
    result: dict[str, list[str]] = {}
    for table in UNTOUCHED_TABLES:
        rows = await env.execute(
            text(f"SELECT t::text FROM {table} t ORDER BY t::text")  # noqa: S608
        )
        assert rows is not None
        result[table] = [str(r[0]) for r in rows]
    skip = ",".join(f"'{uuid.UUID(str(u))}'" for u in skip_updated)
    skip_array = f"ARRAY[{skip}]::uuid[]" if skip else "'{}'::uuid[]"
    rows = await env.execute(
        text(
            "SELECT workspace_id::text || '|' || user_id::text || '|' || created_at::text || '|' "
            "|| coalesce(created_by::text, '-') || '|' "
            f"|| CASE WHEN user_id = ANY({skip_array}) THEN '-' ELSE updated_at::text END "  # noqa: S608
            "FROM workspace_member ORDER BY 1"
        )
    )
    assert rows is not None
    result["workspace_member(keys)"] = [str(r[0]) for r in rows]
    return result


# --- внедрение сбоя (plan D-8) ----------------------------------------------------------


async def install_failure(
    env: ApiEnv, *, on: Literal["version", "event"], entity_id: uuid.UUID | None = None
) -> None:
    """Временный триггер, роняющий миграцию.

    ``on="version"`` - ``BEFORE UPDATE ON alembic_version`` (сбой после ролей, журнала и CHECK,
    до отметки версии). ``on="event"`` - ``BEFORE INSERT ON domain_event`` для записи с
    ``entity_id``: сбой посреди записи журнала (роли уже сняты, записи, идущие в журнале раньше
    неё, уже вставлены, сама запись и следующие - нет). Сообщение ошибки содержит
    ``FAILURE_MARK``.
    """
    await env.execute(
        text(
            f"CREATE FUNCTION {_FAIL_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ "  # noqa: S608
            f"BEGIN RAISE EXCEPTION '{FAILURE_MARK}'; END; $$"
        )
    )
    if on == "version":
        await env.execute(
            text(
                f"CREATE TRIGGER {_FAIL_FUNCTION}_version BEFORE UPDATE ON alembic_version "
                f"FOR EACH ROW EXECUTE FUNCTION {_FAIL_FUNCTION}()"
            )
        )
    else:
        assert entity_id is not None, "для on='event' нужен entity_id"
        key = uuid.UUID(str(entity_id))
        await env.execute(
            text(
                f"CREATE TRIGGER {_FAIL_FUNCTION}_event BEFORE INSERT ON domain_event "
                f"FOR EACH ROW WHEN (NEW.entity_id = '{key}') "
                f"EXECUTE FUNCTION {_FAIL_FUNCTION}()"
            )
        )


async def remove_failure(env: ApiEnv) -> None:
    """Убирает триггеры и функцию сбоя («сбой устранён»)."""
    await env.execute(text(f"DROP TRIGGER IF EXISTS {_FAIL_FUNCTION}_version ON alembic_version"))
    await env.execute(text(f"DROP TRIGGER IF EXISTS {_FAIL_FUNCTION}_event ON domain_event"))
    await env.execute(text(f"DROP FUNCTION IF EXISTS {_FAIL_FUNCTION}()"))
