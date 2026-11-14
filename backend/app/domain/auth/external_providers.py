"""Провайдеры внешнего входа: Яндекс ID, VK ID, Google (spec 029 FR-12…FR-14, FR-21; ADR-0026).

Мы — OAuth 2.0 клиент с PKCE (S256). Модуль строит адрес авторизации и обменивает ``code`` на
идентичность: стабильный идентификатор провайдера, email и признак его подтверждения.
Провайдерские токены живут только внутри ``fetch_identity`` и никуда не сохраняются (FR-21).
Тексты исключений не содержат ответов провайдера, кодов и токенов.

Источники (официальная документация, проверено 2026-11-15):
* Яндекс ID: ``oauth.yandex.ru/authorize``, ``POST oauth.yandex.ru/token`` (с ``code_verifier``
  секрет не обязателен), ``GET login.yandex.ru/info`` (``id``, ``default_email``; признака
  подтверждения email нет).
* VK ID: ``id.vk.ru/authorize``, ``POST id.vk.ru/oauth2/auth`` (``device_id`` из redirect),
  ``POST id.vk.ru/oauth2/user_info`` (``user_id``, ``email``, ``verified``: смысл не раскрыт, не
  используется).
* Google: ``accounts.google.com/o/oauth2/v2/auth``, ``POST oauth2.googleapis.com/token``,
  ``GET openidconnect.googleapis.com/v1/userinfo`` (``sub``, ``email``, ``email_verified``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlencode

import httpx

from app.domain.users.email import normalize_email

if TYPE_CHECKING:
    from app.core.config import Settings

ProviderName = Literal["yandex", "vk", "google"]
PROVIDER_NAMES: Final[tuple[ProviderName, ...]] = ("yandex", "vk", "google")
HTTP_TIMEOUT: Final = 10.0
_MAX_SUBJECT: Final = 255


class ProviderError(Exception):
    """Провайдер недоступен или ответил не так, как ожидалось (текст без данных ответа)."""


@dataclass(frozen=True)
class ProviderConfig:
    name: ProviderName
    client_id: str
    client_secret: str | None = field(default=None, repr=False)

    @property
    def auto_link_by_verified_email(self) -> bool:
        """FR-16: автопривязка по email только у провайдера, подтверждающего адрес (Google)."""
        return self.name == "google"


@dataclass(frozen=True)
class ExternalProfile:
    subject: str = field(repr=False)
    email: str | None = field(repr=False)
    email_verified: bool


def enabled_providers(settings: Settings) -> dict[ProviderName, ProviderConfig]:
    """Провайдеры, у которых включён флаг И задан Client ID (флаг без ключей не включает вход)."""
    found: dict[ProviderName, ProviderConfig] = {}
    if settings.yandex_login and settings.yandex_client_id:
        secret = settings.yandex_client_secret
        found["yandex"] = ProviderConfig(
            "yandex", settings.yandex_client_id, secret.get_secret_value() if secret else None
        )
    if settings.vk_login and settings.vk_client_id:
        found["vk"] = ProviderConfig("vk", settings.vk_client_id)
    if settings.google_login and settings.google_client_id:
        secret = settings.google_client_secret
        found["google"] = ProviderConfig(
            "google", settings.google_client_id, secret.get_secret_value() if secret else None
        )
    return found


def callback_url(base_url: str, provider: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/auth/external/{provider}/callback"


def authorize_url(cfg: ProviderConfig, *, redirect_uri: str, state: str, challenge: str) -> str:
    """Адрес авторизации у провайдера (PKCE S256, ``state``, точный ``redirect_uri``; NFR-2)."""
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if cfg.name == "yandex":
        base = "https://oauth.yandex.ru/authorize"
        params["scope"] = "login:email"
    elif cfg.name == "vk":
        base = "https://id.vk.ru/authorize"
        params["scope"] = "vkid.personal_info email"
    else:
        base = "https://accounts.google.com/o/oauth2/v2/auth"
        params["scope"] = "openid email"
    return f"{base}?{urlencode(params)}"


def _json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise ProviderError("provider http status")
    try:
        data = response.json()
    except ValueError:
        raise ProviderError("provider json") from None
    if not isinstance(data, dict):
        raise ProviderError("provider json shape")
    return data


def _subject(value: object) -> str:
    text = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not text or len(text) > _MAX_SUBJECT:
        raise ProviderError("provider subject")
    return text


def _email(value: object) -> str | None:
    return normalize_email(value) if isinstance(value, str) else None


async def fetch_identity(
    client: httpx.AsyncClient,
    cfg: ProviderConfig,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    device_id: str | None = None,
    state: str | None = None,
) -> ExternalProfile:
    """Обменивает ``code`` на токен и читает идентичность; токен после этого отбрасывается."""
    try:
        if cfg.name == "yandex":
            return await _yandex(client, cfg, code, verifier)
        if cfg.name == "vk":
            return await _vk(client, cfg, code, verifier, redirect_uri, device_id, state)
        return await _google(client, cfg, code, verifier, redirect_uri)
    except httpx.HTTPError:
        raise ProviderError("provider transport") from None


async def _yandex(
    client: httpx.AsyncClient, cfg: ProviderConfig, code: str, verifier: str
) -> ExternalProfile:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": cfg.client_id,
        "code_verifier": verifier,
    }
    if cfg.client_secret:
        form["client_secret"] = cfg.client_secret
    token = _json(await client.post("https://oauth.yandex.ru/token", data=form)).get("access_token")
    if not isinstance(token, str) or not token:
        raise ProviderError("provider token")
    info = _json(
        await client.get(
            "https://login.yandex.ru/info",
            params={"format": "json"},
            headers={"Authorization": f"OAuth {token}"},
        )
    )
    return ExternalProfile(
        subject=_subject(info.get("id")),
        email=_email(info.get("default_email")),
        email_verified=False,
    )


async def _vk(
    client: httpx.AsyncClient,
    cfg: ProviderConfig,
    code: str,
    verifier: str,
    redirect_uri: str,
    device_id: str | None,
    state: str | None,
) -> ExternalProfile:
    if not device_id or not state:
        raise ProviderError("provider device_id")
    tokens = _json(
        await client.post(
            "https://id.vk.ru/oauth2/auth",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": cfg.client_id,
                "device_id": device_id,
                "redirect_uri": redirect_uri,
                "state": state,
            },
        )
    )
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        raise ProviderError("provider token")
    info = _json(
        await client.post(
            "https://id.vk.ru/oauth2/user_info",
            data={"client_id": cfg.client_id, "access_token": token},
        )
    )
    user = info.get("user")
    if not isinstance(user, dict):
        raise ProviderError("provider user")
    return ExternalProfile(
        subject=_subject(user.get("user_id")),
        email=_email(user.get("email")),
        email_verified=False,  # смысл поля ``verified`` в документации VK ID не раскрыт
    )


async def _google(
    client: httpx.AsyncClient, cfg: ProviderConfig, code: str, verifier: str, redirect_uri: str
) -> ExternalProfile:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": cfg.client_id,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    }
    if cfg.client_secret:
        form["client_secret"] = cfg.client_secret
    token = _json(await client.post("https://oauth2.googleapis.com/token", data=form)).get(
        "access_token"
    )
    if not isinstance(token, str) or not token:
        raise ProviderError("provider token")
    info = _json(
        await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
    )
    verified = info.get("email_verified")
    return ExternalProfile(
        subject=_subject(info.get("sub")),
        email=_email(info.get("email")),
        email_verified=verified is True or verified == "true",
    )
