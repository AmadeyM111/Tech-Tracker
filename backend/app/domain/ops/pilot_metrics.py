"""Метрики пилота к контрольной точке: только чтение, без новой схемы (spec 031).

``collect`` выполняет SELECT-запросы за период ``[since, until)`` в транзакции ``READ ONLY`` и
возвращает числа; ``render_markdown`` печатает отчёт. Персональных данных нет: только счётчики,
медианы и имена клиентов агентов (``client_name``); логины, названия задач и тексты не читаются.
Определения метрик — ``docs/pilot/README.md``.
"""

# ruff: noqa: E501
# Длинные строки — SQL и подписи отчёта: их удобнее читать целиком.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from app.core.clock import MOSCOW_TZ

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ACTIVE_DAYS: Final = 7
TOP_CLIENTS: Final = 5

# Каждый запрос — одна строка с именованными столбцами; параметры :since, :until, :active_since.
QUERIES: Final[dict[str, str]] = {
    "users": """
        SELECT
          count(*) FILTER (WHERE wm.role IS NOT NULL AND NOT u.is_blocked) AS total,
          count(*) FILTER (WHERE wm.role IS NULL AND NOT u.is_blocked) AS without_role,
          count(*) FILTER (WHERE u.is_blocked) AS blocked,
          count(*) FILTER (WHERE u.self_registered) AS self_registered,
          count(*) FILTER (WHERE u.created_at >= :since AND u.created_at < :until) AS registered_in_period
        FROM app_user u JOIN workspace_member wm ON wm.user_id = u.id
    """,
    # Активный = есть действие в журнале, вход по сессии или использование токена за окно.
    "active": """
        SELECT count(DISTINCT user_id) AS active FROM (
          SELECT actor_id AS user_id FROM domain_event
            WHERE actor_id IS NOT NULL AND occurred_at >= :active_since AND occurred_at < :until
          UNION
          SELECT user_id FROM user_session
            WHERE last_activity_at >= :active_since AND last_activity_at < :until
          UNION
          SELECT user_id FROM api_token
            WHERE last_used_at >= :active_since AND last_used_at < :until
          UNION
          SELECT user_id FROM oauth_grant
            WHERE last_used_at >= :active_since AND last_used_at < :until
        ) a
    """,
    "projects": """
        SELECT
          count(*) FILTER (WHERE deleted_at IS NULL) AS live,
          count(*) FILTER (WHERE created_at >= :since AND created_at < :until) AS created
        FROM project
    """,
    "tasks": """
        SELECT
          count(*) FILTER (WHERE created_at >= :since AND created_at < :until) AS created,
          count(*) FILTER (WHERE deleted_at IS NULL AND status <> 'done') AS open_now,
          count(*) FILTER (WHERE deleted_at IS NULL AND status = 'done') AS done_now,
          count(*) FILTER (WHERE deleted_at IS NULL AND status <> 'done'
                           AND due_date < (:until AT TIME ZONE 'Europe/Moscow')::date) AS overdue_now
        FROM task
    """,
    # «Закрыто» = переход в done по журналу (task.updated с изменением status -> done).
    "closed": """
        SELECT count(DISTINCT entity_id) AS closed FROM domain_event
        WHERE action = 'task.updated' AND occurred_at >= :since AND occurred_at < :until
          AND jsonb_path_exists(changes, '$[*] ? (@.field == "status" && @.new == "done")')
    """,
    # Реакция = первый комментарий или первое изменение задачи от другого пользователя.
    "reaction": """
        WITH new_tasks AS (
          SELECT id, created_at, created_by FROM task
          WHERE created_at >= :since AND created_at < :until AND parent_id IS NULL
        ), first_reaction AS (
          SELECT t.id, t.created_at, min(r.at) AS at FROM new_tasks t
          LEFT JOIN LATERAL (
            SELECT c.created_at AS at FROM comment c
              WHERE c.task_id = t.id AND c.deleted_at IS NULL AND c.created_by IS DISTINCT FROM t.created_by
            UNION ALL
            SELECT e.occurred_at FROM domain_event e
              WHERE e.entity_id = t.id AND e.action = 'task.updated'
                AND e.actor_id IS DISTINCT FROM t.created_by
          ) r ON true
          GROUP BY t.id, t.created_at
        )
        SELECT
          count(*) AS tasks,
          count(at) AS reacted,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (at - created_at)) / 3600.0)
            AS median_hours,
          percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM (at - created_at)) / 3600.0)
            AS p90_hours
        FROM first_reaction
    """,
    "comments": """
        SELECT count(*) AS created FROM comment
        WHERE created_at >= :since AND created_at < :until AND deleted_at IS NULL
    """,
    "tokens": """
        SELECT
          count(*) FILTER (WHERE created_at >= :since AND created_at < :until) AS created,
          count(*) FILTER (WHERE revoked_at IS NULL AND expires_at > :until) AS active_now,
          count(DISTINCT user_id) FILTER (WHERE revoked_at IS NULL AND expires_at > :until) AS users_with_token,
          count(DISTINCT user_id) FILTER (WHERE last_used_at >= :since AND last_used_at < :until) AS users_used
        FROM api_token
    """,
    "oauth": """
        SELECT
          count(*) FILTER (WHERE created_at >= :since AND created_at < :until) AS granted,
          count(*) FILTER (WHERE revoked_at IS NULL) AS active_now,
          count(DISTINCT user_id) FILTER (WHERE last_used_at >= :since AND last_used_at < :until) AS users_used
        FROM oauth_grant
    """,
    "agent_actions": """
        SELECT count(*) AS actions, count(DISTINCT actor_id) AS users FROM domain_event
        WHERE client_name IS NOT NULL AND occurred_at >= :since AND occurred_at < :until
    """,
    "agent_clients": """
        SELECT client_name AS name, count(*) AS actions FROM domain_event
        WHERE client_name IS NOT NULL AND occurred_at >= :since AND occurred_at < :until
        GROUP BY client_name ORDER BY count(*) DESC, client_name LIMIT :top
    """,
    "attachments": """
        SELECT
          count(*) AS uploaded,
          count(DISTINCT task_id) AS tasks,
          coalesce(sum(size_bytes), 0) AS bytes
        FROM attachment
        WHERE created_at >= :since AND created_at < :until AND deleted_at IS NULL
    """,
    "mentions": """
        SELECT count(*) AS mentions, count(DISTINCT user_id) AS users FROM comment_mention
        WHERE created_at >= :since AND created_at < :until
    """,
    "notifications": """
        SELECT
          count(*) AS created,
          count(*) FILTER (WHERE read_at IS NOT NULL) AS read
        FROM notification
        WHERE created_at >= :since AND created_at < :until
    """,
}


@dataclass(frozen=True)
class PilotMetrics:
    since: datetime
    until: datetime
    active_since: datetime
    data: dict[str, dict[str, Any]] = field(default_factory=dict)
    clients: list[tuple[str, int]] = field(default_factory=list)


async def collect(
    db: AsyncSession, *, since: datetime, until: datetime, active_days: int = ACTIVE_DAYS
) -> PilotMetrics:
    """Все метрики одним проходом; транзакция переводится в ``READ ONLY`` (запись невозможна)."""
    from datetime import timedelta

    await db.execute(text("SET TRANSACTION READ ONLY"))
    active_since = until - timedelta(days=active_days)
    params = {"since": since, "until": until, "active_since": active_since, "top": TOP_CLIENTS}
    data: dict[str, dict[str, Any]] = {}
    for name, sql in QUERIES.items():
        if name == "agent_clients":
            continue
        row = (await db.execute(text(sql), params)).mappings().one()
        data[name] = dict(row)
    clients = [
        (str(r["name"]), int(r["actions"]))
        for r in (await db.execute(text(QUERIES["agent_clients"]), params)).mappings()
    ]
    return PilotMetrics(
        since=since, until=until, active_since=active_since, data=data, clients=clients
    )


def _n(value: Any) -> int:
    return 0 if value is None else int(value)


def _hours(value: Any) -> str:
    if value is None:
        return "нет данных"
    hours = float(value)
    return f"{hours * 60:.0f} мин" if hours < 1 else f"{hours:.1f} ч"


def _pair(a: Any, b: Any) -> str:
    return f"{_n(a)} / {_n(b)}"


def _share(part: int, total: int) -> str:
    return "—" if total == 0 else f"{part / total * 100:.0f} %"


def _msk(moment: datetime) -> str:
    return moment.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")


def _table(rows: list[tuple[str, str]]) -> list[str]:
    return [
        "| Метрика | Значение |",
        "|---|---|",
        *[f"| {label} | {value} |" for label, value in rows],
    ]


def render_markdown(
    m: PilotMetrics, *, generated_at: datetime, active_days: int = ACTIVE_DAYS
) -> str:
    """Отчёт в Markdown: числа из ``collect`` и пустые строки для ручных выводов."""
    d = m.data
    u, tk, rc, tok = d["users"], d["tasks"], d["reaction"], d["tokens"]
    oa, ag, att, men, nt = (
        d["oauth"],
        d["agent_actions"],
        d["attachments"],
        d["mentions"],
        d["notifications"],
    )
    active = _n(d["active"]["active"])
    lines = [
        "# Метрики пилота GTrack",
        "",
        f"- **Период:** {_msk(m.since)} — {_msk(m.until)} (МСК); «активные» — за {active_days} сут. "
        "до конца периода",
        f"- **Снято:** {_msk(generated_at)} (МСК); только чтение, персональных данных нет",
        "",
        "## Пользователи",
        *_table(
            [
                ("Пользователей с ролью (не заблокированных)", str(_n(u["total"]))),
                (
                    f"Активных за {active_days} дней",
                    f"{active} ({_share(active, _n(u['total']))})",
                ),
                ("Зарегистрировано за период", str(_n(u["registered_in_period"]))),
                ("Всего самостоятельных регистраций", str(_n(u["self_registered"]))),
                ("Без роли / заблокировано", _pair(u["without_role"], u["blocked"])),
            ]
        ),
        "",
        "## Работа с задачами",
        *_table(
            [
                (
                    "Проектов живых / создано за период",
                    _pair(d["projects"]["live"], d["projects"]["created"]),
                ),
                ("Задач создано за период", str(_n(tk["created"]))),
                ("Задач закрыто за период (переход в «Готово»)", str(_n(d["closed"]["closed"]))),
                ("Сейчас открыто / выполнено", _pair(tk["open_now"], tk["done_now"])),
                ("Просрочено сейчас", str(_n(tk["overdue_now"]))),
                ("Комментариев за период", str(_n(d["comments"]["created"]))),
            ]
        ),
        "",
        "## Время до первой реакции на новую задачу",
        "Реакция — первый комментарий или изменение задачи от другого пользователя (не автора).",
        "",
        *_table(
            [
                ("Новых задач (верхнего уровня)", str(_n(rc["tasks"]))),
                (
                    "С реакцией",
                    f"{_n(rc['reacted'])} ({_share(_n(rc['reacted']), _n(rc['tasks']))})",
                ),
                ("Медиана", _hours(rc["median_hours"])),
                ("90-й процентиль", _hours(rc["p90_hours"])),
            ]
        ),
        "",
        "## ИИ-агенты (MCP)",
        *_table(
            [
                (
                    "Токенов `gtrk_` выпущено за период / активных сейчас",
                    _pair(tok["created"], tok["active_now"]),
                ),
                (
                    "Пользователей с активным токеном / применявших токен за период",
                    _pair(tok["users_with_token"], tok["users_used"]),
                ),
                (
                    "Облачных клиентов (OAuth) подключено за период / активных сейчас",
                    _pair(oa["granted"], oa["active_now"]),
                ),
                ("Пользователей, чей облачный клиент работал за период", str(_n(oa["users_used"]))),
                (
                    "Действий агентов в журнале за период / пользователей",
                    _pair(ag["actions"], ag["users"]),
                ),
            ]
        ),
    ]
    if m.clients:
        lines += ["", "Действия по клиентам:", "", "| Клиент | Действий |", "|---|---|"]
        lines += [f"| {name} | {count} |" for name, count in m.clients]
    lines += [
        "",
        "## Вложения, упоминания, уведомления",
        *_table(
            [
                (
                    "Вложений загружено за период / задач с вложениями",
                    _pair(att["uploaded"], att["tasks"]),
                ),
                ("Объём загруженных вложений", f"{_n(att['bytes']) / (1024 * 1024):.1f} МБ"),
                (
                    "Упоминаний `@логин` за период / упомянутых пользователей",
                    _pair(men["mentions"], men["users"]),
                ),
                (
                    "Уведомлений создано / прочитано",
                    f"{_pair(nt['created'], nt['read'])} ({_share(_n(nt['read']), _n(nt['created']))})",
                ),
            ]
        ),
        "",
        "## Выводы (заполняет человек)",
        "- Что работает:",
        "- Что мешает:",
        "- Решения к контрольной точке:",
        "",
    ]
    return "\n".join(lines)
