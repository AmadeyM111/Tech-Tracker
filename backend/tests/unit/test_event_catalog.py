"""T30: каталог событий R1.1 (plan D-41, §4.4, §10.5; FR-41, BR-2, AC-65).

Таблица ``EXPECTED`` — дословная копия plan §10.5. Имена членов ``EventAction`` контрактом
не заданы: действия сопоставляются по значениям.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from app.domain.events.catalog import EVENT_CATALOG, EntityType, EventAction, EventSpec

USER_ACTIONS = {
    "user.created",
    "user.blocked",
    "user.unblocked",
    "user.password_reset",
    "user.sessions_revoked",
    "user.role_assigned",
    "user.role_changed",
    "user.role_removed",
}

F = frozenset
# action -> (entity_type, feed, in_audit, fields, value_fields)
EXPECTED: dict[str, tuple[str, str | None, bool, frozenset[str], frozenset[str]]] = {
    "project.updated": ("project", "project", False, F({"name", "description"}), F()),
    "project.ownership_transferred": (
        "project",
        "project",
        True,
        F({"owner_id"}),
        F({"owner_id"}),
    ),
    "project.archived": ("project", "project", True, F({"status"}), F()),
    "project.unarchived": ("project", "project", True, F({"status"}), F()),
    "member.added": ("user", "project", False, F(), F()),
    "member.removed": ("user", "project", False, F(), F()),
    "task.created": ("task", "project", False, F(), F()),
    "task.deleted": ("task", "project", False, F(), F()),
    "task.restored": ("task", "project", False, F(), F()),
    "task.updated": (
        "task",
        "project",
        False,
        F({"status", "assignee_id", "due_date", "title", "description"}),
        F({"status", "assignee_id", "due_date"}),
    ),
    "task.unassigned_member_removed": (
        "task",
        "project",
        False,
        F({"assignee_id"}),
        F({"assignee_id"}),
    ),
    "comment.created": ("comment", "project", False, F(), F()),
    "comment.deleted": ("comment", "project", False, F(), F()),
    "attachment.created": ("attachment", "project", False, F(), F()),
    "attachment.deleted": ("attachment", "project", False, F(), F()),
}

FORBIDDEN_FIELD_NAMES = {
    "title",
    "description",
    "body",
    "text",
    "name",
    "filename",
    "content",
    "comment",
}
# title/description/name входят в таблицу §10.5 как ИМЕНА изменённых полей (changed_fields);
# запрет относится к value_fields (значения) и к именам, не перечисленным в таблице.
ALLOWED_IN_FIELDS_BY_PLAN = {"title", "description", "name"}


def _spec(action: str) -> EventSpec:
    return EVENT_CATALOG[EventAction(action)]


def test_fr41_catalog_has_all_r11_actions_and_user_actions_only() -> None:
    assert {m.value for m in EventAction} == USER_ACTIONS | set(EXPECTED)
    assert {a.value for a in EVENT_CATALOG} == USER_ACTIONS | set(EXPECTED)


@pytest.mark.parametrize("action", sorted(EXPECTED))
def test_fr41_r11_catalog_entry_matches_plan_table(action: str) -> None:
    entity, feed, in_audit, fields, value_fields = EXPECTED[action]
    spec = _spec(action)
    assert spec.entity_type == EntityType(entity)
    assert spec.feed == feed
    assert spec.audit is in_audit
    assert spec.deal_history is False
    assert spec.fields == fields
    assert spec.value_fields == value_fields


@pytest.mark.parametrize("action", sorted(USER_ACTIONS))
def test_t30_user_actions_unchanged(action: str) -> None:
    spec = _spec(action)
    assert spec.entity_type == EntityType.USER
    assert spec.audit is True
    assert spec.feed is None
    assert spec.deal_history is False
    assert spec.fields == frozenset()
    assert spec.value_fields == frozenset()


def test_t30_event_spec_has_frozenset_fields_and_defaults() -> None:
    names = [f.name for f in dataclasses.fields(EventSpec)]
    assert names[:4] == ["entity_type", "audit", "feed", "deal_history"]
    assert "fields" in names
    assert "value_fields" in names
    bare = EventSpec(entity_type=EntityType.USER, audit=True, feed=None, deal_history=False)
    assert bare.fields == frozenset()
    assert bare.value_fields == frozenset()
    for spec in EVENT_CATALOG.values():
        assert isinstance(spec.fields, frozenset)
        assert isinstance(spec.value_fields, frozenset)
        assert all(isinstance(n, str) for n in spec.fields | spec.value_fields)


def test_t30_event_spec_remains_frozen() -> None:
    spec = _spec("task.updated")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(spec, "fields", frozenset({"x"}))  # noqa: B010


def test_t30_value_fields_are_subset_of_fields() -> None:
    for action, spec in EVENT_CATALOG.items():
        assert spec.value_fields <= spec.fields, action


def test_br2_no_business_value_names_in_fields_beyond_plan() -> None:
    """BR-2: имена полей с текстовыми бизнес-значениями допустимы только как в §10.5.

    ``changes`` (значения) не должен содержать ни одного запрещённого имени вообще.
    """
    for action, spec in EVENT_CATALOG.items():
        assert not (spec.value_fields & FORBIDDEN_FIELD_NAMES), action
        extra = (spec.fields & FORBIDDEN_FIELD_NAMES) - ALLOWED_IN_FIELDS_BY_PLAN
        assert not extra, (action, extra)
    # запрещённые имена вне §10.5 не просачиваются в changed_fields других действий
    for action, spec in EVENT_CATALOG.items():
        if action.value in EXPECTED and EXPECTED[action.value][3]:
            continue
        assert not (spec.fields & FORBIDDEN_FIELD_NAMES), action


def test_br2_text_fields_never_have_values_recorded() -> None:
    for action in ("task.updated", "project.updated"):
        spec = _spec(action)
        assert {"title", "description", "name"} & spec.fields
        assert not ({"title", "description", "name"} & spec.value_fields)


def test_t30_in_audit_matches_plan() -> None:
    audited = {a.value for a, s in EVENT_CATALOG.items() if s.audit}
    expected = USER_ACTIONS | {
        "project.ownership_transferred",
        "project.archived",
        "project.unarchived",
    }
    assert audited == expected


def test_t30_project_feed_actions_are_exactly_the_r11_non_user_set() -> None:
    feed_project: Any = {a.value for a, s in EVENT_CATALOG.items() if s.feed == "project"}
    assert feed_project == set(EXPECTED)
    assert all(s.feed is None for a, s in EVENT_CATALOG.items() if a.value in USER_ACTIONS)
