"""Доска и перенос карточки: ``GET /projects/{id}/board``, ``POST /tasks/{id}/move`` (plan §11.4).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403.
Порядок ошибок: гейты -> 422 схемы -> 404 -> 403 -> 422 домена; объектные права проверяет
домен (``app.domain.boards``, ``app.domain.tasks.service.move``). 503 ``service_busy`` с
``Retry-After`` отдаёт общий обработчик ошибок. Транзакцию фиксирует ``DbSession``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.boards import Board, TaskMove
from app.core.db import DbSession
from app.domain.access.roles import Actor, Capability
from app.domain.boards import service as boards
from app.domain.tasks import service as tasks

router = APIRouter(
    tags=["boards"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get(
    "/projects/{project_id}/board",
    response_model=Board,
    responses=error_responses(404, 422),
)
async def get_board(project_id: UUID, db: DbSession, actor: CurrentActor) -> Board:
    """Доска: 4 колонки со всеми карточками задач верхнего уровня, без пагинации (FR-47)."""
    return Board.model_validate(await boards.get_board(db, actor, project_id))


@router.post(
    "/tasks/{task_id}/move",
    status_code=204,
    response_class=Response,
    responses=error_responses(400, 404, 422),
)
async def move_task(task_id: UUID, body: TaskMove, db: DbSession, actor: CurrentActor) -> Response:
    """Переносит карточку в колонку между соседями; позиция считается на сервере (FR-28a)."""
    await tasks.move(
        db,
        actor,
        task_id,
        status=body.status,
        before_task_id=body.before_task_id,
        after_task_id=body.after_task_id,
    )
    return Response(status_code=204)
