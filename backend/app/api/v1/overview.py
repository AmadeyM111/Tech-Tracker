"""«Сводка»: ``GET /api/v1/me/overview`` и ``/me/overview/{tasks,projects}`` (spec 008).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403.
Одно значение ``status`` и ``due`` (Q-7): повтор параметра — 422, а не «последнее победило».
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.common import ProjectRef
from app.api.v1.schemas.overview import (
    OverviewCountsOut,
    OverviewCsvQuery,
    OverviewProjectList,
    OverviewTaskItem,
    OverviewTaskPage,
    OverviewTaskQuery,
)
from app.core.clock import MOSCOW_TZ, today_msk, utcnow
from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import ErrorCode, Unprocessable
from app.core.pagination import PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.events.catalog import EventAction
from app.domain.events.writer import record_event
from app.domain.overview.export_csv import render_csv
from app.domain.overview.queries import (
    OverviewFilter,
    overview_counts,
    overview_export_rows,
    overview_projects,
    overview_tasks,
)

router = APIRouter(
    prefix="/me/overview",
    tags=["overview"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]
_SINGLE = ("project_id", "status", "due", "needs_review", "page", "page_size")
_SINGLE_CSV = ("project_id", "status", "due", "needs_review")


@router.get("", response_model=OverviewCountsOut)
async def get_overview(db: DbSession, actor: CurrentActor) -> OverviewCountsOut:
    """Плитки «Сводки» по всем моим проектам; фильтров нет (Q-2)."""
    return OverviewCountsOut.model_validate(await overview_counts(db, actor))


@router.get("/projects", response_model=OverviewProjectList)
async def list_overview_projects(db: DbSession, actor: CurrentActor) -> OverviewProjectList:
    """Мои проекты (владелец или участник) для фильтра по проекту, по имени."""
    rows = await overview_projects(db, actor)
    return OverviewProjectList(items=[ProjectRef(id=i, name=n) for i, n in rows])


@router.get("/tasks", response_model=OverviewTaskPage, responses=error_responses(404, 422))
async def list_overview_tasks(
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    query: Annotated[OverviewTaskQuery, Query()],
) -> OverviewTaskPage:
    """Задачи сводки с фильтрами: срок по возрастанию, без срока в конце (FR-5…FR-9)."""
    repeated = [name for name in _SINGLE if len(request.query_params.getlist(name)) > 1]
    if repeated:
        raise Unprocessable(
            f"Параметр задаётся один раз: {', '.join(repeated)}", code=ErrorCode.validation_error
        )
    items, has_next, total = await overview_tasks(
        db,
        actor,
        OverviewFilter(
            project_id=query.project_id,
            status=query.status,
            priorities=frozenset(query.priority),
            due=query.due,
            needs_review=query.needs_review,
        ),
        PageParams(page=query.page, page_size=query.page_size),
        today=today_msk(),
    )
    return OverviewTaskPage(
        items=[OverviewTaskItem.model_validate(i) for i in items],
        page=query.page,
        page_size=query.page_size,
        has_next=has_next,
        total=total,
    )


@router.get(
    "/tasks.csv",
    dependencies=[Depends(require_capability(Capability.EXPORT_OVERVIEW))],
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV выборки «Сводки» (spec 025)"},
        **error_responses(404, 422),
    },
    response_class=Response,
)
async def export_overview_tasks(
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    query: Annotated[OverviewCsvQuery, Query()],
) -> Response:
    """Выборка «Сводки» с фильтрами целиком в CSV; только БА (ADR-0023, FR-1…FR-8)."""
    repeated = [name for name in _SINGLE_CSV if len(request.query_params.getlist(name)) > 1]
    if repeated:
        raise Unprocessable(
            f"Параметр задаётся один раз: {', '.join(repeated)}", code=ErrorCode.validation_error
        )
    settings: Settings = request.app.state.settings
    limit = settings.csv_max_rows
    rows, total = await overview_export_rows(
        db,
        actor,
        OverviewFilter(
            project_id=query.project_id,
            status=query.status,
            priorities=frozenset(query.priority),
            due=query.due,
            needs_review=query.needs_review,
        ),
        today=today_msk(),
        limit=limit,
    )
    if total > limit:
        raise Unprocessable(
            f"В выборке {total} задач, максимум {limit}. Сузьте фильтры",
            code=ErrorCode.export_too_large,
        )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_OVERVIEW_EXPORTED,
        entity_id=actor.user_id,
        details={"rows": str(len(rows))},
    )
    stamp = utcnow().astimezone(MOSCOW_TZ).strftime("%Y%m%d-%H%M")
    return Response(
        content=render_csv(rows, base_url=settings.public_base_url),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gtrack-summary-{stamp}.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
