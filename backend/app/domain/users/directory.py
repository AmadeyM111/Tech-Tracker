"""Справочник пользователей и загрузка получателей (plan §10.2 п.3, §10.4, D-24, FR-13, FR-70).

Только чтение: ``password_hash`` и счётчики входа не выбираются. Все выборки ограничены
пространством (AC-21): чужие и неизвестные пользователи выглядят одинаково.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, literal, select

from app.core.pagination import PageParams
from app.domain.access.recipients import RecipientFacts
from app.domain.access.roles import ROLE_CAPABILITIES, Actor, Capability, Role
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

# Роли, которые могут быть исполнителем, участником и владельцем: БА, СМ, «Пользователь».
_DIRECTORY_ROLES = sorted(
    role.value for role, caps in ROLE_CAPABILITIES.items() if Capability.BUSINESS_ACCESS in caps
)


@dataclass(frozen=True)
class DirectoryUser:
    id: UUID
    login: str
    role: Role


@dataclass(frozen=True)
class UserRef:
    id: UUID
    login: str


def _like_pattern(q: str) -> str:
    """Подстрока для ``ILIKE ... ESCAPE '\\'``: ``\\``, ``%`` и ``_`` — литералы (D-24)."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def list_directory(
    db: AsyncSession, actor: Actor, params: PageParams, *, q: str | None
) -> tuple[list[DirectoryUser], bool]:
    """Страница незаблокированных пользователей пространства с ролью БА/СМ/П (``login, id``).

    Список и роль читаются одним SELECT (JOIN ``workspace_member``): нет гонки между ними.
    ``paginate`` работает с одной сущностью, поэтому ``LIMIT page_size + 1`` применён здесь.
    Второй элемент — признак следующей страницы.
    """
    stmt = (
        select(AppUser.id, AppUser.login, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(
            WorkspaceMember.workspace_id == actor.workspace_id,
            WorkspaceMember.role.in_(_DIRECTORY_ROLES),
            AppUser.is_blocked.is_(False),
        )
        .order_by(AppUser.login, AppUser.id)
    )
    if q:
        stmt = stmt.where(AppUser.login.ilike(_like_pattern(q), escape="\\"))
    offset = (params.page - 1) * params.page_size
    stmt = stmt.limit(params.page_size + 1).offset(literal(offset, BigInteger()))
    rows = (await db.execute(stmt)).all()
    items = [DirectoryUser(id=r.id, login=r.login, role=Role(r.role)) for r in rows]
    return items[: params.page_size], len(items) > params.page_size


async def load_recipient(
    db: AsyncSession, workspace_id: UUID, user_id: UUID, *, lock: bool
) -> RecipientFacts:
    """Факты получателя для ``check_recipient`` (FR-70).

    Нет членства в пространстве (чужой или неизвестный) — ``in_workspace=False``. ``lock=True`` —
    строки ``app_user`` и ``workspace_member`` ``FOR SHARE``: блокировка и смена роли
    дожидаются завершения транзакции (§10.2 п.3).
    """
    stmt = (
        select(AppUser.is_blocked, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(WorkspaceMember.workspace_id == workspace_id, AppUser.id == user_id)
    )
    if lock:
        stmt = stmt.with_for_update(read=True, of=[AppUser, WorkspaceMember])
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return RecipientFacts(user_id=user_id, in_workspace=False, is_blocked=False, role=None)
    return RecipientFacts(
        user_id=user_id,
        in_workspace=True,
        is_blocked=row.is_blocked,
        role=None if row.role is None else Role(row.role),
    )


async def user_refs(
    db: AsyncSession, workspace_id: UUID, ids: Iterable[UUID]
) -> dict[UUID, UserRef]:
    """``{id: UserRef}`` одним запросом; чужие и неизвестные id пропускаются."""
    wanted = list(set(ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(AppUser.id, AppUser.login)
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(WorkspaceMember.workspace_id == workspace_id, AppUser.id.in_(wanted))
    )
    return {row.id: UserRef(id=row.id, login=row.login) for row in rows}
