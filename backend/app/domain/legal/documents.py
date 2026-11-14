"""Загрузка текстов Политики и Согласия и реквизитов оператора (спека 021, FR-1, FR-9).

Тексты лежат в ``documents/{privacy,consent}.json``, реквизиты — в ``documents/requisites.json``
(единственное место). В текстах подстановки ``{operator_name}``, ``{operator_ogrn}``,
``{operator_inn}``, ``{operator_address}``, ``{contact_email}``, ``{site_url}``. Версия — дата
``ГГГГ-ММ-ДД``; у обоих документов она одна (``CURRENT_VERSION``). Модуль читает файлы один раз.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, cast

DOCUMENTS_DIR: Final = Path(__file__).parent / "documents"
PLACEHOLDER: Final = "[ЗАПОЛНИТЬ]"
PROPOSAL_MARK: Final = "[предложение, подтвердить у юриста]"
Kind = Literal["privacy", "consent"]
KINDS: Final[tuple[Kind, ...]] = ("privacy", "consent")
_VERSION_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_SLOT_RE: Final = re.compile(r"\{([a-z_]+)\}")
_REQUISITE_KEYS: Final = (
    "operator_name",
    "operator_ogrn",
    "operator_inn",
    "operator_address",
    "contact_email",
    "site_url",
)


@dataclass(frozen=True)
class Section:
    heading: str | None
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    kind: Kind
    title: str
    version: str
    sections: tuple[Section, ...]


def _read(name: str) -> dict[str, object]:
    raw = json.loads((DOCUMENTS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{name}.json: ожидается объект")
    return cast("dict[str, object]", raw)


@lru_cache
def requisites() -> dict[str, str]:
    raw = _read("requisites")
    missing = [key for key in _REQUISITE_KEYS if not isinstance(raw.get(key), str)]
    if missing:
        raise ValueError(f"requisites.json: нет полей {missing}")
    return {key: str(raw[key]) for key in _REQUISITE_KEYS}


def _fill(text: str, values: dict[str, str]) -> str:
    def slot(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"в тексте неизвестная подстановка {{{key}}}")
        return values[key]

    return _SLOT_RE.sub(slot, text)


@lru_cache
def load(kind: Kind) -> Document:
    """Документ с подставленными реквизитами. Fail Fast при неверной версии или подстановке."""
    raw = _read(kind)
    version = raw.get("version")
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"{kind}.json: версия должна быть датой ГГГГ-ММ-ДД")
    values = requisites()
    sections_raw = cast("list[dict[str, object]]", raw["sections"])
    sections = tuple(
        Section(
            heading=None if s["heading"] is None else _fill(str(s["heading"]), values),
            paragraphs=tuple(_fill(str(p), values) for p in cast("list[object]", s["paragraphs"])),
        )
        for s in sections_raw
    )
    return Document(kind=kind, title=str(raw["title"]), version=version, sections=sections)


@lru_cache
def current_version() -> str:
    """Версия набора документов; Политика и Согласие обязаны совпадать (FR-1)."""
    versions = {load(kind).version for kind in KINDS}
    if len(versions) != 1:
        raise ValueError(f"версии Политики и Согласия различаются: {sorted(versions)}")
    return versions.pop()


def unfilled_placeholders() -> list[str]:
    """Места, где остался ``[ЗАПОЛНИТЬ]``: поля реквизитов и документы (FR-9)."""
    found = [f"requisites.{key}" for key, value in requisites().items() if PLACEHOLDER in value]
    for kind in KINDS:
        document = load(kind)
        texts = [p for s in document.sections for p in s.paragraphs]
        texts += [s.heading for s in document.sections if s.heading is not None]
        if any(PLACEHOLDER in text for text in texts):
            found.append(f"{kind}.json")
    return found


def proposal_count() -> int:
    """Число абзацев с пометкой «предложение, подтвердить у юриста» (предупреждение)."""
    return sum(
        PROPOSAL_MARK in p for kind in KINDS for s in load(kind).sections for p in s.paragraphs
    )
