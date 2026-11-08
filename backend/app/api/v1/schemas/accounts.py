"""Схемы раздела «Учётные записи без роли» для БА: ``/api/v1/unassigned-accounts*``.

Spec 019, FR-13a, AC-30; plan §4.4. В элементе списка email нет (NFR-1, FR-13a): БА его не видит.
Запрос назначения роли — ``SetRoleRequest`` из ``schemas/admin.py`` (та же схема, что у
``PUT /admin/users/{id}/role``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UnassignedAccountOut(BaseModel):
    """Учётная запись без роли: ровно id, логин, имя, фамилия и дата создания (AC-30)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    login: str
    first_name: str | None
    last_name: str | None
    created_at: datetime
