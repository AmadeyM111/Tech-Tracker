"""Согласие на обработку ПДн: проверка формы и запись факта (спека 021, FR-3, FR-5, FR-7).

Версия — дата текста (``documents.current_version``). Проверка формы одна для регистрации по
email, старта входа через провайдера и экрана подтверждения. Значений ПДн модуль не пишет:
в аудит попадает только версия текста (NFR-1).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import update

from app.core.errors import ErrorCode, Unprocessable
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.legal.documents import current_version
from app.domain.users.models import AppUser

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def check_form(consent: bool, version: str | None) -> str:
    """Флажок отмечен и версия текущая, иначе 422. Возвращает версию для записи."""
    if not consent:
        raise Unprocessable(
            "Необходимо согласие на обработку персональных данных",
            code=ErrorCode.pdn_consent_required,
        )
    if version != current_version():
        raise Unprocessable(
            "Текст согласия обновился, обновите страницу",
            code=ErrorCode.pdn_consent_version_mismatch,
        )
    return current_version()


async def accept(
    db: AsyncSession, *, user_id: UUID, workspace_id: UUID, version: str, now: datetime
) -> None:
    """Фиксирует согласие существующего пользователя и пишет событие (FR-5, FR-7)."""
    await db.execute(
        update(AppUser)
        .where(AppUser.id == user_id)
        .values(pdn_consent_version=version, pdn_consented_at=now)
    )
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=user_id,
        action=EventAction.USER_PDN_CONSENT_GIVEN,
        entity_id=user_id,
        details=UserEventDetails(version=version),
    )
