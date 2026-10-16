"""Роли, возможности и субъект запроса (plan §4.5, BR-1, BR-2, BR-11, FR-8…FR-10, FR-66).

Матрица ``ROLE_CAPABILITIES`` отвечает на вопрос «открыт ли раздел». Права на конкретный
объект (проект, задача) проверяет ``domain/access/policy.py`` (R1.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, auto
from types import MappingProxyType
from typing import Final
from uuid import UUID


class Role(StrEnum):
    """Роль в пространстве; значения совпадают с ``workspace_member.role`` (CHECK role_valid)."""

    TECH_ADMIN = "tech_admin"
    BUSINESS_ADMIN = "business_admin"
    MIXED = "mixed"
    USER = "user"


class Capability(StrEnum):
    """Возможность; значение — имя члена в нижнем регистре (``auto()`` у ``StrEnum``)."""

    MANAGE_ACCOUNTS = auto()  # создание/блокировка/разблокировка, сброс пароля, сессии
    ASSIGN_ROLES = auto()  # FR-12
    VIEW_AUDIT = auto()  # FR-41
    BUSINESS_ACCESS = auto()  # раздел проектов и задач
    PROJECT_CREATE = auto()
    # БА: правка, участники (в т.ч. себя), владение, удаление, архив — любой проект (002/FR-8)
    PROJECT_MANAGE_ANY = auto()
    TASK_ASSIGN_OTHERS = auto()  # «создание задачи другому», смена исполнителя (FR-19a)
    LABELS_MANAGE = auto()  # FR-18b
    CRM_READ = auto()
    CRM_WRITE = auto()  # включая удаление/восстановление CRM, связь с проектом
    PIPELINE_MANAGE = auto()  # FR-34


_TECH_ADMIN_CAPS: Final = frozenset(
    {Capability.MANAGE_ACCOUNTS, Capability.ASSIGN_ROLES, Capability.VIEW_AUDIT}
)
_BUSINESS_ADMIN_CAPS: Final = frozenset(
    {
        Capability.BUSINESS_ACCESS,
        Capability.PROJECT_CREATE,
        Capability.PROJECT_MANAGE_ANY,
        Capability.TASK_ASSIGN_OTHERS,
        Capability.LABELS_MANAGE,
        Capability.CRM_READ,
        Capability.CRM_WRITE,
        Capability.PIPELINE_MANAGE,
    }
)

ROLE_CAPABILITIES: Final[Mapping[Role, frozenset[Capability]]] = MappingProxyType(
    {
        Role.TECH_ADMIN: _TECH_ADMIN_CAPS,
        Role.BUSINESS_ADMIN: _BUSINESS_ADMIN_CAPS,
        Role.MIXED: _TECH_ADMIN_CAPS | _BUSINESS_ADMIN_CAPS | {Capability.PROJECT_MANAGE_ANY},
        Role.USER: frozenset({Capability.BUSINESS_ACCESS}),
    }
)

# Обладатели MANAGE_ACCOUNTS; для инварианта «всегда есть активный администратор» (FR-69).
ACCOUNT_ADMIN_ROLES: Final = frozenset({Role.TECH_ADMIN, Role.MIXED})


@dataclass(frozen=True, slots=True)
class Actor:
    """Субъект запроса: данные читаются из БД на каждый запрос (FR-67)."""

    user_id: UUID
    workspace_id: UUID
    login: str
    role: Role | None
    must_change_password: bool
    session_id: bytes

    def can(self, cap: Capability) -> bool:
        """Есть ли у роли возможность; без роли (FR-66) — нет ни одной."""
        if self.role is None:
            return False
        return cap in ROLE_CAPABILITIES[self.role]
