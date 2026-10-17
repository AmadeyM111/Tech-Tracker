"""R3-T13: миграция 0006 «три роли» (spec 002 AC-2, AC-20...AC-22, AC-29; FR-2, FR-13...FR-17).

Схема D-12: ``committed``-тест на head -> ``downgrade 0005`` -> данные предыдущей версии
(``tests/upgrade002_support``) -> ``alembic upgrade head`` подпроцессом -> проверка БД. Шаги
через HTTP (сессия S, вход, 403, смена пароля) - в R3-T14, здесь только роли, данные и журнал.

Время записей миграции берётся из БД (``now()`` транзакции, plan D-7, П-4): тест проверяет
попадание в окно ``[t0, t1]`` по ``clock_timestamp()`` БД и равенство времени у всех записей.
Часы приложения (``FixedClock``) на подпроцесс alembic не влияют.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.db_support import BACKEND_DIR
from tests.upgrade002_support import (
    FAILURE_MARK,
    PREFIX,
    alembic_ok,
    alembic_versions,
    audit_rows,
    data_fingerprint,
    db_now,
    install_failure,
    make_ac20_world,
    make_ac22_world,
    make_mixed,
    make_plain,
    member_updated_at,
    mixed_ids,
    remove_failure,
    roles_by_login,
    seed_journal,
    to_head,
    to_schema_0005,
    try_upgrade,
)

if TYPE_CHECKING:
    from datetime import datetime

    from tests.conftest import ApiEnv
    from tests.upgrade002_support import World

MIGRATION_0006 = BACKEND_DIR / "migrations" / "versions" / "0006_three_roles.py"
ROLE_CHECK = "ck_workspace_member_role_valid"
CHECK_VIOLATION = "23514"


def _login(name: str) -> str:
    return f"{PREFIX}{name}"


# --- общие проверки результата ------------------------------------------------------------


async def _check_def(env: ApiEnv) -> str:
    rows = await env.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n").bindparams(
            n=ROLE_CHECK
        )
    )
    assert rows is not None and len(rows) == 1, f"нет ровно одного CHECK {ROLE_CHECK}"
    return str(rows[0][0])


def _expected_roles(w: World, overrides: dict[str, str | None]) -> dict[str, str | None]:
    """Роли всех пользователей фикстуры: прежние, кроме ``overrides`` (короткие имена)."""
    expected: dict[str, str | None] = {}
    for name, user in w.users.items():
        expected[_login(name)] = overrides.get(name, user.role)
    return expected


async def _assert_journal_added(
    env: ApiEnv,
    w: World,
    before: list[Any],
    expected: list[tuple[str, str, str | None]],
    t0: datetime,
    t1: datetime,
) -> list[Any]:
    """Прежние записи побайтно те же; новые - ровно ``expected`` (имя, действие, role_to).

    Порядок новых записей - по логину (plan D-11): ``id`` возрастают в этом порядке. Автор -
    «система», ``entity_type = user``, ``in_audit``, ``details`` - ``role_from``/``role_to``.
    """
    after = await audit_rows(env)
    n = len(before)
    assert len(after) == n + len(expected), (
        f"журнал: было {n}, стало {len(after)}, ожидали +{len(expected)}"
    )
    assert [tuple(r) for r in after[:n]] == [tuple(r) for r in before], "прежние записи изменены"
    new = after[n:]
    assert [e.entity_id for e in new] == [w.uid(name) for name, _, _ in expected]
    ids = [e.id for e in new]
    assert ids == sorted(ids) and (not before or ids[0] > before[-1].id)
    for event, (name, action, role_to) in zip(new, expected, strict=True):
        assert event.action == action, name
        assert event.actor_id is None, f"{name}: автор должен быть «система»"
        assert event.entity_type == "user", name
        assert event.workspace_id == w.ws.id, name
        assert event.in_audit is True, name
        assert list(event.changed_fields) == [], name
        assert event.project_id is None and event.deal_id is None, name
        assert event.changes is None, name
        assert event.details == {"role_from": "mixed", "role_to": role_to}, name
    stamps = {e.occurred_at for e in new}
    assert len(stamps) == 1, f"у записей одной миграции должно быть одно время: {stamps}"
    (stamp,) = stamps
    assert stamp.tzinfo is not None
    assert t0 <= stamp <= t1, f"время записи {stamp} вне окна обновления [{t0}, {t1}]"
    # plan §4.5: updated_at бывшего СМ ставится тем же now() транзакции, что и время записи
    updated = await member_updated_at(env)
    for event in new:
        assert updated[(event.workspace_id, event.entity_id)] == stamp, (
            f"{event.entity_id}: updated_at не равен времени записи журнала"
        )
    return list(new)


async def _assert_data_preserved(env: ApiEnv, w: World, fingerprint: dict[str, list[str]]) -> None:
    """FR-14: владение, членство, исполнитель, авторство, блокировка, одноразовый пароль,
    сессии - как до обновления (побайтно по строкам таблиц); ``updated_at`` не-СМ не изменился
    (``updated_at`` бывших СМ проверяет ``_assert_journal_added``)."""
    assert await data_fingerprint(env, skip_updated=mixed_ids(w)) == fingerprint
    rows = await env.execute(
        text("SELECT name, owner_id FROM project WHERE workspace_id = :w").bindparams(w=w.ws.id)
    )
    assert rows is not None
    assert {r.name: r.owner_id for r in rows}["PM"] == w.uid("m1")


async def _assert_ac20_result(
    env: ApiEnv,
    w: World,
    before: list[Any],
    fingerprint: dict[str, list[str]],
    t0: datetime,
    t1: datetime,
) -> None:
    assert await alembic_versions(env) == ["0006"]
    roles = await roles_by_login(env)
    assert roles == _expected_roles(w, {"m1": None, "m2": None, "m3": None})
    await _assert_journal_added(
        env,
        w,
        before,
        [
            ("m1", "user.role_removed", None),
            ("m2", "user.role_removed", None),
            ("m3", "user.role_removed", None),
        ],
        t0,
        t1,
    )
    await _assert_data_preserved(env, w, fingerprint)


# --- AC-20 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac20_roles_data_and_journal_after_upgrade(committed_api_env: ApiEnv) -> None:
    """002/AC-20 (FR-13, FR-14, FR-15): роли m1, m2, m3 сняты, остальные не изменились; данные
    и сессия S на месте; в журнале N + 3 записи «снятие роли» от «системы»."""
    env = committed_api_env
    w, n = await make_ac20_world(env)
    before = await audit_rows(env)
    assert len(before) == n and n > 0
    assert await roles_by_login(env) == _expected_roles(w, {})  # m1..m3 - mixed
    fingerprint = await data_fingerprint(env, skip_updated=mixed_ids(w))
    assert len(fingerprint["user_session"]) == 1  # сессия S

    t0 = await db_now(env)
    await to_head(env)
    t1 = await db_now(env)

    await _assert_ac20_result(env, w, before, fingerprint, t0, t1)


@pytest.mark.committed
async def test_002_ac20_ownership_membership_assignee_author_block_otp_session(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-20, FR-14: владелец PM - m1; m1 - участник P и PM; исполнитель T2 - m1; автор
    комментария - m1; m2 заблокирован; у m3 признак одноразового пароля; строка сессии S цела."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    session_id = env.token_id(w.tokens["m1"])
    await to_head(env)
    m1, m2, m3 = w.uid("m1"), w.uid("m2"), w.uid("m3")

    owner = await env.execute(text("SELECT name, owner_id FROM project ORDER BY name"))
    assert owner is not None
    assert {r.name: r.owner_id for r in owner} == {"P": w.uid("ba.owner"), "PM": m1}
    members = await env.execute(text("SELECT project_id, user_id FROM project_member"))
    assert members is not None
    pairs = {(r.project_id, r.user_id) for r in members}
    assert (w.project_p, m1) in pairs and (w.project_pm, m1) in pairs
    assert (w.project_pm, w.uid("ba.pm")) in pairs
    task = await env.execute(
        text("SELECT assignee_id, created_by FROM task WHERE id = :t").bindparams(t=w.task_t2)
    )
    assert task is not None and (task[0].assignee_id, task[0].created_by) == (
        m1,
        w.uid("ba.owner"),
    )
    comment = await env.execute(
        text("SELECT created_by FROM comment WHERE id = :c").bindparams(c=w.comment_id)
    )
    assert comment is not None and comment[0].created_by == m1
    flags = await env.execute(text("SELECT id, is_blocked, must_change_password FROM app_user"))
    assert flags is not None
    by_id = {r.id: (r.is_blocked, r.must_change_password) for r in flags}
    assert by_id[m1] == (False, False)
    assert by_id[m2] == (True, False)
    assert by_id[m3] == (False, True)
    sessions = await env.execute(text("SELECT id, user_id FROM user_session"))
    assert sessions is not None
    assert [(bytes(r.id), r.user_id) for r in sessions] == [(session_id, m1)]
    assert await alembic_versions(env) == ["0006"]


@pytest.mark.committed
async def test_002_ac20_migration_record_equals_manual_role_removed_record(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-20, FR-15 («такая же, как при ручном действии», plan §4.5): запись миграции
    совпадает с записью ``set_role`` (снятие роли) по всем полям, кроме автора, времени и
    прежней роли."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    await to_head(env)
    assert await alembic_versions(env) == ["0006"]
    migrated = [r for r in await audit_rows(env) if r.entity_id == w.uid("m1")][-1]
    assert migrated.action == "user.role_removed"

    manual = await _manual_set_role(env, w, actor="ta1", target="ba.pm", role=None)
    _assert_same_shape(migrated, manual)
    assert manual.actor_id == w.uid("ta1") and migrated.actor_id is None
    assert manual.details == {"role_from": "business_admin", "role_to": None}


@pytest.mark.committed
async def test_002_ac20_journal_follows_login_order(committed_api_env: ApiEnv) -> None:
    """002/AC-20, plan D-11: записи журнала идут в порядке логинов (m1, m2, m3), даже если
    пользователи созданы в обратном порядке."""
    env = committed_api_env
    await to_schema_0005(env)
    from tests.factories import make_workspace

    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        await s.commit()
    created = {}
    for name in ("m3", "m1", "m2"):  # порядок создания не совпадает с порядком логинов
        created[name], _ = await make_mixed(env, ws, _login(name))
    n = len(await audit_rows(env))
    await to_head(env)
    rows = await audit_rows(env)
    assert len(rows) == n + 3
    assert [r.entity_id for r in rows[n:]] == [created[k].id for k in ("m1", "m2", "m3")]
    # формальная защита на будущее: временная таблица исчезает вместе с сессией alembic при любом
    # коде миграции, поэтому ``ON COMMIT DROP`` этой проверкой не доказывается
    leftovers = await env.execute(
        text("SELECT count(*) FROM pg_class WHERE relname = 'gt_0006_mixed'")
    )
    assert leftovers is not None and leftovers[0][0] == 0


def test_002_ac20_migration_literals_match_event_catalog() -> None:
    """002/AC-20, plan D-6: литералы миграции совпадают с ``EventAction``/каталогом событий;
    миграция не импортирует код приложения."""
    from app.domain.access.roles import Role
    from app.domain.events.catalog import EVENT_CATALOG, EventAction

    assert MIGRATION_0006.is_file(), "нет backend/migrations/versions/0006_three_roles.py"
    source = MIGRATION_0006.read_text(encoding="utf-8")
    for action in (EventAction.USER_ROLE_REMOVED, EventAction.USER_ROLE_CHANGED):
        spec = EVENT_CATALOG[action]
        assert f"'{action.value}'" in source, f"в миграции нет литерала {action.value!r}"
        assert spec.entity_type.value == "user"
        assert spec.audit is True
    assert "'mixed'" in source
    assert "'tech_admin'" in source
    assert {r.value for r in Role} == {"tech_admin", "business_admin", "user"}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app"), "миграция импортирует app.*"
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith("app") for a in node.names), "импорт app.*"


# --- AC-21 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac21_no_mixed_users_no_records_roles_unchanged(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-21 (FR-15, FR-17): в БД предыдущей версии нет ``mixed`` - в журнале не появилось
    записей, роли и прочие данные не изменились, версия схемы стала 0006."""
    from tests.factories import make_workspace

    env = committed_api_env
    await to_schema_0005(env)
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        await s.commit()
    users = {}
    for name, role in (
        ("ta1", "tech_admin"),
        ("ba1", "business_admin"),
        ("u1", "user"),
        ("nr", None),
    ):
        users[name], _ = await make_plain(env, ws, _login(name), role, session=name == "ba1")
    n = await seed_journal(env, ws, users, actor="ta1")
    before = await audit_rows(env)
    roles_before = await roles_by_login(env)
    assert len(before) == n and "mixed" not in roles_before.values()
    fingerprint = await data_fingerprint(env)
    assert await alembic_versions(env) == ["0005"]

    await to_head(env)

    assert await alembic_versions(env) == ["0006"]
    assert [tuple(r) for r in await audit_rows(env)] == [tuple(r) for r in before]
    assert await roles_by_login(env) == roles_before
    assert await data_fingerprint(env) == fingerprint
    assert "mixed" not in await _check_def(env)


@pytest.mark.committed
async def test_002_ac21_restart_after_upgrade_changes_nothing(committed_api_env: ApiEnv) -> None:
    """002/AC-21, FR-17: после успешного обновления по AC-20 повторные ``alembic upgrade head``
    и ``run_bootstrap`` (перезапуск) оставляют в журнале N + 3 записи, роли и данные прежними."""
    from app.domain.system.bootstrap import run_bootstrap

    env = committed_api_env
    w, n = await make_ac20_world(env)
    before = await audit_rows(env)
    fingerprint = await data_fingerprint(env, skip_updated=mixed_ids(w))
    t0 = await db_now(env)
    await to_head(env)
    t1 = await db_now(env)
    await _assert_ac20_result(env, w, before, fingerprint, t0, t1)
    journal = await audit_rows(env)
    roles = await roles_by_login(env)
    assert len(journal) == n + 3

    result = await alembic_ok(env, "upgrade", "head")
    assert result.returncode == 0
    env.settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    await run_bootstrap(
        env.sessionmaker, env.settings, clock=env.clock, generate=lambda: "Zq7Lm2Vx9BootstrapPw"
    )

    assert await alembic_versions(env) == ["0006"]
    assert [tuple(r) for r in await audit_rows(env)] == [tuple(r) for r in journal]
    assert await roles_by_login(env) == roles
    assert await data_fingerprint(env, skip_updated=mixed_ids(w)) == fingerprint


# --- AC-22 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac22_no_active_tech_admin_active_former_mixed_become_tech_admins(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-22, FR-16 (ветка «нет активного ТА»): единственный ТА заблокирован - m1 и m3
    (активные, у m3 одноразовый пароль не сменён) получают ``tech_admin``, заблокированный m2 -
    без роли; в журнале N + 3: «смена роли» mixed -> tech_admin для m1, m3, «снятие роли» для m2."""
    env = committed_api_env
    w, n = await make_ac22_world(env, with_active_ta=False)
    before = await audit_rows(env)
    assert len(before) == n
    fingerprint = await data_fingerprint(env, skip_updated=mixed_ids(w))

    t0 = await db_now(env)
    await to_head(env)
    t1 = await db_now(env)

    assert await alembic_versions(env) == ["0006"]
    assert await roles_by_login(env) == _expected_roles(
        w, {"m1": "tech_admin", "m2": None, "m3": "tech_admin"}
    )
    await _assert_journal_added(
        env,
        w,
        before,
        [
            ("m1", "user.role_changed", "tech_admin"),
            ("m2", "user.role_removed", None),
            ("m3", "user.role_changed", "tech_admin"),
        ],
        t0,
        t1,
    )
    # ta.b остаётся заблокированным ТА; владение PM и членство не изменились (FR-14)
    assert await data_fingerprint(env, skip_updated=mixed_ids(w)) == fingerprint
    owner = await env.execute(
        text("SELECT owner_id FROM project WHERE id = :p").bindparams(p=w.project_pm)
    )
    assert owner is not None and owner[0][0] == w.uid("m1")
    # в пространстве снова есть активный ТА (FR-16)
    active = await env.execute(
        text(
            "SELECT count(*) FROM workspace_member m JOIN app_user u ON u.id = m.user_id "
            "WHERE m.role = 'tech_admin' AND NOT u.is_blocked"
        )
    )
    assert active is not None and active[0][0] == 2


@pytest.mark.committed
async def test_002_ac22_active_tech_admin_with_unchanged_otp_means_roles_are_just_removed(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-22, FR-16 (ветка «активный ТА есть»): ``ta.new`` с несменённым одноразовым
    паролем - активный ТА, FR-16 не применяется: у m1, m2, m3 нет роли, в журнале N + 3 записи
    «снятие роли»; роли ``ta.b``, ``ta.new``, ``ba.pm`` не изменились."""
    env = committed_api_env
    w, _ = await make_ac22_world(env, with_active_ta=True)
    before = await audit_rows(env)
    fingerprint = await data_fingerprint(env, skip_updated=mixed_ids(w))

    t0 = await db_now(env)
    await to_head(env)
    t1 = await db_now(env)

    assert await alembic_versions(env) == ["0006"]
    assert await roles_by_login(env) == _expected_roles(w, {"m1": None, "m2": None, "m3": None})
    await _assert_journal_added(
        env,
        w,
        before,
        [
            ("m1", "user.role_removed", None),
            ("m2", "user.role_removed", None),
            ("m3", "user.role_removed", None),
        ],
        t0,
        t1,
    )
    assert await data_fingerprint(env, skip_updated=mixed_ids(w)) == fingerprint


@pytest.mark.committed
async def test_002_ac22_only_blocked_former_mixed_just_lose_the_role(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-22, FR-16 («заблокированные и в этом случае без роли»): ТА нет, все бывшие СМ
    заблокированы - назначать ТА некого, роли снимаются, система остаётся без активного ТА
    (spec §8)."""
    from tests.factories import make_workspace

    env = committed_api_env
    await to_schema_0005(env)
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        await s.commit()
    users = {}
    users["ba1"], _ = await make_plain(env, ws, _login("ba1"), "business_admin")
    users["m1"], _ = await make_mixed(env, ws, _login("m1"), blocked=True)
    users["m2"], _ = await make_mixed(env, ws, _login("m2"), blocked=True)
    await seed_journal(env, ws, users, actor=None)
    before = await audit_rows(env)

    await to_head(env)

    roles = await roles_by_login(env)
    assert roles == {_login("ba1"): "business_admin", _login("m1"): None, _login("m2"): None}
    after = await audit_rows(env)
    assert len(after) == len(before) + 2
    assert {(r.action, r.details["role_to"] is None) for r in after[len(before) :]} == {
        ("user.role_removed", True)
    }
    updated = await member_updated_at(env)
    for event in after[len(before) :]:
        assert updated[(event.workspace_id, event.entity_id)] == event.occurred_at


@pytest.mark.committed
async def test_002_ac22_fr16_is_evaluated_per_workspace(committed_api_env: ApiEnv) -> None:
    """002/AC-22, FR-16, plan §4.5 («Пространства»): в первом пространстве есть активный ТА -
    бывший СМ теряет роль; во втором ТА нет - активный бывший СМ получает ``tech_admin``;
    пользователь с ``business_admin`` в ws1 и ``mixed`` в ws2 сохраняет роль в ws1."""
    from tests.factories import make_workspace

    env = committed_api_env
    await to_schema_0005(env)
    async with env.sessionmaker() as s:
        ws1 = await make_workspace(s)
        ws2 = await make_workspace(s)
        await s.commit()
    ta, _ = await make_plain(env, ws1, _login("ws1.ta"), "tech_admin")
    x1, _ = await make_mixed(env, ws1, _login("ws1.x1"))
    y1, _ = await make_mixed(env, ws2, _login("ws2.y1"))
    y2, _ = await make_mixed(env, ws2, _login("ws2.y2"), blocked=True)
    # один глобальный пользователь (D-5): business_admin в ws1 и mixed в ws2
    shared, _ = await make_plain(env, ws1, _login("shared"), "business_admin")
    async with env.sessionmaker() as s:
        await s.execute(
            text(
                "INSERT INTO workspace_member (workspace_id, user_id, role, created_at, "
                "updated_at, created_by) SELECT :w2, user_id, 'mixed', created_at, updated_at, "
                "created_by FROM workspace_member WHERE workspace_id = :w1 AND user_id = :u"
            ),
            {"w1": ws1.id, "w2": ws2.id, "u": shared.id},
        )
        await s.commit()
    before = await audit_rows(env)

    await to_head(env)

    roles = await roles_by_login(env)
    assert roles[ta.login] == "tech_admin"
    assert roles[x1.login] is None
    assert roles[y1.login] == "tech_admin"
    assert roles[y2.login] is None
    member_roles = await env.execute(
        text("SELECT workspace_id, role FROM workspace_member WHERE user_id = :u").bindparams(
            u=shared.id
        )
    )
    assert member_roles is not None
    assert {r[0]: r[1] for r in member_roles} == {ws1.id: "business_admin", ws2.id: "tech_admin"}
    new = {r.entity_id: r for r in (await audit_rows(env))[len(before) :]}
    assert set(new) == {x1.id, y1.id, y2.id, shared.id}
    assert (new[shared.id].action, new[shared.id].workspace_id) == ("user.role_changed", ws2.id)
    updated = await member_updated_at(env)
    assert updated[(ws2.id, shared.id)] == new[shared.id].occurred_at
    assert updated[(ws1.id, shared.id)] < new[shared.id].occurred_at  # ws1 не тронуто
    assert (new[x1.id].action, new[x1.id].workspace_id) == ("user.role_removed", ws1.id)
    assert (new[y1.id].action, new[y1.id].workspace_id) == ("user.role_changed", ws2.id)
    assert new[y1.id].details == {"role_from": "mixed", "role_to": "tech_admin"}
    assert (new[y2.id].action, new[y2.id].workspace_id) == ("user.role_removed", ws2.id)


@pytest.mark.committed
async def test_002_ac22_migration_record_equals_manual_role_changed_record(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-22, FR-15: запись «смена роли» mixed -> tech_admin совпадает с записью
    ``set_role`` (смена роли на ``tech_admin``) по всем полям, кроме автора, времени и прежней
    роли."""
    env = committed_api_env
    w, _ = await make_ac22_world(env, with_active_ta=False)
    await to_head(env)
    assert await alembic_versions(env) == ["0006"]
    migrated = [r for r in await audit_rows(env) if r.entity_id == w.uid("m1")][-1]
    assert migrated.action == "user.role_changed"

    # m1 - уже активный ТА: он и меняет роль ba.pm (business_admin -> tech_admin)
    manual = await _manual_set_role(env, w, actor="m1", target="ba.pm", role="tech_admin")
    _assert_same_shape(migrated, manual)
    assert manual.details["role_to"] == migrated.details["role_to"] == "tech_admin"
    assert migrated.actor_id is None and manual.actor_id == w.uid("m1")


# --- AC-29 --------------------------------------------------------------------------------


@pytest.mark.committed
@pytest.mark.parametrize("on", ["version", "event"])
async def test_002_ac29_failure_in_the_middle_rolls_everything_back_and_retry_works(
    committed_api_env: ApiEnv, on: str
) -> None:
    """002/AC-29 (FR-17): сбой после снятия ролей и записи журнала (``on="version"``: триггер на
    ``alembic_version``; ``on="event"``: триггер на запись журнала для m2) - alembic завершается
    ошибкой, версия 0005, роли mixed, журнал из N записей, БД принимает ``mixed``; после
    устранения сбоя повтор даёт результат AC-20."""
    env = committed_api_env
    w, n = await make_ac20_world(env)
    before = await audit_rows(env)
    assert len(before) == n
    fingerprint = await data_fingerprint(env, skip_updated=mixed_ids(w))
    full_fingerprint = await data_fingerprint(env)
    updated_before = await member_updated_at(env)
    roles_before = await roles_by_login(env)
    check_before = await _check_def(env)
    assert "mixed" in check_before

    if on == "version":
        await install_failure(env, on="version")
    else:
        await install_failure(env, on="event", entity_id=w.uid("m2"))
    failed = await try_upgrade(env)

    assert failed.returncode != 0, "обновление с внедрённым сбоем должно завершиться ошибкой"
    assert FAILURE_MARK in failed.stdout + failed.stderr, (
        f"сбой не от внедрённого триггера:\n{failed.stderr[-1500:]}"
    )
    assert await alembic_versions(env) == ["0005"]
    assert await roles_by_login(env) == roles_before
    assert {r for r in roles_before.values() if r == "mixed"} == {"mixed"}
    assert [tuple(r) for r in await audit_rows(env)] == [tuple(r) for r in before]
    assert await data_fingerprint(env) == full_fingerprint  # откат: и updated_at бывших СМ
    assert await member_updated_at(env) == updated_before
    assert await _check_def(env) == check_before
    # хранилище по-прежнему принимает mixed (транзакция откатывается)
    async with env.sessionmaker() as s:
        trans = await s.begin()
        try:
            res = await s.execute(
                text(
                    "UPDATE workspace_member SET role = 'mixed' WHERE user_id = :u RETURNING role"
                ).bindparams(u=w.uid("ba.pm"))
            )
            assert res.scalar_one() == "mixed"
        finally:
            await trans.rollback()

    await remove_failure(env)
    t0 = await db_now(env)
    await to_head(env)
    t1 = await db_now(env)

    await _assert_ac20_result(env, w, before, fingerprint, t0, t1)


# --- AC-2 после обновления ------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac2_upgraded_database_rejects_mixed_and_accepts_three_roles_and_null(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-2 (FR-2): после обновления БД с данными ``mixed`` в обход API отклоняет ``mixed``
    и ``admin`` (23514), принимает три значения и «без роли»; CHECK без ``mixed``."""
    from sqlalchemy.exc import DBAPIError

    env = committed_api_env
    w, _ = await make_ac20_world(env)
    await to_head(env)
    assert await alembic_versions(env) == ["0006"]
    definition = await _check_def(env)
    assert "mixed" not in definition
    assert set(re.findall(r"'([a-z_]+)'", definition)) == {"tech_admin", "business_admin", "user"}

    for bad in ("mixed", "admin"):
        with pytest.raises(DBAPIError) as info:
            async with env.sessionmaker() as s, s.begin():
                await s.execute(
                    text("UPDATE workspace_member SET role = :r WHERE user_id = :u").bindparams(
                        r=bad, u=w.uid("ba.pm")
                    )
                )
        orig: Any = info.value.orig
        code = getattr(orig, "sqlstate", None) or getattr(
            getattr(orig, "__cause__", None), "sqlstate", None
        )
        assert code == CHECK_VIOLATION, (bad, repr(info.value))
    for good in ("tech_admin", "business_admin", "user", None):
        async with env.sessionmaker() as s, s.begin():
            await s.execute(
                text("UPDATE workspace_member SET role = :r WHERE user_id = :u").bindparams(
                    r=good, u=w.uid("u1")
                )
            )
    assert (await roles_by_login(env))[_login("u1")] is None


# --- вспомогательное: запись «вручную» ---------------------------------------------------


async def _manual_set_role(
    env: ApiEnv, w: World, *, actor: str, target: str, role: str | None
) -> Any:
    """``set_role`` от имени ``actor`` (активный ТА после обновления); возвращает строку журнала."""
    from app.domain.access.roles import Actor, Role
    from app.domain.users.service import set_role

    user = w.users[actor]
    actor_obj = Actor(
        user_id=user.id,
        workspace_id=w.ws.id,
        login=user.login,
        role=Role.TECH_ADMIN,
        must_change_password=False,
        session_id=b"\x02" * 32,
    )
    before = {r.id for r in await audit_rows(env)}
    async with env.sessionmaker() as s, s.begin():
        await set_role(s, actor_obj, w.uid(target), None if role is None else Role(role))
    created = [r for r in await audit_rows(env) if r.id not in before]
    assert len(created) == 1, f"set_role должен писать ровно одну запись, записано {len(created)}"
    return created[0]


def _assert_same_shape(migrated: Any, manual: Any) -> None:
    """Запись миграции равна записи ``set_role`` по полям plan §4.5 (кроме актора, времени)."""
    for column in (
        "workspace_id",
        "entity_type",
        "action",
        "changed_fields",
        "project_id",
        "deal_id",
        "in_audit",
        "changes",
    ):
        assert getattr(migrated, column) == getattr(manual, column), column
    assert set(migrated.details) == set(manual.details) == {"role_from", "role_to"}
    assert migrated.details["role_to"] == manual.details["role_to"]
    assert manual.details["role_from"] != "mixed"
    assert migrated.details["role_from"] == "mixed"
    assert migrated.occurred_at.tzinfo is not None and manual.occurred_at.tzinfo is not None
