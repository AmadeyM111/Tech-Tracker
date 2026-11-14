"""Публичные юридические тексты и принятие согласия на обработку ПДн (спека 021, FR-2, FR-5)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_actor
from app.api.openapi import error_response, error_responses
from app.api.v1.schemas.legal import LegalDocument, LegalSection, LegalStatus, PdnConsentAccept
from app.core.clock import utcnow
from app.core.db import DbSession
from app.core.errors import FeatureDisabled
from app.domain.access.roles import Actor
from app.domain.legal import consent as consent_domain
from app.domain.legal import documents

router = APIRouter(tags=["legal"])


def _enabled(request: Request) -> bool:
    enabled: bool = request.app.state.settings.pdn_consent_enabled
    return enabled


@router.get("/legal", response_model=LegalStatus)
async def legal_status(request: Request) -> LegalStatus:
    """Публично: включена ли функция согласия и версия текстов (для флажка и экрана)."""
    return LegalStatus(enabled=_enabled(request), version=documents.current_version())


@router.get(
    "/legal/{kind}",
    response_model=LegalDocument,
    responses={
        **error_response(404, "Функция отключена (code: feature_disabled)"),
        **error_responses(422),
    },
)
async def legal_document(kind: Literal["privacy", "consent"], request: Request) -> LegalDocument:
    """Публично, без входа: Политика (``privacy``) или Согласие (``consent``)."""
    if not _enabled(request):
        raise FeatureDisabled()
    doc = documents.load(kind)
    return LegalDocument(
        kind=doc.kind,
        title=doc.title,
        version=doc.version,
        effective_date=doc.version,
        sections=[
            LegalSection(heading=s.heading, paragraphs=list(s.paragraphs)) for s in doc.sections
        ],
    )


@router.post(
    "/me/pdn-consent",
    status_code=204,
    response_class=Response,
    responses=error_responses(400, 401, 403, 422),
)
async def accept_pdn_consent(
    body: PdnConsentAccept,
    db: DbSession,
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Принятие согласия текущей версии (204).

    ``get_actor``, а не ``get_active_actor``: маршрут доступен именно тому, кого гейт
    ``pdn_consent_pending`` не пускает дальше (как выход и смена пароля).
    """
    version = consent_domain.check_form(body.pdn_consent, body.pdn_consent_version)
    await consent_domain.accept(
        db, user_id=actor.user_id, workspace_id=actor.workspace_id, version=version, now=utcnow()
    )
    return Response(status_code=204)
