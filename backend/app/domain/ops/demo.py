"""Демо-данные (plan §11.8, D-63, D-6, FR-49 в редакции SC-13, FR-64, BR-9).

``load_demo_data`` одной транзакцией создаёт 12 демо-пользователей, 2 проекта, 30 задач
(6 из них подзадачи) и комментарии прямыми вставками ORM (без сервисов и ``Actor``). События
проектов и задач не пишутся (D-55); пишутся ``user.created`` и ``user.role_assigned`` с автором
«система» (``actor_id = NULL``). Пароли пишутся в ``secrets_dir/demo-passwords.txt`` (0600).

Порядок: проверка отказа -> строки -> файл -> фиксация. При ошибке фиксации файл удаляется,
если отдельной сессией подтверждено, что демо-данные не зафиксированы (как у первого ТА,
plan §4.7). Выбор данных — ``random.Random(seed)``; пароли случайны и от seed не зависят.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from app.core.clock import Clock, today_msk, use_clock
from app.core.config import Settings
from app.core.secrets import ensure_private_dir, write_private_file
from app.core.security.passwords import PasswordHasher, generate_password, hash_in_thread
from app.domain.comments.models import Comment
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.positions import STEP
from app.domain.users.models import AppUser
from app.domain.workspaces.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEMO_PASSWORDS_FILE: Final = "demo-passwords.txt"

# bigint-константа блокировки (ASCII «GOST» + номер): два параллельных запуска не вставят дубли
_DEMO_LOCK_KEY: Final = 0x474F535400000002

# БА - участник обоих демо-проектов, не владелец (002/FR-22, D-13)
_ALL_PROJECTS_BA: Final = "demo.ba4"

# читается как глобальное имя модуля во время вызова (подмена в тесте AC-30, plan D-13)
_USERS: Final[tuple[tuple[str, str], ...]] = (
    ("demo.ta", "tech_admin"),
    (_ALL_PROJECTS_BA, "business_admin"),
    ("demo.ba1", "business_admin"),
    ("demo.ba2", "business_admin"),
    ("demo.ba3", "business_admin"),
    *((f"demo.user{i}", "user") for i in range(1, 8)),
)

# (название, владелец, второй БА, П проекта, названия задач верхнего уровня)
_PROJECTS: Final = (
    (
        "Внедрение трекера",
        "demo.ba1",
        "demo.ba2",
        ("demo.user1", "demo.user2", "demo.user3", "demo.user4"),
        (
            "Описать текущий процесс",
            "Собрать требования команд",
            "Настроить рабочее пространство",
            "Подготовить учётные записи",
            "Согласовать роли",
            "Заполнить справочники",
            "Провести обучение",
            "Подготовить инструкцию",
            "Организовать пробный запуск",
            "Собрать обратную связь",
            "Исправить замечания",
            "Подвести итоги внедрения",
        ),
    ),
    (
        "Подготовка пилота",
        "demo.ba2",
        "demo.ba1",
        ("demo.user4", "demo.user5", "demo.user6", "demo.user7"),
        (
            "Определить цели пилота",
            "Выбрать пилотные группы",
            "Составить план пилота",
            "Подготовить стенд",
            "Загрузить тестовые данные",
            "Проверить права доступа",
            "Подготовить сценарии проверки",
            "Назначить ответственных",
            "Запланировать встречи",
            "Согласовать критерии успеха",
            "Подготовить отчёт",
            "Оценить результаты пилота",
        ),
    ),
)
_COMMENTS: Final = (
    "Взял в работу.",
    "Нужно уточнить детали у заказчика.",
    "Готово, прошу проверить.",
    "Есть замечания, см. описание.",
    "Перенёс срок, согласовано.",
    "Блокирует следующую задачу.",
    "Обновил описание по итогам встречи.",
    "Проверил, всё в порядке.",
)
_STATUSES: Final = (
    TaskStatus.TODO.value,
    TaskStatus.IN_PROGRESS.value,
    TaskStatus.REVIEW.value,
    TaskStatus.DONE.value,
)
_TOP_PER_PROJECT: Final = 12
_HIGH_PER_PROJECT: Final = 3  # 6 из 30 — «около 1/4» от задач верхнего уровня
_SUBTASK_PARENTS: Final = 3
_SUBTASKS_PER_PARENT: Final = 2


class DemoDataRefused(Exception):
    """Загрузка демо-данных отказана: в базе уже есть данные; ничего не изменено."""


class WorkspaceMissing(DemoDataRefused):
    """Пространства нет: ``gostracker bootstrap`` не выполнялся (ошибка установки, не отказ)."""


@dataclass(frozen=True)
class DemoReport:
    users: int
    projects: int
    tasks: int  # включая подзадачи
    subtasks: int
    comments: int
    passwords_file: Path


@dataclass
class _Plan:
    """Строки, готовые к вставке; собираются без обращения к БД."""

    projects: list[Project]
    tasks: list[Task]
    subtasks: list[Task]
    comments: list[Comment]
    project_members: list[ProjectMember]


def _stamp(base: datetime, number: int) -> dict[str, datetime]:
    """Метки строки с порядковым номером: ``base`` + номер секунд (детерминированно, различны)."""
    moment = base + timedelta(seconds=number)
    return {"created_at": moment, "updated_at": moment}


def _add_subtasks(
    rng: random.Random,
    plan: _Plan,
    members_by_project: dict[UUID, list[UUID]],
    number: int,
    base: datetime,
) -> None:
    # подзадачи: 3 родителя (по одному-двум на проект), по 2 подзадачи, позиции нет;
    # автор — владелец проекта (SC-20: «Пользователь» не ставит подзадачу другому)
    owners = {p.id: p.owner_id for p in plan.projects}
    parents = rng.sample(plan.tasks, _SUBTASK_PARENTS)
    for parent in parents:
        members = members_by_project[parent.project_id]
        for step in range(1, _SUBTASKS_PER_PARENT + 1):
            number += 1
            plan.subtasks.append(
                Task(
                    id=uuid4(),
                    workspace_id=parent.workspace_id,
                    project_id=parent.project_id,
                    parent_id=parent.id,
                    title=f"{parent.title}: шаг {step}",
                    description="Демо-подзадача.",
                    status=rng.choice(_STATUSES),
                    priority=TaskPriority.BASE.value,
                    due_date=None,
                    assignee_id=rng.choice(members),
                    position=None,
                    created_by=owners[parent.project_id],
                    **_stamp(base, number),
                )
            )


def _build_content(
    rng: random.Random, workspace_id: UUID, ids: dict[str, UUID], base: datetime
) -> _Plan:
    today = today_msk(base)
    number = len(_USERS)  # пользователи заняли номера 0..11
    plan = _Plan([], [], [], [], [])
    members_by_project: dict[UUID, list[UUID]] = {}
    for name, owner, other_ba, users, titles in _PROJECTS:
        owner_id = ids[owner]
        project = Project(
            id=uuid4(),
            workspace_id=workspace_id,
            name=name,
            description=f"Демонстрационный проект «{name}».",
            owner_id=owner_id,
            created_by=owner_id,
            **_stamp(base, number),
        )
        number += 1
        plan.projects.append(project)
        # владельцу — строка участника (заметка ревью T71)
        logins = (owner, other_ba, _ALL_PROJECTS_BA, *users)
        members = [ids[login] for login in logins]
        members_by_project[project.id] = members
        plan.project_members.extend(
            ProjectMember(
                workspace_id=workspace_id,
                project_id=project.id,
                user_id=user_id,
                created_by=owner_id,
                **_stamp(base, number),
            )
            for user_id in members
        )

        statuses = [s for s in _STATUSES for _ in range(_TOP_PER_PROJECT // len(_STATUSES))]
        rng.shuffle(statuses)
        high = set(rng.sample(range(_TOP_PER_PROJECT), _HIGH_PER_PROJECT))
        user_ids = [ids[login] for login in users]
        counters: dict[str, int] = {}
        top: list[Task] = []
        for index, title in enumerate(titles):
            status = statuses[index]
            counters[status] = counters.get(status, 0) + 1
            # каждая третья задача — «своя» у П (автор = исполнитель); остальные — от владельца
            if index % 3 == 0:
                assignee_id: UUID | None = rng.choice(user_ids)
                author_id = assignee_id
            else:
                assignee_id = rng.choice([*members, None])
                author_id = owner_id
            number += 1
            due = None if index % 4 == 3 else today + timedelta(days=rng.randint(-3, 14))
            top.append(
                Task(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    project_id=project.id,
                    parent_id=None,
                    title=title,
                    description=f"Демо-задача проекта «{name}».",
                    status=status,
                    priority=(TaskPriority.HIGH if index in high else TaskPriority.BASE).value,
                    due_date=due,
                    assignee_id=assignee_id,
                    position=STEP * counters[status],
                    created_by=author_id,
                    **_stamp(base, number),
                )
            )
        plan.tasks.extend(top)

        for _ in range(rng.randint(8, 12)):  # 16..24 на два проекта
            number += 1
            plan.comments.append(
                Comment(
                    workspace_id=workspace_id,
                    task_id=rng.choice(top).id,
                    body=rng.choice(_COMMENTS),
                    created_by=rng.choice(members),
                    **_stamp(base, number),
                )
            )

    _add_subtasks(rng, plan, members_by_project, number, base)
    return plan


async def _check_empty(session: AsyncSession) -> UUID:
    """Возвращает пространство или бросает ``DemoDataRefused``; ничего не меняет."""
    workspace_id = (
        await session.execute(
            select(Workspace.id).order_by(Workspace.created_at, Workspace.id).limit(1)
        )
    ).scalar_one_or_none()
    if workspace_id is None:
        raise WorkspaceMissing("Пространства нет: сначала выполните gostracker bootstrap")
    projects = (await session.execute(select(func.count()).select_from(Project))).scalar_one()
    tasks = (await session.execute(select(func.count()).select_from(Task))).scalar_one()
    users = (await session.execute(select(func.count()).select_from(AppUser))).scalar_one()
    if projects or tasks:
        raise DemoDataRefused("В базе уже есть проекты или задачи: демо-данные не загружены")
    if users > 1:
        raise DemoDataRefused(
            "В базе уже есть пользователи сверх первого техадминистратора: демо-данные не загружены"
        )
    return workspace_id


async def _demo_committed(sessionmaker: async_sessionmaker[AsyncSession]) -> bool | None:
    """Зафиксированы ли демо-пользователи; ``None`` — проверить не удалось."""
    try:
        async with sessionmaker() as check:
            found = (
                await check.execute(select(AppUser.id).where(AppUser.login == _USERS[0][0]))
            ).scalar_one_or_none()
    except Exception:
        return None
    return found is not None


async def _insert_users(
    session: AsyncSession, settings: Settings, workspace_id: UUID, base: datetime
) -> tuple[dict[str, UUID], dict[str, str]]:
    """Создаёт демо-учётные записи, роли и события; возвращает ``(id, пароли)`` по логинам."""
    hasher = await asyncio.to_thread(
        partial(
            PasswordHasher,
            time_cost=settings.argon2_time_cost,
            memory_cost_kib=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
        )
    )
    passwords: dict[str, str] = {}
    ids: dict[str, UUID] = {}
    for number, (login, role) in enumerate(_USERS):
        stamp = _stamp(base, number)
        password = generate_password()
        passwords[login] = password
        user = AppUser(
            login=login,
            password_hash=await hash_in_thread(hasher, password),
            must_change_password=True,
            is_blocked=False,
            created_by=None,
            **stamp,
        )
        session.add(user)
        await session.flush()
        ids[login] = user.id
        session.add(
            WorkspaceMember(
                workspace_id=workspace_id, user_id=user.id, role=role, created_by=None, **stamp
            )
        )
        await session.flush()
        await record_event(
            session,
            workspace_id=workspace_id,
            actor_id=None,
            action=EventAction.USER_CREATED,
            entity_id=user.id,
        )
        await record_event(
            session,
            workspace_id=workspace_id,
            actor_id=None,
            action=EventAction.USER_ROLE_ASSIGNED,
            entity_id=user.id,
            details=UserEventDetails(role_from=None, role_to=role),
        )
    return ids, passwords


def _write_passwords(settings: Settings, path: Path, passwords: dict[str, str]) -> None:
    ensure_private_dir(settings.secrets_dir)
    # строк демо нет, а файл есть: остаток прежнего запуска, его пароли нигде не действуют;
    # параллельный запуск отсекает advisory-блокировка
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    write_private_file(
        path, "".join(f"login={login}\tpassword={pw}\n" for login, pw in passwords.items())
    )


async def load_demo_data(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    clock: Clock,
    seed: int,
) -> DemoReport:
    """Загружает демо-данные одной транзакцией; при наличии данных — ``DemoDataRefused``."""
    path = settings.secrets_dir / DEMO_PASSWORDS_FILE
    file_written = False
    try:
        with use_clock(clock):
            async with sessionmaker() as session, session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _DEMO_LOCK_KEY}
                )
                workspace_id = await _check_empty(session)
                base = clock.now()
                ids, passwords = await _insert_users(session, settings, workspace_id, base)
                plan = _build_content(random.Random(seed), workspace_id, ids, base)
                session.add_all(plan.projects)
                await session.flush()
                session.add_all(plan.project_members)
                session.add_all(plan.tasks)
                await session.flush()
                session.add_all(plan.subtasks)
                session.add_all(plan.comments)
                await session.flush()
                report = DemoReport(
                    users=len(_USERS),
                    projects=len(plan.projects),
                    tasks=len(plan.tasks) + len(plan.subtasks),
                    subtasks=len(plan.subtasks),
                    comments=len(plan.comments),
                    passwords_file=path,
                )
                _write_passwords(settings, path, passwords)
                file_written = True
            # здесь выполнена фиксация транзакции (выход из session.begin())
    except Exception:
        # COMMIT мог дойти до БД, а подтверждение потеряться: тогда пароли действуют, и файл
        # удалять нельзя; исход неизвестен (БД недоступна) - файл остаётся (как у первого ТА)
        if file_written and await _demo_committed(sessionmaker) is False:
            with contextlib.suppress(OSError):
                path.unlink()
        raise
    return report
