"""Раздел «Система» ТА: ``GET /api/v1/admin/system/backup`` (spec 009 FR-6, plan PB-7).

Гейт — router-level ``require_capability(MANAGE_ACCOUNTS)``: БА и пользователь получают 403,
без сессии — 401. Ответ — только метаданные копий; путей и содержимого нет.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.admin_system import BackupStatusOut
from app.core.clock import utcnow
from app.core.db import DbSession
from app.domain.access.roles import Capability
from app.domain.ops.backup_status import backup_status

router = APIRouter(
    prefix="/admin/system",
    tags=["admin-system"],
    dependencies=[Depends(require_capability(Capability.MANAGE_ACCOUNTS))],
    responses=error_responses(401, 403),
)


@router.get("/backup", response_model=BackupStatusOut)
async def get_backup_status(request: Request, db: DbSession) -> BackupStatusOut:
    """Состояние резервных копий: ``stale`` — нет копий, старше порога или последний сбой."""
    status = await backup_status(
        db, now=utcnow(), stale_hours=request.app.state.settings.backup_stale_hours
    )
    return BackupStatusOut.model_validate(status)
