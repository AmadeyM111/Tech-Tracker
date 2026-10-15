"""Проверка получателя действия: исполнитель, участник, владелец (FR-70, plan §4.5, §11.5).

Порядок: ``user_not_found`` → ``user_blocked`` → ``recipient_wrong_role`` →
``not_project_member``; все ошибки — ``Unprocessable`` (422). Чистая функция без БД.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
from uuid import UUID

from app.core.errors import ErrorCode, Unprocessable
from app.domain.access.roles import ROLE_CAPABILITIES, Capability, Role


class RecipientPurpose(StrEnum):
    PROJECT_MEMBER = auto()  # БА, СМ, «Пользователь»
    TASK_ASSIGNEE = auto()  # БА, СМ, «Пользователь» + участник проекта
    PROJECT_OWNER = auto()  # БА, СМ + участник проекта


@dataclass(frozen=True, slots=True)
class RecipientFacts:
    user_id: UUID
    in_workspace: bool
    is_blocked: bool
    role: Role | None


# Возможность, которой должна обладать роль получателя.
_REQUIRED_CAPABILITY = {
    RecipientPurpose.PROJECT_MEMBER: Capability.BUSINESS_ACCESS,
    RecipientPurpose.TASK_ASSIGNEE: Capability.BUSINESS_ACCESS,
    RecipientPurpose.PROJECT_OWNER: Capability.PROJECT_CREATE,
}
_MEMBER_REQUIRED = frozenset({RecipientPurpose.TASK_ASSIGNEE, RecipientPurpose.PROJECT_OWNER})


def check_recipient(
    target: RecipientFacts,
    purpose: RecipientPurpose,
    *,
    project_member_ids: frozenset[UUID] | None,
) -> None:
    """Бросает ``Unprocessable`` с кодом первой нарушенной проверки.

    ``ValueError`` — ошибка вызывающего кода: цель требует членства, а список участников
    не передан (``project_member_ids is None``).
    """
    member_required = purpose in _MEMBER_REQUIRED
    if member_required and project_member_ids is None:
        raise ValueError(f"project_member_ids обязателен для {purpose}")
    members = project_member_ids or frozenset()
    if not target.in_workspace:
        raise Unprocessable("Пользователь не найден", code=ErrorCode.user_not_found)
    if target.is_blocked:
        raise Unprocessable("Пользователь заблокирован", code=ErrorCode.user_blocked)
    if target.role is None or _REQUIRED_CAPABILITY[purpose] not in ROLE_CAPABILITIES[target.role]:
        raise Unprocessable(
            "Роль пользователя не подходит для этого действия",
            code=ErrorCode.recipient_wrong_role,
        )
    if member_required and target.user_id not in members:
        raise Unprocessable("Пользователь не участник проекта", code=ErrorCode.not_project_member)
