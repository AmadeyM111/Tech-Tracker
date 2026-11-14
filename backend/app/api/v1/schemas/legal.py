"""Схемы публичных текстов и принятия согласия на обработку ПДн (спека 021, §4)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class LegalStatus(BaseModel):
    """``GET /legal``: включена ли функция и текущая версия текстов."""

    enabled: bool
    version: str


class LegalSection(BaseModel):
    heading: str | None
    paragraphs: list[str]


class LegalDocument(BaseModel):
    """``GET /legal/{kind}``: текст с подставленными реквизитами оператора."""

    kind: str
    title: str
    version: str
    effective_date: str
    sections: list[LegalSection]


class PdnConsentAccept(BaseModel):
    """``POST /me/pdn-consent``: подтверждение согласия существующим пользователем."""

    model_config = ConfigDict(extra="forbid")

    pdn_consent: bool
    pdn_consent_version: Annotated[str, Field(max_length=32)]
