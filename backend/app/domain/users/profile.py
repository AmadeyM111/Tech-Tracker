"""Собственный профиль пользователя: имя и фамилия (spec 019: FR-3c, AC-34; plan §4.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from app.core.clock import utcnow
from app.core.errors import ErrorCode, NoRole, Unprocessable
from app.domain.events.catalog import EventAction
from app.domain.events.writer import record_event
from app.domain.users.models import AppUser
from app.domain.users.names import normalize_person_name

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.access.roles import Actor


@dataclass(frozen=True)
class OwnProfile:
    """Имя и фамилия; ``None`` у записей, созданных до появления полей."""

    first_name: str | None
    last_name: str | None


async def _load(db: AsyncSession, actor: Actor) -> OwnProfile:
    row = (
        await db.execute(
            select(AppUser.first_name, AppUser.last_name).where(AppUser.id == actor.user_id)
        )
    ).one()
    return OwnProfile(first_name=row.first_name, last_name=row.last_name)


async def get_own_profile(db: AsyncSession, actor: Actor) -> OwnProfile:
    """Имена текущего пользователя из БД."""
    return await _load(db, actor)


async def set_own_name(
    db: AsyncSession, actor: Actor, first_name: str, last_name: str
) -> OwnProfile:
    """Меняет собственные имя и фамилию (любая роль с сессией).

    Без изменений -- без UPDATE и без события; иначе событие ``user.name_changed`` с
    именами изменённых полей (значения в событие, исключения и логи не попадают).
    """
    if actor.role is None:  # гейт get_active_actor уже отработал; защита от прямого вызова
        raise NoRole()
    first = normalize_person_name(first_name)
    if first is None:
        raise Unprocessable("Недопустимое имя", code=ErrorCode.first_name_invalid)
    last = normalize_person_name(last_name)
    if last is None:
        raise Unprocessable("Недопустимая фамилия", code=ErrorCode.last_name_invalid)
    current = await _load(db, actor)
    changed = [
        field
        for field, old, new in (
            ("first_name", current.first_name, first),
            ("last_name", current.last_name, last),
        )
        if old != new
    ]
    if not changed:
        return current
    await db.execute(
        update(AppUser)
        .where(AppUser.id == actor.user_id)
        .values(first_name=first, last_name=last, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_NAME_CHANGED,
        entity_id=actor.user_id,
        changed_fields=changed,
    )
    return OwnProfile(first_name=first, last_name=last)
