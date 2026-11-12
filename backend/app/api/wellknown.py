"""Метаданные OAuth: ``/.well-known/*`` (RFC 9728, RFC 8414; spec 028 FR-1, FR-2).

Адреса строятся только из ``PUBLIC_BASE_URL``: за nginx и Caddy схема и ``Host`` запроса не
годятся. Без ``PUBLIC_BASE_URL`` (или с не-https) функция выключена: 404 ``feature_disabled``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.core.errors import FeatureDisabled
from app.domain.oauth.service import SCOPES_SUPPORTED, canonical_resource, issuer

router = APIRouter(tags=["oauth-metadata"], include_in_schema=False)
_NO_STORE = {"Cache-Control": "no-store"}


def oauth_base_url(settings: Settings) -> str | None:
    """``PUBLIC_BASE_URL``, если он годится для OAuth (https), иначе ``None``."""
    base = settings.public_base_url
    return base.rstrip("/") if base and base.lower().startswith("https://") else None


def require_base_url(request: Request) -> str:
    base = oauth_base_url(request.app.state.settings)
    if base is None:
        raise FeatureDisabled()
    return base


def protected_resource_metadata(base: str) -> dict[str, Any]:
    return {
        "resource": canonical_resource(base),
        "authorization_servers": [issuer(base)],
        "scopes_supported": list(SCOPES_SUPPORTED),
        "bearer_methods_supported": ["header"],
    }


def authorization_server_metadata(base: str) -> dict[str, Any]:
    return {
        "issuer": issuer(base),
        "authorization_endpoint": f"{issuer(base)}/oauth/authorize",
        "token_endpoint": f"{issuer(base)}/api/v1/oauth/token",
        "registration_endpoint": f"{issuer(base)}/api/v1/oauth/register",
        "revocation_endpoint": f"{issuer(base)}/api/v1/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": list(SCOPES_SUPPORTED),
        "authorization_response_iss_parameter_supported": True,
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource(request: Request) -> JSONResponse:
    return JSONResponse(protected_resource_metadata(require_base_url(request)), headers=_NO_STORE)


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
async def authorization_server(request: Request) -> JSONResponse:
    return JSONResponse(authorization_server_metadata(require_base_url(request)), headers=_NO_STORE)
