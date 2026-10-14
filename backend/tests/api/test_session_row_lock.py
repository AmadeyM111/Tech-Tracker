"""T16a: ``get_actor`` не держит блокировку строки сессии до конца запроса (plan §4.5, §4.6).

Дефект (T16, попытка 3): ``SessionStore.resolve`` делает ``UPDATE user_session SET
last_activity_at`` в транзакции запроса, строка удерживается до конца запроса. Администратор A
выполняет действие (держит свою строку сессии, ждёт advisory-блокировку), администратор C
блокирует A / сбрасывает ему пароль / завершает его сессии (держит advisory-блокировку, ждёт
строку сессии A) -> deadlock, 500. Тот же цикл у ``POST /auth/password`` пользователя Y при
параллельном действии над Y.

Контракт исправления (tasks.md T16a, D-14, FR-59): активность фиксируется сразу после
``resolve`` (до обработчика), поэтому:
- строка сессии не удерживается обработчиком -> нет цикла;
- 4xx/5xx после ``get_actor`` не откатывают ``last_activity_at``;
- истёкшая сессия удаляется и это удаление переживает 401;
- остальная работа обработчика остаётся в одной транзакции запроса и откатывается целиком
  (D-3); границы сроков, фон (AC-79) и число COMMIT не меняются.

Реальные параллельные запросы: ``committed_api_env`` (чистая схема, соединение на запрос),
ASGITransport, временные роуты поверх настоящих ``get_actor``/``require_capability``/сервиса
учётных записей (HTTP-роутов администрирования до T17 нет). Время — ``FixedClock``.

Нет ``from __future__ import annotations``: FastAPI разбирает аннотации локальных обработчиков.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, Request
from pydantic import SecretStr
from sqlalchemy import event, select, text, update

from app.api.deps import get_actor, require_capability
from app.core.db import DbSession
from app.core.errors import Forbidden, NotFound, ProjectArchived, Unprocessable
from app.domain.access.roles import Actor, Capability
from app.domain.users import service as users_service
from tests.conftest import FIXED_NOW, ApiEnv
from tests.factories import PLACEHOLDER_HASH, UserRow, get_table, make_user, make_workspace

PW = "Sup3r-secret-Pa55phrase-xyz"
OTP = "Tmp-Pa55phrase-xyz-777"
ITERATIONS = 100
MAX_FAILURES = 3  # на текущем коде дедлок детерминирован: после 3 сбоев прерываем (скорость)
OK_STATUSES = {200, 204, 401, 403, 404, 422}
HOLD_HEADER = "X-T-Hold"


# --- окружение: временные роуты и вспомогательные функции ---------------------------------


@dataclass
class Gate:
    """Удерживает помеченный заголовком запрос внутри обработчика до ``release``."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def hold(self) -> None:
        self.entered.set()
        await asyncio.wait_for(self.release.wait(), timeout=15)


@dataclass
class Hooks:
    gate: Gate | None = None


def _mount_routes(env: ApiEnv) -> Hooks:
    hooks = Hooks()

    async def act(
        user_id: uuid.UUID,
        action: str,
        request: Request,
        db: DbSession,
        actor: Annotated[Actor, Depends(require_capability(Capability.MANAGE_ACCOUNTS))],
    ) -> Any:
        """Админ-действие над пользователем; с ``X-T-Hold`` держится до ``release``."""
        if request.headers.get(HOLD_HEADER) == "1" and hooks.gate is not None:
            await hooks.gate.hold()
        state = request.app.state
        if action == "block":
            await users_service.block_user(db, actor, state.session_store, user_id)
        elif action == "reset":
            await users_service.reset_password(
                db,
                actor,
                state.password_hasher,
                state.session_store,
                user_id,
                one_time_password=SecretStr(OTP),
            )
        elif action == "revoke":
            await users_service.revoke_sessions(db, actor, state.session_store, user_id)
        else:  # pragma: no cover
            raise AssertionError(action)
        return {"ok": True}

    async def ping(actor: Annotated[Actor, Depends(get_actor)]) -> Any:
        return {"ok": True}

    async def fail(status: int, actor: Annotated[Actor, Depends(get_actor)]) -> Any:
        if status == 403:
            raise Forbidden()
        if status == 404:
            raise NotFound()
        if status == 409:
            raise ProjectArchived()
        if status == 422:
            raise Unprocessable(code="validation_error")
        raise RuntimeError("boom")  # 5xx: необработанное исключение

    async def write_then_fail(db: DbSession, actor: Annotated[Actor, Depends(get_actor)]) -> Any:
        """Запись обработчика, затем отказ: запись обязана откатиться (D-3)."""
        await db.execute(
            update(get_table("app_user"))
            .where(get_table("app_user").c.id == actor.user_id)
            .values(failed_login_count=3)
        )
        raise Unprocessable(code="validation_error")

    async def write_ok(db: DbSession, actor: Annotated[Actor, Depends(get_actor)]) -> Any:
        await db.execute(
            update(get_table("app_user"))
            .where(get_table("app_user").c.id == actor.user_id)
            .values(failed_login_count=2)
        )
        return {"ok": True}

    app = env.app
    app.add_api_route("/_t/act/{user_id}/{action}", act, methods=["POST"])
    app.add_api_route("/_t/ping", ping, methods=["GET", "POST"])
    app.add_api_route("/_t/fail/{status}", fail, methods=["POST"])
    app.add_api_route("/_t/write-then-fail", write_then_fail, methods=["POST"])
    app.add_api_route("/_t/write-ok", write_ok, methods=["POST"])
    return hooks


def _cookie(env: ApiEnv, token: str, **extra: str) -> dict[str, str]:
    return env.auth(token, **extra)


async def _seed_user(
    env: ApiEnv, workspace: Any, role: str | None, *, sessions: int = 1, password: str | None = None
) -> tuple[UserRow, list[str]]:
    """Пользователь с ``sessions`` действующими сессиями на ``FIXED_NOW``; токены."""
    from app.core.secrets import ensure_secret_key
    from app.domain.auth.sessions import SessionStore

    store = SessionStore(
        ensure_secret_key(env.settings),
        idle_timeout=env.settings.session_idle_timeout,
        absolute_timeout=env.settings.session_absolute_timeout,
    )
    async with env.sessionmaker() as session:
        kwargs: dict[str, Any] = {"password": password} if password else {}
        if not password:
            kwargs["password_hash"] = PLACEHOLDER_HASH
        user = await make_user(session, workspace=workspace, role=role, **kwargs)
        tokens = [
            await store.create(
                session, user_id=user.id, workspace_id=user.workspace_id, now=FIXED_NOW
            )
            for _ in range(sessions)
        ]
        await session.commit()
    return user, tokens


async def _new_workspace(env: ApiEnv) -> Any:
    async with env.sessionmaker() as session:
        ws = await make_workspace(session)
        await session.commit()
    return ws


async def _last_activity(env: ApiEnv, token: str) -> Any:
    table = get_table("user_session")
    rows = await env.execute(
        select(table.c.last_activity_at).where(table.c.id == env.token_id(token))
    )
    assert rows is not None
    return rows[0][0] if rows else None


async def _session_rows(env: ApiEnv, token: str) -> list[Any]:
    table = get_table("user_session")
    rows = await env.execute(select(table.c.id).where(table.c.id == env.token_id(token)))
    assert rows is not None
    return rows


async def _waiters(env: ApiEnv) -> int:
    async with env.sessionmaker() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock'"
                )
            )
        ).scalar_one()
    return int(count)


async def _wait_blocked_or_done(
    env: ApiEnv, task: "asyncio.Task[Any]", timeout: float = 1.5
) -> None:
    """Ждёт, пока запрос завершится или упрётся в чужую блокировку строки (воспроизведение)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not task.done() and asyncio.get_running_loop().time() < deadline:
        if await _waiters(env) > 0:
            return
        await asyncio.sleep(0.01)


async def _wait_event(event_: asyncio.Event, task: "asyncio.Task[Any]") -> None:
    """Ждёт ``event_`` или завершения ``task`` (запрос мог завершиться раньше)."""
    waiter = asyncio.ensure_future(event_.wait())
    try:
        await asyncio.wait({waiter, task}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()


async def _call(
    coro_factory: Callable[[], Any],
) -> tuple[str, int | str]:
    """Результат запроса: ``("status", код)`` или ``("exc", имя исключения)``."""
    try:
        response: httpx.Response = await coro_factory()
    except Exception as exc:  # DBAPIError / DeadlockDetectedError из приложения
        return "exc", f"{type(exc).__name__}: {str(getattr(exc, 'orig', exc))[:50]}"
    return "status", response.status_code


def _bad(result: tuple[str, int | str]) -> bool:
    kind, value = result
    return kind == "exc" or value not in OK_STATUSES


# --- дедлок: администратор над администратором --------------------------------------------

A_ACTIONS = ("revoke", "reset", "block")
C_ACTIONS = ("block", "reset", "revoke")


async def test_fr62_concurrent_admin_actions_on_working_admin_have_no_deadlock(
    committed_api_env: ApiEnv,
) -> None:
    """FR-5, FR-62, FR-67, D-14: A выполняет действие, C блокирует/сбрасывает/завершает A.

    Режимы (i % 3): 0 — A удерживается внутри обработчика, C стартует после (цикл на
    текущем коде); 1 — C удерживается, A выполняется целиком; 2 — без удержания, гонка.
    """
    env = committed_api_env
    hooks = _mount_routes(env)
    failures: list[str] = []
    done = 0
    for i in range(ITERATIONS):
        ws = await _new_workspace(env)
        a, (tok_a,) = await _seed_user(env, ws, "tech_admin")
        b, _ = await _seed_user(env, ws, "tech_admin")
        c, (tok_c,) = await _seed_user(env, ws, "tech_admin")
        a_action, c_action = A_ACTIONS[i % 3], C_ACTIONS[i % 3]
        mode = i % 3
        hooks.gate = Gate()

        def req_a(hold: bool, tok_a: str = tok_a, b: UserRow = b, a_action: str = a_action) -> Any:
            headers = _cookie(env, tok_a, **({HOLD_HEADER: "1"} if hold else {}))
            return env.client.post(f"/_t/act/{b.id}/{a_action}", headers=headers)

        def req_c(hold: bool, tok_c: str = tok_c, a: UserRow = a, c_action: str = c_action) -> Any:
            headers = _cookie(env, tok_c, **({HOLD_HEADER: "1"} if hold else {}))
            return env.client.post(f"/_t/act/{a.id}/{c_action}", headers=headers)

        results: list[tuple[str, int | str]]
        if mode == 0:
            task_a = asyncio.ensure_future(_call(lambda: req_a(True)))
            await _wait_event(hooks.gate.entered, task_a)
            task_c = asyncio.ensure_future(_call(lambda: req_c(False)))
            await _wait_blocked_or_done(env, task_c)
            hooks.gate.release.set()
            results = [await task_a, await task_c]
        elif mode == 1:
            task_c = asyncio.ensure_future(_call(lambda: req_c(True)))
            await _wait_event(hooks.gate.entered, task_c)
            task_a = asyncio.ensure_future(_call(lambda: req_a(False)))
            await _wait_blocked_or_done(env, task_a)
            hooks.gate.release.set()
            results = [await task_a, await task_c]
        else:
            results = list(
                await asyncio.gather(_call(lambda: req_a(False)), _call(lambda: req_c(False)))
            )
        done += 1
        if any(_bad(r) for r in results):
            failures.append(f"итерация {i} режим {mode} {a_action}/{c_action}: {results}")
            if len(failures) >= MAX_FAILURES:
                break
    assert not failures, (
        f"{len(failures)} из {done} итераций с 5xx/исключением (deadlock):\n" + "\n".join(failures)
    )
    assert done == ITERATIONS


# --- дедлок: смена своего пароля против действия администратора ---------------------------


async def test_fr62_change_own_password_vs_admin_action_has_no_deadlock(
    committed_api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-56, FR-62: Y делает ``POST /auth/password``, админ блокирует/сбрасывает/завершает Y.

    Чётные итерации: Y удерживается между ``get_actor`` и первой записью сервиса
    (``reserve_attempt``), админ стартует и выполняет действие; нечётные: админ удерживается
    в обработчике, Y выполняется целиком.
    """
    from app.domain.auth import service as auth_service

    env = committed_api_env
    hooks = _mount_routes(env)
    original = vars(auth_service)["reserve_attempt"]
    y_gate: list[Gate | None] = [None]

    async def gated_reserve(*args: Any, **kwargs: Any) -> Any:
        gate = y_gate[0]
        if gate is not None:
            await gate.hold()
        return await original(*args, **kwargs)

    monkeypatch.setattr(auth_service, "reserve_attempt", gated_reserve, raising=True)

    failures: list[str] = []
    done = 0
    for i in range(ITERATIONS):
        ws = await _new_workspace(env)
        admin, (tok_admin,) = await _seed_user(env, ws, "tech_admin")
        await _seed_user(env, ws, "tech_admin")  # второй админ: FR-69 не мешает
        y, (tok_y, _other) = await _seed_user(env, ws, "user", sessions=2, password=PW)
        action = C_ACTIONS[i % 3]
        new_password = f"New-Pa55phrase-{i:04d}-qzxw"

        def req_y(tok_y: str = tok_y, new_password: str = new_password) -> Any:
            return env.client.post(
                "/api/v1/auth/password",
                json={"current_password": PW, "new_password": new_password},
                headers=_cookie(env, tok_y),
            )

        def req_admin(
            hold: bool, tok_admin: str = tok_admin, y: UserRow = y, action: str = action
        ) -> Any:
            headers = _cookie(env, tok_admin, **({HOLD_HEADER: "1"} if hold else {}))
            return env.client.post(f"/_t/act/{y.id}/{action}", headers=headers)

        gate = Gate()
        results: list[tuple[str, int | str]]
        if i % 2 == 0:
            y_gate[0] = gate
            task_y = asyncio.ensure_future(_call(req_y))
            await _wait_event(gate.entered, task_y)
            task_admin = asyncio.ensure_future(_call(lambda: req_admin(False)))
            await _wait_blocked_or_done(env, task_admin)
            gate.release.set()
            results = [await task_y, await task_admin]
        else:
            y_gate[0] = None
            hooks.gate = gate
            task_admin = asyncio.ensure_future(_call(lambda: req_admin(True)))
            await _wait_event(gate.entered, task_admin)
            task_y = asyncio.ensure_future(_call(req_y))
            await _wait_blocked_or_done(env, task_y)
            gate.release.set()
            results = [await task_y, await task_admin]
        done += 1
        if any(_bad(r) for r in results):
            failures.append(f"итерация {i} {action}: {results}")
            if len(failures) >= MAX_FAILURES:
                break
    assert not failures, (
        f"{len(failures)} из {done} итераций с 5xx/исключением (deadlock):\n" + "\n".join(failures)
    )
    assert done == ITERATIONS


# --- активность переживает ошибку --------------------------------------------------------


@pytest.mark.parametrize("status", [403, 404, 409, 422])
async def test_fr59_4xx_after_get_actor_still_extends_session(
    committed_api_env: ApiEnv, status: int
) -> None:
    """FR-59, T12 (ревью): 4xx после ``get_actor`` продлевает сессию и это зафиксировано."""
    env = committed_api_env
    _mount_routes(env)
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    assert await _last_activity(env, token) == FIXED_NOW
    env.clock.advance(timedelta(hours=1))

    response = await env.client.post(f"/_t/fail/{status}", headers=_cookie(env, token))

    assert response.status_code == status
    assert await _last_activity(env, token) == FIXED_NOW + timedelta(hours=1)


async def test_fr59_5xx_after_get_actor_keeps_activity(committed_api_env: ApiEnv) -> None:
    """Решение: активность закреплена до выполнения обработчика, 5xx её не теряет."""
    env = committed_api_env
    _mount_routes(env)
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(hours=1))

    kind, value = await _call(lambda: env.client.post("/_t/fail/500", headers=_cookie(env, token)))

    assert (kind == "status" and value == 500) or (
        kind == "exc" and str(value).split(":")[0] == "RuntimeError"
    )
    assert await _last_activity(env, token) == FIXED_NOW + timedelta(hours=1)


# --- истёкшая сессия ----------------------------------------------------------------------


async def test_ac32_idle_expired_session_row_is_deleted_after_401(
    committed_api_env: ApiEnv,
) -> None:
    """AC-32, T11 (ревью): 401 по истёкшей сессии, строка удалена и после отката запроса."""
    env = committed_api_env
    _mount_routes(env)
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    assert len(await _session_rows(env, token)) == 1
    env.clock.advance(timedelta(hours=8))

    response = await env.me(token)

    assert response.status_code == 401
    assert await _session_rows(env, token) == []


async def test_ac33_absolute_expired_session_row_is_deleted_after_401(
    committed_api_env: ApiEnv,
) -> None:
    """AC-33: абсолютный срок 7 суток; простой в норме (активность 1 час назад)."""
    env = committed_api_env
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    table = get_table("user_session")
    last = FIXED_NOW + timedelta(days=7) - timedelta(hours=1)
    await env.execute(
        update(table).where(table.c.id == env.token_id(token)).values(last_activity_at=last)
    )
    env.clock.set(FIXED_NOW + timedelta(days=7))

    response = await env.me(token)

    assert response.status_code == 401
    assert await _session_rows(env, token) == []


# --- границы сроков не изменились --------------------------------------------------------


async def test_ac32_idle_boundary_7_59_59_alive_8_00_00_dead(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    user = await env.new_user(role="user")
    alive = await env.login_ok(user)
    dead = await env.login_ok(user)
    env.clock.set(FIXED_NOW + timedelta(hours=7, minutes=59, seconds=59))
    assert (await env.me(alive)).status_code == 200
    assert await _last_activity(env, alive) == FIXED_NOW + timedelta(
        hours=7, minutes=59, seconds=59
    )
    env.clock.set(FIXED_NOW + timedelta(hours=8))
    assert (await env.me(dead)).status_code == 401
    assert await _session_rows(env, dead) == []


async def test_ac33_absolute_boundary_7_days(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    user = await env.new_user(role="user")
    alive = await env.login_ok(user)
    dead = await env.login_ok(user)
    table = get_table("user_session")
    last = FIXED_NOW + timedelta(days=7) - timedelta(hours=1)
    await env.execute(update(table).values(last_activity_at=last))
    env.clock.set(FIXED_NOW + timedelta(days=7) - timedelta(seconds=1))
    assert (await env.me(alive)).status_code == 200
    env.clock.set(FIXED_NOW + timedelta(days=7))
    assert (await env.me(dead)).status_code == 401


async def test_ac79_background_get_does_not_extend_session(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(hours=1))

    response = await env.me(token, **{"X-GT-Background": "1"})

    assert response.status_code == 200
    assert await _last_activity(env, token) == FIXED_NOW


async def test_ac79_post_with_background_header_is_ordinary(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    _mount_routes(env)
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(hours=1))

    response = await env.client.post(
        "/_t/ping", headers=_cookie(env, token, **{"X-GT-Background": "1"})
    )

    assert response.status_code == 200
    assert await _last_activity(env, token) == FIXED_NOW + timedelta(hours=1)


# --- счётчик COMMIT / UPDATE --------------------------------------------------------------


@dataclass
class Counter:
    commits: int = 0
    session_updates: int = 0


async def _measure(env: ApiEnv, token: str, **extra: str) -> tuple[httpx.Response, Counter]:
    bind = env.sessionmaker.kw["bind"]
    engine = bind.sync_engine
    counter = Counter()

    def on_commit(conn: Any) -> None:
        counter.commits += 1

    def on_execute(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        if statement.lstrip().upper().startswith("UPDATE USER_SESSION"):
            counter.session_updates += 1

    event.listen(engine, "commit", on_commit)
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        response = await env.me(token, **extra)
    finally:
        event.remove(engine, "commit", on_commit)
        event.remove(engine, "before_cursor_execute", on_execute)
    return response, counter


async def test_fr59_ordinary_request_has_at_most_one_extra_commit(
    committed_api_env: ApiEnv,
) -> None:
    """Обычный запрос: ровно одно ``UPDATE user_session`` и не более 2 COMMIT (1 итоговый +
    не более одного дополнительного на ``get_actor``)."""
    env = committed_api_env
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(minutes=5))

    response, counter = await _measure(env, token)

    assert response.status_code == 200
    assert counter.session_updates == 1
    assert 1 <= counter.commits <= 2, counter


async def test_ac79_background_request_has_no_extra_commit_and_no_update(
    committed_api_env: ApiEnv,
) -> None:
    """Фон: ни ``UPDATE user_session``, ни дополнительного COMMIT (только итоговый)."""
    env = committed_api_env
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(minutes=5))

    response, counter = await _measure(env, token, **{"X-GT-Background": "1"})

    assert response.status_code == 200
    assert counter.session_updates == 0
    assert counter.commits == 1, counter


# --- одна транзакция на запрос для обработчика (D-3) -----------------------------------


async def test_d3_handler_work_rolls_back_entirely_though_activity_committed(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    _mount_routes(env)
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(hours=1))

    response = await env.client.post("/_t/write-then-fail", headers=_cookie(env, token))

    assert response.status_code == 422
    assert (await env.user_row(user.id)).failed_login_count == 0  # запись обработчика откатилась
    assert await _last_activity(env, token) == FIXED_NOW + timedelta(hours=1)


async def test_d3_handler_work_is_committed_once_on_success(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    _mount_routes(env)
    user = await env.new_user(role="user")
    token = await env.login_ok(user)
    env.clock.advance(timedelta(hours=1))

    response = await env.client.post("/_t/write-ok", headers=_cookie(env, token))

    assert response.status_code == 200
    assert (await env.user_row(user.id)).failed_login_count == 2
    assert await _last_activity(env, token) == FIXED_NOW + timedelta(hours=1)
