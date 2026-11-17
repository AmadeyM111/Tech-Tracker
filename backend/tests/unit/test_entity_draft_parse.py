"""Разбор текста propose_entities без БД."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.core.errors import Unprocessable
from app.domain.tasks.entity_draft import parse_entities

PID = UUID("11111111-1111-4111-8111-111111111111")


def test_json_array() -> None:
    items = parse_entities(f'[{{"type":"task","title":"A","project_id":"{PID}"}}]')
    assert items[0].type == "task"
    assert items[0].title == "A"
    assert items[0].project_id == PID


def test_line_format() -> None:
    items = parse_entities("task: Первая\nincident: Вторая\nnote: Третья")
    assert [i.type for i in items] == ["task", "incident", "note"]
    assert [i.title for i in items] == ["Первая", "Вторая", "Третья"]


def test_empty_and_garbage_fail() -> None:
    with pytest.raises(Unprocessable) as empty:
        parse_entities("   ")
    assert empty.value.code == "entity_parse_error"
    with pytest.raises(Unprocessable) as garbage:
        parse_entities("hello")
    assert garbage.value.code == "entity_parse_error"
