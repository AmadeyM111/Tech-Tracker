"""Чтение и запись knowledge_record (спека 037, CD-08, CD-09)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import can_read_project_content
from app.domain.access.roles import Actor, Capability, Role
from app.domain.events.client_context import current_client_name
from app.domain.knowledge.models import KnowledgeRecord
from app.domain.projects.models import Project, ProjectMember
from app.domain.projects.queries import load_project_facts

TITLE_MAX = 255
BODY_MAX = 10_000
WITH_MAX = 255
KINDS = frozenset({"decision", "reason", "agreement"})
SCOPES = frozenset({"space", "project"})


@dataclass(frozen=True)
class KnowledgeView:
    id: UUID
    scope: str
    project_id: UUID | None
    type: str
    title: str
    body: str
    confirmed_with: str | None
    confirmed_by: UUID
    client_name: str | None
    created_at: datetime


def _unstructured(detail: str) -> Unprocessable:
    return Unprocessable(detail, code=ErrorCode.knowledge_unstructured)


def _view(row: KnowledgeRecord) -> KnowledgeView:
    return KnowledgeView(
        id=row.id,
        scope=row.scope,
        project_id=row.project_id,
        type=row.kind,
        title=row.title,
        body=row.body,
        confirmed_with=row.confirmed_with,
        confirmed_by=row.confirmed_by,
        client_name=row.client_name,
        created_at=row.created_at,
    )


def as_dict(view: KnowledgeView) -> dict[str, Any]:
    return {
        "id": str(view.id),
        "scope": view.scope,
        "project_id": None if view.project_id is None else str(view.project_id),
        "type": view.type,
        "title": view.title,
        "body": view.body,
        "confirmed_with": view.confirmed_with,
        "confirmed_by": str(view.confirmed_by),
        "client_name": view.client_name,
        "created_at": view.created_at.isoformat().replace("+00:00", "Z"),
    }


def _member_of_any_project(actor: Actor) -> ColumnElement[bool]:
    return exists().where(
        ProjectMember.user_id == actor.user_id,
        ProjectMember.workspace_id == actor.workspace_id,
        Project.id == ProjectMember.project_id,
        Project.workspace_id == actor.workspace_id,
        Project.deleted_at.is_(None),
    )


async def _can_read_space(db: AsyncSession, actor: Actor) -> bool:
    if not actor.can(Capability.BUSINESS_ACCESS):
        return False
    if actor.role is Role.BUSINESS_ADMIN:
        return True
    return bool(await db.scalar(select(_member_of_any_project(actor))))


def _can_write_space(actor: Actor) -> bool:
    return actor.can(Capability.BUSINESS_ACCESS) and actor.role is Role.BUSINESS_ADMIN


async def _require_project_read(db: AsyncSession, actor: Actor, project_id: UUID) -> None:
    facts = await load_project_facts(db, actor, project_id)
    if not can_read_project_content(actor, facts):
        raise Forbidden()


async def _require_project_write(db: AsyncSession, actor: Actor, project_id: UUID) -> None:
    await _require_project_read(db, actor, project_id)


def parse_upsert(
    *,
    scope: str | None,
    project_id: UUID | None,
    kind: str | None,
    title: str | None,
    body: str | None,
    confirmed_with: str | None,
) -> tuple[str, UUID | None, str, str, str, str | None]:
    """Проверяет поля записи; мусор и пересказ — ``knowledge_unstructured``."""
    if scope not in SCOPES:
        raise _unstructured("scope: space или project")
    if kind not in KINDS:
        raise _unstructured("type: decision, reason или agreement")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > TITLE_MAX:
        raise _unstructured("title: что решили, строка 1–255")
    if not isinstance(body, str) or not body.strip() or len(body.strip()) > BODY_MAX:
        raise _unstructured("body: почему, строка 1–10000")
    title_s, body_s = title.strip(), body.strip()
    with_s: str | None
    if kind == "agreement":
        if (
            not isinstance(confirmed_with, str)
            or not confirmed_with.strip()
            or len(confirmed_with.strip()) > WITH_MAX
        ):
            raise _unstructured("confirmed_with: с кем, строка 1–255")
        with_s = confirmed_with.strip()
    else:
        if confirmed_with is not None and str(confirmed_with).strip():
            raise _unstructured("confirmed_with только для agreement")
        with_s = None
    if scope == "space":
        if project_id is not None:
            raise _unstructured("project_id только для scope=project")
        return scope, None, kind, title_s, body_s, with_s
    if project_id is None:
        raise _unstructured("project_id обязателен для scope=project")
    return scope, project_id, kind, title_s, body_s, with_s


async def upsert_knowledge(
    db: AsyncSession,
    actor: Actor,
    *,
    scope: str | None,
    project_id: UUID | None,
    kind: str | None,
    title: str | None,
    body: str | None,
    confirmed_with: str | None,
    commit: bool,
    knowledge_id: UUID | None,
) -> dict[str, Any]:
    parsed = parse_upsert(
        scope=scope,
        project_id=project_id,
        kind=kind,
        title=title,
        body=body,
        confirmed_with=confirmed_with,
    )
    p_scope, p_project, p_kind, p_title, p_body, p_with = parsed
    if p_scope == "space":
        if not _can_write_space(actor):
            raise Forbidden()
    else:
        assert p_project is not None
        await _require_project_write(db, actor, p_project)
    draft = {
        "scope": p_scope,
        "project_id": None if p_project is None else str(p_project),
        "type": p_kind,
        "title": p_title,
        "body": p_body,
        "confirmed_with": p_with,
        "knowledge_id": None if knowledge_id is None else str(knowledge_id),
    }
    if not commit:
        return {"committed": False, "draft": draft, "record": None}
    client = current_client_name()
    if knowledge_id is None:
        row = KnowledgeRecord(
            workspace_id=actor.workspace_id,
            scope=p_scope,
            project_id=p_project,
            kind=p_kind,
            title=p_title,
            body=p_body,
            confirmed_with=p_with,
            confirmed_by=actor.user_id,
            created_by=actor.user_id,
            client_name=client,
        )
        db.add(row)
        await db.flush()
        return {"committed": True, "draft": draft, "record": as_dict(_view(row))}
    existing = await db.get(KnowledgeRecord, knowledge_id)
    if existing is None or existing.workspace_id != actor.workspace_id:
        raise NotFound("Запись не найдена")
    if existing.scope == "space":
        if not _can_write_space(actor):
            raise Forbidden()
    else:
        assert existing.project_id is not None
        await _require_project_write(db, actor, existing.project_id)
    existing.scope = p_scope
    existing.project_id = p_project
    existing.kind = p_kind
    existing.title = p_title
    existing.body = p_body
    existing.confirmed_with = p_with
    existing.confirmed_by = actor.user_id
    existing.client_name = client
    await db.flush()
    return {"committed": True, "draft": draft, "record": as_dict(_view(existing))}


def _visible_stmt(actor: Actor, *, include_space: bool) -> Select[KnowledgeRecord]:
    member = exists().where(
        ProjectMember.project_id == KnowledgeRecord.project_id,
        ProjectMember.user_id == actor.user_id,
        ProjectMember.workspace_id == actor.workspace_id,
    )
    owner = exists().where(
        Project.id == KnowledgeRecord.project_id,
        Project.owner_id == actor.user_id,
        Project.workspace_id == actor.workspace_id,
        Project.deleted_at.is_(None),
    )
    project_ok = (KnowledgeRecord.scope == "project") & or_(member, owner)
    space_ok = KnowledgeRecord.scope == "space" if include_space else false()
    return (
        select(KnowledgeRecord)
        .where(
            KnowledgeRecord.workspace_id == actor.workspace_id,
            or_(space_ok, project_ok),
        )
        .order_by(KnowledgeRecord.created_at.desc(), KnowledgeRecord.id.desc())
    )


async def list_knowledge(
    db: AsyncSession,
    actor: Actor,
    params: PageParams,
    *,
    scope: Literal["space", "project"] | None,
    project_id: UUID | None,
) -> tuple[list[KnowledgeView], bool]:
    if not actor.can(Capability.BUSINESS_ACCESS):
        raise Forbidden()
    stmt = _visible_stmt(actor, include_space=True)
    if project_id is not None:
        await _require_project_read(db, actor, project_id)
        if scope == "space":
            stmt = stmt.where(KnowledgeRecord.scope == "space")
        elif scope == "project":
            stmt = stmt.where(
                KnowledgeRecord.scope == "project",
                KnowledgeRecord.project_id == project_id,
            )
        else:
            stmt = stmt.where(
                or_(
                    KnowledgeRecord.scope == "space",
                    (KnowledgeRecord.scope == "project")
                    & (KnowledgeRecord.project_id == project_id),
                )
            )
    else:
        if scope == "space":
            if not await _can_read_space(db, actor):
                raise Forbidden()
            stmt = stmt.where(KnowledgeRecord.scope == "space")
        elif scope == "project":
            stmt = _visible_stmt(actor, include_space=False)
        else:
            if not await _can_read_space(db, actor):
                stmt = _visible_stmt(actor, include_space=False)
    rows, has_next = await paginate(db, stmt, params)
    return [_view(row) for row in rows], has_next


async def get_knowledge(db: AsyncSession, actor: Actor, knowledge_id: UUID) -> KnowledgeView:
    if not actor.can(Capability.BUSINESS_ACCESS):
        raise Forbidden()
    row = await db.get(KnowledgeRecord, knowledge_id)
    if row is None or row.workspace_id != actor.workspace_id:
        raise NotFound("Запись не найдена")
    if row.scope == "space":
        if not await _can_read_space(db, actor):
            raise Forbidden()
        return _view(row)
    assert row.project_id is not None
    await _require_project_read(db, actor, row.project_id)
    return _view(row)
