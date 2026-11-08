"""B09-T05: ``GET /api/v1/admin/system/backup`` (spec 009 FR-6; AC-7, AC-8)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import insert

from app.domain.ops.models import BackupRun
from tests.conftest import FIXED_NOW, ApiEnv

URL = "/api/v1/admin/system/backup"


async def _seed_run(env: ApiEnv, *, ago: timedelta, status: str = "ok") -> None:
    finished = FIXED_NOW - ago
    await env.execute(
        insert(BackupRun).values(
            id=uuid.uuid4(),
            started_at=finished - timedelta(seconds=5),
            finished_at=finished,
            status=status,
            size_bytes=2048 if status == "ok" else None,
            schema_revision="0011" if status == "ok" else None,
            file_name="gtrack-backup-x.tar" if status == "ok" else None,
            error_code=None if status == "ok" else "pg_dump_failed",
        )
    )


async def _get_as(env: ApiEnv, role: str | None) -> Any:
    user = await env.new_user(role=role)
    return await env.client.get(URL, headers=env.auth(await env.login_ok(user)))


async def test_009_ac7_tech_admin_sees_status_fields(api_env: ApiEnv) -> None:
    await _seed_run(api_env, ago=timedelta(hours=2))
    response = await _get_as(api_env, "tech_admin")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "last_success_at",
        "last_success_size_bytes",
        "last_run_at",
        "last_run_status",
        "stale",
        "stale_after_hours",
    }
    assert body["last_success_size_bytes"] == 2048
    assert body["last_run_status"] == "ok"
    assert body["stale"] is False and body["stale_after_hours"] == 26
    assert "file_name" not in body and "path" not in body


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_009_ac7_other_roles_get_403(api_env: ApiEnv, role: str) -> None:
    response = await _get_as(api_env, role)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_009_ac7_anonymous_gets_401(api_env: ApiEnv) -> None:
    assert (await api_env.client.get(URL)).status_code == 401


@pytest.mark.parametrize(
    ("ago", "stale"),
    [(timedelta(hours=25, minutes=59), False), (timedelta(hours=26, minutes=1), True)],
    ids=["25h59m", "26h01m"],
)
async def test_009_ac8_stale_boundary(api_env: ApiEnv, ago: timedelta, stale: bool) -> None:
    await _seed_run(api_env, ago=ago)
    assert (await _get_as(api_env, "tech_admin")).json()["stale"] is stale


async def test_009_ac8_no_copies_is_stale(api_env: ApiEnv) -> None:
    body = (await _get_as(api_env, "tech_admin")).json()
    assert body["stale"] is True
    assert body["last_success_at"] is None and body["last_run_status"] is None


async def test_009_ac8_last_run_failed_is_stale(api_env: ApiEnv) -> None:
    await _seed_run(api_env, ago=timedelta(hours=3))
    await _seed_run(api_env, ago=timedelta(hours=1), status="failed")
    body = (await _get_as(api_env, "tech_admin")).json()
    assert body["stale"] is True
    assert body["last_run_status"] == "failed"
    assert body["last_success_size_bytes"] == 2048
