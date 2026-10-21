"""Сервис задач: создание, изменение, удаление, перемещение (plan §11.4, §11.5, §4.5, §10.2;
D-46, D-52, D-55, D-56).

Не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``. Порядок проверок: проект
или задача (404) -> ``FOR SHARE`` проекта (§10.2 п.2) -> права (403) -> входные данные (422) ->
глубина (422, подзадача) -> получатель (422, ``FOR SHARE``, п.3) -> колонка (п.4) -> запись.
Событий ленты нет (D-55). Название и описание хранятся как введены (D-52).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select, update

from app.core.clock import today_msk, utcnow
from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.domain.access.policy import (
    ProjectFacts,
    TaskFacts,
    can_change_assignee,
    can_change_task_status,
    can_create_subtask,
    can_create_task,
    can_delete_task,
    can_edit_task_fully,
    can_read_project_content,
)
from app.domain.access.recipients import RecipientPurpose, check_recipient
from app.domain.access.roles import Actor, Role
from app.domain.comments.models import Comment
from app.domain.projects.models import ProjectMember
from app.domain.projects.queries import load_project_facts
from app.domain.tasks import positions
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.positions import append_position, lock_columns
from app.domain.users.directory import load_recipient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TITLE_MAX: Final = 255
DESCRIPTION_MAX: Final = 10_000


class Unset(Enum):
    """Тип сентинела «поле не передано» (отличается от явного ``None``)."""

    UNSET = 0


UNSET: Final = Unset.UNSET


@dataclass(frozen=True)
class TaskCreateData:
    """``assignee``: ``UNSET`` — не передан, ``None`` — явно без исполнителя."""

    title: str
    description: str = ""
    assignee: UUID | None | Unset = UNSET
    due_date: date | None = None
    priority: str | TaskPriority = TaskPriority.MEDIUM.value


def _invalid(message: str) -> Unprocessable:
    return Unprocessable(message, code=ErrorCode.validation_error)


def _validate(data: TaskCreateData) -> TaskPriority:
    """Проверка входных данных; возвращает приоритет. Строки не нормализуются (D-52)."""
    title, description = data.title, data.description
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX:
        raise _invalid("Название задачи: от 1 до 255 символов, не только пробелы")
    if not isinstance(description, str) or len(description) > DESCRIPTION_MAX:
        raise _invalid("Описание задачи: не более 10000 символов")
    if "\x00" in title or "\x00" in description:
        raise _invalid("Текст не может содержать нулевой символ")
    due = data.due_date
    if due is not None and (not isinstance(due, date) or isinstance(due, datetime)):
        raise _invalid("Срок задачи: дата без времени")
    try:
        return TaskPriority(data.priority)
    except ValueError:
        raise _invalid("Приоритет: low, medium или high") from None


def _effective_assignee(actor: Actor, data: TaskCreateData, *, top_level: bool) -> UUID | None:
    """Не передан: задача — создатель (006/FR-17, D-4); подзадача — «Пользователь» сам,
    БА — без исполнителя (AC-109). Передан (в т.ч. ``None``) — как передан."""
    if data.assignee is UNSET:
        if top_level or actor.role == Role.USER:
            return actor.user_id
        return None
    assert not isinstance(data.assignee, Unset)
    return data.assignee


def _check_top_level(values: Mapping[str, Any], today: date) -> None:
    """006/FR-15…FR-17, FR-23: проверяет только присутствующие ключи ``description``,
    ``due_date``, ``assignee_id``. Сначала ``validation_error``, затем срок в прошлом."""
    if "description" in values and (
        not isinstance(values["description"], str) or not values["description"].strip()
    ):
        raise _invalid("Описание задачи обязательно")
    if "due_date" in values and values["due_date"] is None:
        raise _invalid("Срок задачи обязателен")
    if "assignee_id" in values and values["assignee_id"] is None:
        raise _invalid("Исполнитель задачи обязателен")
    due = values.get("due_date")
    if due is not None and due < today:
        raise Unprocessable(
            "Срок не может быть раньше сегодняшнего дня", code=ErrorCode.due_date_in_past
        )


async def _check_assignee(
    db: AsyncSession, actor: Actor, project: ProjectFacts, assignee_id: UUID | None
) -> None:
    """Получатель ``TASK_ASSIGNEE`` под ``FOR SHARE`` (§10.2 п.3); владелец — всегда участник."""
    if assignee_id is None:
        return
    recipient = await load_recipient(db, actor.workspace_id, assignee_id, lock=True)
    is_member = (
        assignee_id == project.owner_id
        or (
            await db.execute(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project.project_id,
                    ProjectMember.user_id == assignee_id,
                )
            )
        ).first()
        is not None
    )
    check_recipient(
        recipient,
        RecipientPurpose.TASK_ASSIGNEE,
        project_member_ids=frozenset({assignee_id}) if is_member else frozenset(),
    )


async def create_task(
    db: AsyncSession, actor: Actor, project_id: UUID, data: TaskCreateData
) -> UUID:
    """Новая задача в конце колонки «К выполнению» (AC-24, AC-49, AC-61; 006/FR-15…FR-18)."""
    project = await load_project_facts(db, actor, project_id, lock="share")
    assignee_id = _effective_assignee(actor, data, top_level=True)
    if not can_create_task(actor, project, assignee_id):
        raise Forbidden()
    priority = _validate(data)
    _check_top_level(
        {"description": data.description, "due_date": data.due_date, "assignee_id": assignee_id},
        today_msk(),
    )
    await _check_assignee(db, actor, project, assignee_id)
    await lock_columns(db, project_id, TaskStatus.TODO)
    task = Task(
        workspace_id=actor.workspace_id,
        project_id=project_id,
        title=data.title,
        description=data.description,
        status=TaskStatus.TODO.value,
        priority=priority.value,
        due_date=data.due_date,
        assignee_id=assignee_id,
        position=await append_position(db, project_id, TaskStatus.TODO),
        created_by=actor.user_id,
    )
    db.add(task)
    await db.flush()
    return task.id


async def create_subtask(
    db: AsyncSession, actor: Actor, parent_id: UUID, data: TaskCreateData
) -> UUID:
    """Подзадача: без позиции, статус ``todo``, проект родителя; глубина — один уровень."""
    ctx = await load_task_context(db, actor, parent_id, lock_project="share")
    assignee_id = _effective_assignee(actor, data, top_level=False)
    if not can_create_subtask(actor, ctx.project, ctx.task, assignee_id):
        raise Forbidden()
    priority = _validate(data)
    if ctx.task.parent_id is not None:
        raise Unprocessable(
            "Подзадачу нельзя вложить в подзадачу", code=ErrorCode.subtask_depth_exceeded
        )
    await _check_assignee(db, actor, ctx.project, assignee_id)
    # Строка родителя под FOR SHARE после получателя (§10.2 п.3 -> п.5): ``delete_task`` берёт её
    # FOR NO KEY UPDATE, поэтому неудалённая подзадача не останется под удалённым родителем;
    # права перепроверяются по фактам, перечитанным под блокировкой.
    row = (
        await db.execute(
            select(Task.created_by, Task.assignee_id, Task.parent_id)
            .where(Task.id == parent_id, Task.deleted_at.is_(None))
            .with_for_update(read=True)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Задача не найдена")
    parent = TaskFacts(
        created_by=row.created_by, assignee_id=row.assignee_id, parent_id=row.parent_id
    )
    if not can_create_subtask(actor, ctx.project, parent, assignee_id):
        raise Forbidden()
    task = Task(
        workspace_id=actor.workspace_id,
        project_id=ctx.project.project_id,
        parent_id=parent_id,
        title=data.title,
        description=data.description,
        status=TaskStatus.TODO.value,
        priority=priority.value,
        due_date=data.due_date,
        assignee_id=assignee_id,
        position=None,
        created_by=actor.user_id,
    )
    db.add(task)
    await db.flush()
    return task.id


@dataclass(frozen=True)
class TaskPatch:
    """``UNSET`` — поле не передано; ``None`` у ``assignee_id``/``due_date`` снимает значение."""

    title: str | Unset = UNSET
    description: str | Unset = UNSET
    assignee_id: UUID | None | Unset = UNSET
    due_date: date | None | Unset = UNSET
    priority: str | TaskPriority | Unset = UNSET
    status: str | TaskStatus | Unset = UNSET


_FIELDS: Final = ("title", "description", "assignee_id", "due_date", "priority", "status")
_FULL_EDIT_FIELDS: Final = ("title", "description", "due_date", "priority")


async def _load_task(db: AsyncSession, task_id: UUID) -> Task:
    """Свежая строка задачи (``populate_existing``): снимок в сессии мог устареть."""
    task = (
        await db.execute(
            select(Task)
            .where(Task.id == task_id, Task.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Задача не найдена")
    return task


async def _lock_task(db: AsyncSession, task_id: UUID) -> Task:
    """Строка задачи FOR NO KEY UPDATE с перечитыванием; удалена — ``404``."""
    task = (
        await db.execute(
            select(Task)
            .where(Task.id == task_id, Task.deleted_at.is_(None))
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Задача не найдена")
    return task


def _status(value: str | TaskStatus) -> TaskStatus:
    try:
        return TaskStatus(value)
    except ValueError:
        raise _invalid("Статус: todo, in_progress, review или done") from None


def _changes(task: Task, patch: TaskPatch) -> dict[str, Any]:
    """D-46: только поля, значение которых отличается от строки ``task``."""
    return {
        name: value
        for name in _FIELDS
        if (value := getattr(patch, name)) is not UNSET and value != getattr(task, name)
    }


def _authorize(actor: Actor, project: ProjectFacts, task: Task, changed: dict[str, Any]) -> None:
    """Права по реально меняющимся полям (FR-19) и проверка входных данных (422).

    Для задачи верхнего уровня после ``_validate`` — правила 006/FR-23 по меняющимся полям."""
    facts = TaskFacts(
        created_by=task.created_by, assignee_id=task.assignee_id, parent_id=task.parent_id
    )
    if "status" in changed and not can_change_task_status(actor, project, facts):
        raise Forbidden()
    if "assignee_id" in changed and not can_change_assignee(actor, project, facts):
        raise Forbidden()
    if any(f in changed for f in _FULL_EDIT_FIELDS) and not can_edit_task_fully(
        actor, project, facts
    ):
        raise Forbidden()
    _validate(
        TaskCreateData(
            title=changed.get("title", task.title),
            description=changed.get("description", task.description),
            due_date=changed.get("due_date", task.due_date),
            priority=changed.get("priority", task.priority),
        )
    )
    if task.parent_id is None:
        _check_top_level(changed, today_msk())
    if "status" in changed:
        _status(changed["status"])


async def _precheck_assignee(
    db: AsyncSession,
    actor: Actor,
    project: ProjectFacts,
    patch: TaskPatch,
    changed: dict[str, Any],
) -> Unprocessable | None:
    """Получатель — до блокировки строки (§10.2 п.3 раньше п.5), даже если по снимку он не
    меняется: чужая правка может сделать его изменением. Тогда ошибка возвращается и
    поднимается только после пересчёта ``changed`` по свежей строке."""
    if not isinstance(patch.assignee_id, UUID):
        return None
    try:
        await _check_assignee(db, actor, project, patch.assignee_id)
    except Unprocessable as exc:
        if "assignee_id" in changed:
            raise
        return exc
    return None


async def update_task(db: AsyncSession, actor: Actor, task_id: UUID, patch: TaskPatch) -> None:
    """Изменение полей (FR-19, D-46): права — по реально меняющимся полям, всё или ничего.

    Снимок до блокировок даёт ранние 403/422; после блокировки строки ``changed`` и права
    пересчитываются по свежей строке (чужая правка, зафиксированная за время ожидания,
    учитывается как при последовательном выполнении). Порядок §10.2: получатель (п.3) ->
    колонки (п.4, если в запросе есть статус задачи верхнего уровня) -> строка (п.5).
    """
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    # D-46: «права и 404 как обычно» — доступ к содержимому проверяется и при пустом PATCH.
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    task = await _load_task(db, task_id)
    changed = _changes(task, patch)
    if not changed:
        return
    _authorize(actor, ctx.project, task, changed)
    recipient_error = await _precheck_assignee(db, actor, ctx.project, patch, changed)
    status = None if isinstance(patch.status, Unset) else _status(patch.status)
    if status is not None and task.parent_id is None:
        await positions.lock_task_columns(db, task, status)
    task = await _lock_task(db, task_id)

    changed = _changes(task, patch)
    if not changed:
        return
    _authorize(actor, ctx.project, task, changed)
    if recipient_error is not None and "assignee_id" in changed:
        raise recipient_error
    if "status" in changed:
        assert status is not None
        if task.parent_id is None:
            await positions.move_task(
                db, task, status=status, before_task_id=None, after_task_id=None
            )
        else:
            task.status = status.value
    for name in (*_FULL_EDIT_FIELDS, "assignee_id"):
        if name in changed:
            value = changed[name]
            setattr(task, name, TaskPriority(value).value if name == "priority" else value)
    await db.flush()


async def delete_task(db: AsyncSession, actor: Actor, task_id: UUID) -> None:
    """Мягкое удаление с каскадом D-56: один ``deleted_at``/``deleted_batch_id`` на пакет."""
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    if not can_delete_task(actor, ctx.project, ctx.task):
        raise Forbidden()
    # Порядок §10.2 п.5: сначала строки задач (сама задача, затем живые подзадачи по ``id``),
    # потом комментарии — как у параллельного удаления подзадачи; иначе взаимоблокировка.
    # Строка под FOR NO KEY UPDATE: ждёт создателя подзадачи (FOR SHARE) и закрывает новых.
    locked = (
        await db.execute(
            select(Task.id)
            .where(Task.id == task_id, Task.deleted_at.is_(None))
            .with_for_update(key_share=True)
        )
    ).first()
    if locked is None:
        raise NotFound("Задача не найдена")
    sub_ids = (
        (
            await db.execute(
                select(Task.id)
                .where(Task.parent_id == task_id, Task.deleted_at.is_(None))
                .order_by(Task.id)
                .with_for_update(key_share=True)
            )
        )
        .scalars()
        .all()
    )
    # Семья — только неудалённые (под уже удалённой подзадачей пакет комментариев прежний).
    family = [task_id, *sub_ids]
    stamp = {"deleted_at": utcnow(), "deleted_batch_id": uuid4()}
    await db.execute(
        update(Task)
        .where(Task.id.in_(family), Task.deleted_at.is_(None))
        .values(**stamp)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(Comment)
        .where(Comment.task_id.in_(family), Comment.deleted_at.is_(None))
        .values(**stamp)
    )


async def move(
    db: AsyncSession,
    actor: Actor,
    task_id: UUID,
    *,
    status: str | TaskStatus,
    before_task_id: UUID | None,
    after_task_id: UUID | None,
) -> None:
    """Перенос карточки между соседями (FR-28a): ``after`` — сосед сверху, ``before`` — снизу."""
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    if not can_change_task_status(actor, ctx.project, ctx.task):
        raise Forbidden()
    if ctx.task.parent_id is not None:  # 422 только после 403: не участник не узнает о подзадаче
        raise _invalid(positions.SUBTASK_NOT_ON_BOARD)
    target = _status(status)
    task = await _load_task(db, task_id)
    await positions.move_task(
        db, task, status=target, before_task_id=before_task_id, after_task_id=after_task_id
    )
    await db.flush()
