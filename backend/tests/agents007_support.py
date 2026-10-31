"""Общие помощники тестов 007 (plan §5): мир агентов.

Не тест-модуль. R7-T08 создаёт ``CLOCK``, ``make_agent`` и адреса; ``make_key``, ``bearer`` и
``make_world007`` добавляют R7-T10 и R7-T12.

Тела секретов в сообщения ``assert`` не попадают: помощники возвращают их только в объектах.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.conftest import ApiEnv
    from tests.factories import ApiKeyRow, UserRow, WorkspaceRow

# 2026-11-02 07:00 UTC = 10:00 по Москве (spec §5, plan §5)
CLOCK = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)

API = "/api/v1"
ADMIN_AGENTS = f"{API}/admin/agents"
ADMIN_USERS = f"{API}/admin/users"
AUDIT = f"{API}/admin/audit"
USERS_DIRECTORY = f"{API}/users"
LOGIN_URL = f"{API}/auth/login"
ME_URL = f"{API}/me"


async def make_agent(
    env: ApiEnv, login: str, role: str | None, *, workspace: WorkspaceRow | None = None
) -> UserRow:
    """Учётная запись агента напрямую в БД (с фиксацией): ``is_agent=true``, хеш случайного
    значения (пароль не известен), без сессий. Без ``workspace`` создаётся новое пространство."""
    import secrets

    kwargs: dict[str, object] = {"password": secrets.token_urlsafe(32)}
    return await env.new_user(workspace=workspace, login=login, role=role, is_agent=True, **kwargs)


async def make_key(
    env: ApiEnv,
    user: UserRow,
    *,
    created_by: UserRow,
    name: str = "k",
    created_at: datetime = CLOCK,
    ttl: timedelta = timedelta(days=90),
    revoked_at: datetime | None = None,
    last_used_at: datetime | None = None,
    secret: str | None = None,
) -> ApiKeyRow:
    """Ключ агента напрямую в БД (с фиксацией): ``expires_at = created_at + ttl``; при
    ``revoked_at`` отозвавшим записывается ``created_by``. В БД попадает только ``sha256``."""
    from tests.factories import make_api_key

    async with env.sessionmaker() as session:
        row = await make_api_key(
            session,
            user=user,
            created_by=created_by,
            secret=secret,
            name=name,
            created_at=created_at,
            expires_at=created_at + ttl,
            revoked_at=revoked_at,
            revoked_by=created_by if revoked_at is not None else None,
            last_used_at=last_used_at,
        )
        await session.commit()
    return row


def bearer(secret: str) -> dict[str, str]:
    """Заголовок ``Authorization: Bearer <ключ>`` (cookie не нужна)."""
    return {"Authorization": f"Bearer {secret}"}


# --- R7-T12: мир spec §5 (plan §5) ------------------------------------------------------------


class HiddenSecret(str):
    """Секрет ключа, чей ``repr`` не раскрывает значение: трейсбэки pytest (аргументы кадров,
    пояснения ``assert``) печатают ``repr``. Значение строки не меняется (``==``, ``+``, ``in``)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "'<секрет ключа>'"


def hide(row: ApiKeyRow) -> ApiKeyRow:
    """Та же строка ключа, но ``secret`` — ``HiddenSecret`` (``repr`` строки не печатает секрет)."""
    from tests.factories import ApiKeyRow as _Row

    return _Row(id=row.id, secret=HiddenSecret(row.secret))


PROJECTS_URL = f"{API}/projects"
MY_TASKS_URL = f"{API}/me/tasks"
LOGOUT_URL = f"{API}/auth/logout"
PASSWORD_URL = f"{API}/auth/password"
HEALTH_URL = f"{API}/health"

# FR-13: тело единого отказа по ключу (ровно это, без дополнительных полей)
NOT_AUTHENTICATED_BODY = {"detail": "Требуется вход в систему", "code": "not_authenticated"}

# plan §4.7, PD-3: имена маршрутов, доступных по ключу (FR-17, FR-18…FR-27)
AGENT_OPERATION_NAMES: frozenset[str] = frozenset(
    {
        "me",
        "list_projects",
        "list_my_tasks",
        "list_project_tasks",
        "get_task",
        "create_task",
        "create_subtask",
        "update_task",
        "list_comments",
        "create_comment",
    }
)


@dataclass
class World007:
    """Мир spec §5: пространство ``ws``; люди с cookie-сессиями, созданными на ``CLOCK``;
    агенты ``agent_u`` (П), ``agent_ba`` (БА); проекты ``P``, ``P2``; задачи ``T1``…``T3``, ``T9``;
    комментарий ``c1``; ключи ``K_u``, ``K_ba``."""

    ws: WorkspaceRow
    ta1: UserRow
    ba1: UserRow
    u1: UserRow
    agent_u: UserRow
    agent_ba: UserRow
    P: uuid.UUID  # noqa: N815
    P2: uuid.UUID  # noqa: N815
    T1: uuid.UUID  # noqa: N815
    T2: uuid.UUID  # noqa: N815
    T3: uuid.UUID  # noqa: N815
    T9: uuid.UUID  # noqa: N815
    c1: uuid.UUID
    K_u: ApiKeyRow  # noqa: N815
    K_ba: ApiKeyRow  # noqa: N815
    cookies: dict[str, str] = field(default_factory=dict)

    def cookie(self, who: str) -> str:
        """Сырой токен cookie-сессии ``ta1``/``ba1``/``u1``."""
        return self.cookies[who]


async def seed_now(
    env: ApiEnv,
    ws: WorkspaceRow,
    role: str | None,
    *,
    login: str,
    password: str | None = None,
) -> tuple[UserRow, str]:
    """Человек в ``ws`` и одна cookie-сессия, созданная на ТЕКУЩЕМ времени часов теста
    (в отличие от ``admin_support.seed``, где сессия создаётся на ``FIXED_NOW``)."""
    from app.core.secrets import ensure_secret_key
    from app.domain.auth.sessions import SessionStore
    from tests.factories import PLACEHOLDER_HASH, make_user

    store = SessionStore(
        ensure_secret_key(env.settings),
        idle_timeout=env.settings.session_idle_timeout,
        absolute_timeout=env.settings.session_absolute_timeout,
    )
    kwargs: dict[str, Any] = (
        {"password": password} if password is not None else {"password_hash": PLACEHOLDER_HASH}
    )
    async with env.sessionmaker() as session:
        user = await make_user(session, workspace=ws, role=role, login=login, **kwargs)
        token = await store.create(
            session, user_id=user.id, workspace_id=user.workspace_id, now=env.clock.now()
        )
        await session.commit()
    return user, token


async def make_world007(env: ApiEnv) -> World007:
    """Мир spec §5. Часы ставятся на ``CLOCK`` до создания сессий: cookie действуют на
    ``CLOCK`` и в ближайшие минуты (AC-8, AC-40)."""
    from datetime import date

    from tests.admin_support import new_workspace
    from tests.factories import make_comment, make_project, make_project_member, make_task

    env.clock.set(CLOCK)
    ws = await new_workspace(env)
    ta1, tok_ta = await seed_now(env, ws, "tech_admin", login="ta1")
    ba1, tok_ba = await seed_now(env, ws, "business_admin", login="ba1")
    u1, tok_u = await seed_now(
        env, ws, "user", login="usr1"
    )  # «u1» короче 3 символов (login_format)
    agent_u = await make_agent(env, "agent.u", "user", workspace=ws)
    agent_ba = await make_agent(env, "agent.ba", "business_admin", workspace=ws)

    async with env.sessionmaker() as s:
        p = await make_project(s, workspace_id=ws.id, owner_id=ba1.id, name="P")
        p2 = await make_project(s, workspace_id=ws.id, owner_id=ba1.id, name="P2")
        for user in (ba1, u1, agent_u, agent_ba):
            await make_project_member(
                s, project_id=p.id, user_id=user.id, workspace_id=ws.id, created_by=ba1.id
            )
        await make_project_member(
            s, project_id=p2.id, user_id=ba1.id, workspace_id=ws.id, created_by=ba1.id
        )
        t1 = await make_task(
            s,
            project_id=p.id,
            workspace_id=ws.id,
            created_by=ba1.id,
            title="T1",
            assignee_id=agent_u.id,
            status="todo",
            position=1024,
        )
        t2 = await make_task(
            s,
            project_id=p.id,
            workspace_id=ws.id,
            created_by=ba1.id,
            title="T2",
            assignee_id=u1.id,
            status="todo",
            position=2048,
        )
        t3 = await make_task(
            s,
            project_id=p.id,
            workspace_id=ws.id,
            created_by=agent_u.id,
            title="T3",
            description="",
            assignee_id=agent_u.id,
            status="in_progress",
            due_date=date(2026, 10, 1),
            position=1024,
        )
        t9 = await make_task(s, project_id=p2.id, workspace_id=ws.id, created_by=ba1.id, title="T9")
        c1 = await make_comment(s, task_id=t1.id, workspace_id=ws.id, created_by=u1.id, body="c1")
        await s.commit()

    k_u = hide(await make_key(env, agent_u, created_by=ta1, name="K_u"))
    k_ba = hide(await make_key(env, agent_ba, created_by=ta1, name="K_ba"))
    return World007(
        ws=ws,
        ta1=ta1,
        ba1=ba1,
        u1=u1,
        agent_u=agent_u,
        agent_ba=agent_ba,
        P=p.id,
        P2=p2.id,
        T1=t1.id,
        T2=t2.id,
        T3=t3.id,
        T9=t9.id,
        c1=c1.id,
        K_u=k_u,
        K_ba=k_ba,
        cookies={"ta1": tok_ta, "ba1": tok_ba, "u1": tok_u},
    )


async def session_count(env: ApiEnv) -> int:
    """Число строк ``user_session`` во всей БД теста."""
    from sqlalchemy import text

    rows = await env.execute(text("SELECT count(*) FROM user_session"))
    assert rows is not None
    return int(rows[0][0])


async def table_digest(env: ApiEnv, *tables: str) -> dict[str, str]:
    """Отпечаток содержимого таблиц: ``md5`` упорядоченных строк (для «данные не изменены»)."""
    from sqlalchemy import text

    out: dict[str, str] = {}
    for name in tables:
        rows = await env.execute(
            text(
                f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) "  # noqa: S608
                f'FROM "{name}" x'
            )
        )
        assert rows is not None
        out[name] = f"{rows[0][0]}:{rows[0][1]}"
    return out


def mutated_secret(secret: str) -> HiddenSecret:
    """Тот же формат ``gtk_…``, изменён один символ в середине."""
    i = len(secret) // 2
    repl = "A" if secret[i] != "A" else "B"
    return HiddenSecret(secret[:i] + repl + secret[i + 1 :])


# --- R7-T14: чтение хранилища событий (FR-42) ---------------------------------------------------


async def domain_events(env: ApiEnv, workspace_id: uuid.UUID) -> list[Any]:
    """Все строки ``domain_event`` пространства по порядку ``id`` (столбцы — атрибуты строки)."""
    from sqlalchemy import text

    rows = await env.execute(
        text("SELECT * FROM domain_event WHERE workspace_id = :w ORDER BY id").bindparams(
            w=workspace_id
        )
    )
    assert rows is not None
    return list(rows)


# --- R7-T15: операции записи по ключу (FR-23…FR-28) ----------------------------------------------


def task_url(task_id: Any) -> str:
    return f"{API}/tasks/{task_id}"


def project_tasks_url(project_id: Any) -> str:
    return f"{API}/projects/{project_id}/tasks"


def subtasks_url(task_id: Any) -> str:
    return f"{API}/tasks/{task_id}/subtasks"


def comments_url(task_id: Any) -> str:
    return f"{API}/tasks/{task_id}/comments"


def board_url(project_id: Any) -> str:
    return f"{API}/projects/{project_id}/board"


async def task_snapshot(env: ApiEnv, task_id: uuid.UUID) -> dict[str, Any]:
    """Вся строка ``task`` (все столбцы) свежей сессией — для «задача не изменилась ни в одном
    поле» (всё или ничего)."""
    from sqlalchemy import text

    rows = await env.execute(text("SELECT * FROM task WHERE id = :t").bindparams(t=task_id))
    assert rows, "задача не найдена в БД"
    return dict(rows[0]._mapping)


async def project_task_count(env: ApiEnv, project_id: uuid.UUID) -> int:
    """Число строк ``task`` проекта (включая подзадачи и мягко удалённые)."""
    from sqlalchemy import text

    rows = await env.execute(
        text("SELECT count(*) FROM task WHERE project_id = :p").bindparams(p=project_id)
    )
    assert rows is not None
    return int(rows[0][0])


async def task_comment_count(env: ApiEnv, task_id: uuid.UUID) -> int:
    """Число строк ``comment`` задачи (включая мягко удалённые)."""
    from sqlalchemy import text

    rows = await env.execute(
        text("SELECT count(*) FROM comment WHERE task_id = :t").bindparams(t=task_id)
    )
    assert rows is not None
    return int(rows[0][0])
