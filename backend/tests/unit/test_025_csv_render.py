"""C25-T02: формирование CSV «Сводки» (spec 025 AC-4, AC-5, AC-6, AC-12) без БД."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.domain.overview.export_csv import HEADER, ExportRow, escape_cell, render_csv

TID = UUID("11111111-1111-4111-8111-111111111111")


def _row(**over: object) -> ExportRow:
    base: dict[str, object] = {
        "task_id": TID,
        "project": "Магазин",
        "title": "Сверить остатки",
        "status": "review",
        "priority": "high",
        "assignee": "demo.ba1",
        "due_date": date(2026, 11, 9),
        "created_at": datetime(2026, 11, 1, 6, 5, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 9, 21, 30, tzinfo=UTC),
    }
    base.update(over)
    return ExportRow(**base)  # type: ignore[arg-type]


def _parse(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


def test_025_ac4_bom_semicolon_crlf_quotes_and_roundtrip() -> None:
    title = 'Проверить "цену"; и\nперенос'
    data = render_csv([_row(title=title)], base_url=None)
    assert data.startswith(b"\xef\xbb\xbf")
    assert (
        data.count(b"\r\n") == 2
    )  # конец заголовка и конец строки данных; \n внутри поля — как есть
    rows = _parse(data)
    assert rows[0] == list(HEADER)
    assert rows[1][1] == title
    assert rows[1][0] == "Магазин"
    assert '"Проверить ""цену""' in data.decode("utf-8")


def test_025_ac5_dates_and_labels_in_moscow_time() -> None:
    row = _parse(render_csv([_row()], base_url="https://gt.example/"))[1]
    assert row[2:6] == ["На проверке", "Высокий", "demo.ba1", "09.11.2026"]
    assert row[6] == "01.11.2026 09:05"
    assert row[7] == "10.11.2026 00:30"  # 21:30Z -> 00:30 МСК следующего дня
    assert row[8] == f"https://gt.example/tasks/{TID}"


def test_025_empty_assignee_due_and_link() -> None:
    row = _parse(render_csv([_row(assignee=None, due_date=None)], base_url=None))[1]
    assert row[4] == "" and row[5] == ""


@pytest.mark.parametrize("base_url", [None, ""])
def test_025_link_is_relative_without_public_base_url(base_url: str | None) -> None:
    """Дизайн-проверка #35: без PUBLIC_BASE_URL в «Ссылке» путь ``/tasks/<id>``, не пусто."""
    row = _parse(render_csv([_row()], base_url=base_url))[1]
    assert row[8] == f"/tasks/{TID}"


@pytest.mark.parametrize("base_url", ["https://gt.example", "https://gt.example/"])
def test_025_link_is_absolute_with_public_base_url(base_url: str) -> None:
    row = _parse(render_csv([_row()], base_url=base_url))[1]
    assert row[8] == f"https://gt.example/tasks/{TID}"


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_025_ac6_formula_cells_get_leading_apostrophe(value: str) -> None:
    assert escape_cell(value) == "'" + value
    row = _parse(render_csv([_row(title=value, project=value, assignee=value)], base_url=None))[1]
    assert row[0].startswith("'") and row[1].startswith("'") and row[4].startswith("'")


def test_025_ac6_plain_text_is_untouched() -> None:
    assert escape_cell("Обычный текст = 1") == "Обычный текст = 1"
    assert escape_cell("") == ""


def test_025_ac12_empty_selection_has_only_header() -> None:
    data = render_csv([], base_url=None)
    assert _parse(data) == [list(HEADER)]
    assert data.endswith(b"\r\n")
