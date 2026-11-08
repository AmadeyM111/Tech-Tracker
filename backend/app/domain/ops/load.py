"""Нагрузочный набор для замера нормативов (spec 016 FR-1, NFR-2, AC-1, AC-2; plan §2).

``load_synthetic_data`` одной транзакцией создаёт 12 пользователей, 8 проектов, ``tasks`` задач
(из них около одной десятой — подзадачи) и комментарии. Всё случайное берётся из
``random.Random(seed)``: id — UUID из того же потока, соль Argon2 и пароль — из seed и логина,
метки времени — от константы ``ANCHOR``. Поэтому одинаковый seed даёт одинаковые строки, и
``gtrack export`` двух запусков совпадает (AC-1). Сеть не используется (NFR-2).

Пароли выводятся из seed и известны всем, кто знает seed: CLI отказывает при ``ENV=production``.
Уведомления не создаются (таблицы нет, 012/T-05); аудит-события не пишутся (D-55).
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from argon2.low_level import Type, hash_secret
from sqlalchemy import func, insert, select, text

from app.core.clock import today_msk
from app.core.config import Settings
from app.domain.comments.models import Comment
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.positions import STEP
from app.domain.users.models import AppUser
from app.domain.workspaces.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ANCHOR: Final = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
"""Момент отсчёта для меток времени и «сегодня» (Europe/Moscow): набор не зависит от часов."""

LOAD_TEST_LOGIN: Final = "load.user1"
"""Пользователь, от имени которого замеряется «Сводка»: участник всех проектов (худший случай)."""

MIN_TASKS: Final = 100
PROJECT_COUNT: Final = 8
SUBTASK_EVERY: Final = 10  # одна подзадача на каждые 10 задач
_BATCH: Final = 5000
# bigint-константа блокировки (ASCII «GOST» + номер): параллельные запуски не вставят дубли
_LOCK_KEY: Final = 0x474F535400000003

_USERS: Final[tuple[tuple[str, str], ...]] = (
    ("load.ta", "tech_admin"),
    ("load.ba1", "business_admin"),
    ("load.ba2", "business_admin"),
    *((f"load.user{i}", "user") for i in range(1, 10)),
)
_OWNERS: Final = ("load.ba1", "load.ba2")
_PROJECT_NAMES: Final = (
    "Внедрение трекера",
    "Подготовка пилота",
    "Миграция данных",
    "Обучение сотрудников",
    "Аудит процессов",
    "Продуктовый backlog",
    "Отчётность квартала",
    "Поддержка клиентов",
)
_STATUS_WEIGHTS: Final = (
    (TaskStatus.TODO.value, 30),
    (TaskStatus.IN_PROGRESS.value, 30),
    (TaskStatus.REVIEW.value, 15),
    (TaskStatus.DONE.value, 25),
)
_PRIORITY_WEIGHTS: Final = (
    (TaskPriority.LOW.value, 30),
    (TaskPriority.MEDIUM.value, 50),
    (TaskPriority.HIGH.value, 20),
)
# срок: без срока / просрочено / сегодня / завтра / на неделе / позже
_DUE_WEIGHTS: Final = (
    ("none", 12),
    ("overdue", 15),
    ("today", 8),
    ("tomorrow", 5),
    ("week", 20),
    ("later", 40),
)
_VERBS: Final = (
    "Подготовить",
    "Согласовать",
    "Проверить",
    "Обновить",
    "Описать",
    "Настроить",
    "Собрать",
)
_OBJECTS: Final = ("отчёт", "требования", "план", "инструкцию", "справочник", "доступы", "макет")
_COMMENT_BODIES: Final = (
    "Взял в работу.",
    "Нужно уточнить детали.",
    "Готово, прошу проверить.",
    "Есть замечания, см. описание.",
    "Перенёс срок, согласовано.",
    "Блокирует следующую задачу.",
    "Проверил, всё в порядке.",
)
_COMMENT_COUNT_WEIGHTS: Final = ((0, 30), (1, 40), (2, 20), (3, 10))
_UNASSIGNED_SHARE: Final = 0.1


class LoadDataRefused(Exception):
    """Отказ (код 2): в базе уже есть проекты, задачи или пользователи сверх первого ТА."""


class LoadWorkspaceMissing(Exception):
    """Пространства нет: ``gtrack bootstrap`` не выполнялся (код 1, ошибка установки)."""


@dataclass(frozen=True)
class LoadReport:
    users: int
    projects: int
    tasks: int  # включая подзадачи
    subtasks: int
    comments: int


@dataclass
class _Plan:
    users: list[dict[str, Any]] = field(default_factory=list)
    workspace_members: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    project_members: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)  # верхний уровень
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)

    def report(self) -> LoadReport:
        return LoadReport(
            users=len(self.users),
            projects=len(self.projects),
            tasks=len(self.tasks) + len(self.subtasks),
            subtasks=len(self.subtasks),
            comments=len(self.comments),
        )


def derive_password(seed: int, login: str) -> str:
    """Синтетический пароль: 20 символов из букв и цифр, производный от seed и логина."""
    digest = hashlib.sha256(f"gtrack-load|{seed}|{login}".encode()).hexdigest()
    return f"Ld{digest[:18]}"


def _password_hash(settings: Settings, seed: int, login: str) -> str:
    """Хеш Argon2id с солью из seed и логина: одинаковый вход — одинаковая строка хеша."""
    salt = hashlib.sha256(f"gtrack-load-salt|{seed}|{login}".encode()).digest()[:16]
    encoded = hash_secret(
        secret=derive_password(seed, login).encode(),
        salt=salt,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
        hash_len=32,
        type=Type.ID,
    )
    return encoded.decode()


def _uuid(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)


def _weighted(rng: random.Random, pairs: Sequence[tuple[Any, int]]) -> Any:
    values = [value for value, _ in pairs]
    weights = [weight for _, weight in pairs]
    return rng.choices(values, weights=weights, k=1)[0]


def _due_date(rng: random.Random, today: date) -> date | None:
    match _weighted(rng, _DUE_WEIGHTS):
        case "overdue":
            return today - timedelta(days=rng.randint(1, 30))
        case "today":
            return today
        case "tomorrow":
            return today + timedelta(days=1)
        case "week":
            return today + timedelta(days=rng.randint(2, 6))
        case "later":
            return today + timedelta(days=rng.randint(7, 120))
        case _:
            return None


def _stamp(moment: datetime) -> dict[str, datetime]:
    return {"created_at": moment, "updated_at": moment}


def _task_row(
    rng: random.Random,
    *,
    workspace_id: UUID,
    project_id: UUID,
    parent_id: UUID | None,
    title: str,
    position: int | None,
    members: Sequence[UUID],
    today: date,
    created: datetime,
) -> dict[str, Any]:
    assignee = None if rng.random() < _UNASSIGNED_SHARE else rng.choice(members)
    return {
        "id": _uuid(rng),
        "workspace_id": workspace_id,
        "project_id": project_id,
        "parent_id": parent_id,
        "title": title,
        "description": "Синтетическая задача нагрузочного набора.",
        "status": _weighted(rng, _STATUS_WEIGHTS),
        "priority": _weighted(rng, _PRIORITY_WEIGHTS),
        "due_date": _due_date(rng, today),
        "assignee_id": assignee,
        "position": position,
        "created_by": rng.choice(members),
        **_stamp(created),
    }


def _title(rng: random.Random, number: int) -> str:
    return f"{rng.choice(_VERBS)} {rng.choice(_OBJECTS)}, задача {number}"


def _build_users(
    rng: random.Random, workspace_id: UUID, hashes: dict[str, str]
) -> tuple[_Plan, dict[str, UUID]]:
    plan = _Plan()
    ids: dict[str, UUID] = {}
    for login, role in _USERS:
        user_id = _uuid(rng)
        ids[login] = user_id
        plan.users.append(
            {
                "id": user_id,
                "login": login,
                "login_display": login,
                "password_hash": hashes[login],
                "must_change_password": False,
                "is_blocked": False,
                "blocked_at": None,
                "failed_login_count": 0,
                "login_locked_until": None,
                "password_changed_at": ANCHOR,
                "created_by": None,
                **_stamp(ANCHOR),
            }
        )
        plan.workspace_members.append(
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "role": role,
                "created_by": None,
                **_stamp(ANCHOR),
            }
        )
    return plan, ids


def _build_projects(
    rng: random.Random, plan: _Plan, workspace_id: UUID, ids: dict[str, UUID]
) -> dict[UUID, list[UUID]]:
    """Проекты и участники; тестовый пользователь — участник каждого проекта."""
    members_by_project: dict[UUID, list[UUID]] = {}
    regular = [login for login, role in _USERS if role == "user" and login != LOAD_TEST_LOGIN]
    for index, name in enumerate(_PROJECT_NAMES):
        owner = _OWNERS[index % len(_OWNERS)]
        other_owner = _OWNERS[(index + 1) % len(_OWNERS)]
        logins = [owner, other_owner, LOAD_TEST_LOGIN, *rng.sample(regular, 4)]
        project_id = _uuid(rng)
        owner_id = ids[owner]
        plan.projects.append(
            {
                "id": project_id,
                "workspace_id": workspace_id,
                "name": name,
                "description": f"Нагрузочный проект «{name}».",
                "owner_id": owner_id,
                "created_by": owner_id,
                "deleted_at": None,
                **_stamp(ANCHOR),
            }
        )
        member_ids = [ids[login] for login in logins]
        members_by_project[project_id] = member_ids
        plan.project_members.extend(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "user_id": user_id,
                "created_by": owner_id,
                **_stamp(ANCHOR),
            }
            for user_id in member_ids
        )
    return members_by_project


def _build_tasks(
    rng: random.Random,
    plan: _Plan,
    workspace_id: UUID,
    members_by_project: dict[UUID, list[UUID]],
    tasks: int,
) -> None:
    """Задачи верхнего уровня (по проектам, позиции) и подзадачи (к случайным родителям)."""
    subtask_count = tasks // SUBTASK_EVERY
    top_count = tasks - subtask_count
    today = today_msk(ANCHOR)
    per_project, extra = divmod(top_count, len(plan.projects))
    seq = 0
    for index, project in enumerate(plan.projects):
        project_id: UUID = project["id"]
        members = members_by_project[project_id]
        count = per_project + (1 if index < extra else 0)
        for position in range(1, count + 1):
            seq += 1
            plan.tasks.append(
                _task_row(
                    rng,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    parent_id=None,
                    title=_title(rng, seq),
                    position=STEP * position,
                    members=members,
                    today=today,
                    created=ANCHOR - timedelta(seconds=tasks - seq),
                )
            )
    for _ in range(subtask_count):
        seq += 1
        parent = rng.choice(plan.tasks)
        plan.subtasks.append(
            _task_row(
                rng,
                workspace_id=workspace_id,
                project_id=parent["project_id"],
                parent_id=parent["id"],
                title=_title(rng, seq),
                position=None,
                members=members_by_project[parent["project_id"]],
                today=today,
                created=ANCHOR - timedelta(seconds=tasks - seq),
            )
        )


def _build_comments(
    rng: random.Random,
    plan: _Plan,
    workspace_id: UUID,
    members_by_project: dict[UUID, list[UUID]],
) -> None:
    for task in plan.tasks:
        members = members_by_project[task["project_id"]]
        for number in range(_weighted(rng, _COMMENT_COUNT_WEIGHTS)):
            plan.comments.append(
                {
                    "id": _uuid(rng),
                    "workspace_id": workspace_id,
                    "task_id": task["id"],
                    "body": rng.choice(_COMMENT_BODIES),
                    "edited_at": None,
                    "created_by": rng.choice(members),
                    **_stamp(task["created_at"] + timedelta(seconds=number + 1)),
                }
            )


def _build_plan(seed: int, tasks: int, workspace_id: UUID, hashes: dict[str, str]) -> _Plan:
    """Строки набора; весь порядок обхода детерминирован, поэтому id совпадают при том же seed."""
    rng = random.Random(seed)
    plan, ids = _build_users(rng, workspace_id, hashes)
    members_by_project = _build_projects(rng, plan, workspace_id, ids)
    _build_tasks(rng, plan, workspace_id, members_by_project, tasks)
    _build_comments(rng, plan, workspace_id, members_by_project)
    return plan


async def _check_empty(session: AsyncSession) -> UUID:
    """Возвращает пространство или бросает исключение; ничего не меняет."""
    workspace_id = (
        await session.execute(
            select(Workspace.id).order_by(Workspace.created_at, Workspace.id).limit(1)
        )
    ).scalar_one_or_none()
    if workspace_id is None:
        raise LoadWorkspaceMissing("Пространства нет: сначала выполните gtrack bootstrap")
    projects = (await session.execute(select(func.count()).select_from(Project))).scalar_one()
    tasks = (await session.execute(select(func.count()).select_from(Task))).scalar_one()
    users = (await session.execute(select(func.count()).select_from(AppUser))).scalar_one()
    if projects or tasks:
        raise LoadDataRefused("В базе уже есть проекты или задачи: нагрузочный набор не загружен")
    if users > 1:
        raise LoadDataRefused(
            "В базе уже есть пользователи сверх первого техадминистратора: "
            "нагрузочный набор не загружен"
        )
    return workspace_id


async def _insert_chunked(
    session: AsyncSession, model: type[Any], rows: list[dict[str, Any]]
) -> None:
    for start in range(0, len(rows), _BATCH):
        await session.execute(insert(model), rows[start : start + _BATCH])


async def _insert_plan(session: AsyncSession, plan: _Plan) -> None:
    # порядок — по зависимостям внешних ключей (deferrable IMMEDIATE)
    await _insert_chunked(session, AppUser, plan.users)
    await _insert_chunked(session, WorkspaceMember, plan.workspace_members)
    await _insert_chunked(session, Project, plan.projects)
    await _insert_chunked(session, ProjectMember, plan.project_members)
    await _insert_chunked(session, Task, plan.tasks)
    await _insert_chunked(session, Task, plan.subtasks)
    await _insert_chunked(session, Comment, plan.comments)


async def load_synthetic_data(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    seed: int,
    tasks: int,
) -> LoadReport:
    """Загружает нагрузочный набор одной транзакцией; при наличии данных — ``LoadDataRefused``."""
    if tasks < MIN_TASKS:
        raise ValueError(f"tasks должно быть не меньше {MIN_TASKS}")
    async with sessionmaker() as session, session.begin():
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
        workspace_id = await _check_empty(session)
        hashes: dict[str, str] = {}
        for login, _ in _USERS:
            hashes[login] = await asyncio.to_thread(_password_hash, settings, seed, login)
        plan = _build_plan(seed, tasks, workspace_id, hashes)
        await _insert_plan(session, plan)
        return plan.report()
