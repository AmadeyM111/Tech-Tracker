"""Учётные записи без роли для бизнес-администратора.

Spec 019: FR-13a, AC-26, AC-30; plan §4.3, RG-11, RG-12.

БА (возможность ``onboard_accounts``) видит учётные записи пространства с ``role IS NULL`` (логин,
имя, фамилия, без email) и назначает им только роль «Пользователь». Роль «БА» или «ТА», смена и
снятие роли остаются за ТА (``users/service.py::set_role``). Заблокированная учётная запись без
роли показывается и получает роль (RG-12): без входа роль ничего не даёт, а событие видно в журнале.

Блокировки назначения (``_lock_for_onboarding``) сериализуются с действиями ТА над учётными
записями того же пространства через тот же advisory-ключ ``_ACCOUNT_LOCK_NAMESPACE``.
Протокол ``_lock_for_account_change`` требует, чтобы актор был ТА, поэтому у БА свой вариант:
после блокировок актор должен оставаться активным БА, иначе ``Forbidden`` (окно между
``get_actor`` и блокировкой).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import load_only

from app.core.errors import Forbidden, NotFound
from app.core.pagination import PageParams, paginate
from app.domain.access.roles import Actor, Capability, Role
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.users.models import AppUser
from app.domain.users.service import _ACCOUNT_LOCK_NAMESPACE
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class UnassignedAccount:
    """Учётная запись без роли для БА: без email и без хеша пароля (AC-30)."""

    id: UUID
    login: str
    first_name: str | None
    last_name: str | None
    created_at: datetime


def _require_onboarding(actor: Actor) -> None:
    """Право БА на учётные записи без роли (RG-11); у ТА и «Пользователя» его нет (403)."""
    if not actor.can(Capability.ONBOARD_ACCOUNTS):
        raise Forbidden()


async def list_unassigned(
    db: AsyncSession, actor: Actor, params: PageParams
) -> tuple[list[UnassignedAccount], bool]:
    """Страница учётных записей пространства актора без роли (FR-13a, AC-30).

    Сортировка ``login ASC, id ASC``. Email в выборку не попадает (``load_only``): ответ для БА
    его не содержит. Второй элемент — признак следующей страницы.
    """
    _require_onboarding(actor)
    stmt = (
        select(AppUser)
        .options(
            load_only(
                AppUser.id,
                AppUser.login_display,
                AppUser.first_name,
                AppUser.last_name,
                AppUser.created_at,
            )
        )
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(
            WorkspaceMember.workspace_id == actor.workspace_id,
            WorkspaceMember.role.is_(None),
        )
        .order_by(AppUser.login, AppUser.id)
    )
    users, has_next = await paginate(db, stmt, params)
    items = [
        UnassignedAccount(
            id=user.id,
            login=user.login_display,
            first_name=user.first_name,
            last_name=user.last_name,
            created_at=user.created_at,
        )
        for user in users
    ]
    return items, has_next


async def _lock_for_onboarding(
    db: AsyncSession, workspace_id: UUID, target_id: UUID, actor_id: UUID
) -> None:
    """Блокировки перед назначением роли БА (plan §4.3, RG-11).

    1. ``pg_advisory_xact_lock`` по пространству с тем же ключом, что у
       ``_lock_for_account_change``: назначение сериализуется с действиями ТА (блокировка,
       смена роли и т.п.) этого пространства.
    2. Строки ``workspace_member`` актора и цели в порядке ``user_id`` (тот же режим и порядок,
       что в ``_lock_for_account_change``).
    3. Актор должен быть активным БА после блокировок (роль и ``is_blocked`` читаются из БД, а не из
       объекта ``Actor``, снятого в ``get_actor``); иначе ``Forbidden``.
    """
    await db.execute(
        select(
            func.pg_advisory_xact_lock(_ACCOUNT_LOCK_NAMESPACE, func.hashtext(str(workspace_id)))
        )
    )
    rows = (
        await db.execute(
            select(WorkspaceMember.user_id, WorkspaceMember.role, AppUser.is_blocked)
            .join(AppUser, AppUser.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id.in_((actor_id, target_id)),
            )
            .order_by(WorkspaceMember.user_id)
            .with_for_update(key_share=True)
        )
    ).all()
    actor_is_active_ba = any(
        row.user_id == actor_id and row.role == Role.BUSINESS_ADMIN.value and not row.is_blocked
        for row in rows
    )
    if not actor_is_active_ba:
        raise Forbidden()


async def _target_role(db: AsyncSession, workspace_id: UUID, user_id: UUID) -> str | None:
    """Роль цели в пространстве актора; цели нет в пространстве — ``NotFound`` (чужое, нет id)."""
    row = (
        await db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFound()
    current: str | None = row.role
    return current


async def assign_user_role(
    db: AsyncSession, actor: Actor, user_id: UUID, role: Role | None, /
) -> None:
    """Назначает роль «Пользователь» учётной записи без роли (FR-13a, AC-26, AC-30).

    Порядок: право БА (403) -> роль не «Пользователь», в том числе ``None`` (403, без
    блокировок) -> блокировки и активность актора (403) -> цель в пространстве (404) -> у цели
    уже есть роль (403) -> UPDATE и событие ``user.role_assigned`` с автором-БА
    (``role_from=None``, ``role_to="user"``).
    """
    _require_onboarding(actor)
    if role != Role.USER:
        raise Forbidden()
    await _lock_for_onboarding(db, actor.workspace_id, user_id, actor.user_id)
    current_role = await _target_role(db, actor.workspace_id, user_id)
    if current_role is not None:
        raise Forbidden()
    await db.execute(
        update(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == actor.workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.role.is_(None),
        )
        .values(role=Role.USER.value)
        .execution_options(synchronize_session=False)
    )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_ROLE_ASSIGNED,
        entity_id=user_id,
        details=UserEventDetails(role_from=None, role_to=Role.USER.value),
    )
