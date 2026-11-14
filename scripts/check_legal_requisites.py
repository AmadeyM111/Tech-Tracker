#!/usr/bin/env python3
"""Проверка реквизитов в юридических текстах перед включением PDN_CONSENT_ENABLED (спека 021, FR-9).

Код 0 — заглушек ``[ЗАПОЛНИТЬ]`` нет; код 1 — остались. Абзацы с пометкой «предложение,
подтвердить у юриста» дают предупреждение и на код не влияют.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.domain.legal import documents  # noqa: E402


def main() -> int:
    left = documents.unfilled_placeholders()
    proposals = documents.proposal_count()
    if proposals:
        print(f"Предупреждение: абзацев с пометкой «предложение»: {proposals}")
    if left:
        print("Не заполнено [ЗАПОЛНИТЬ]: " + ", ".join(left))
        return 1
    print("Реквизиты заполнены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
