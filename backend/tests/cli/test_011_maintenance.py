"""A11-T04: окончательное удаление вложений и файлов-сирот (spec 011 FR-7; AC-7)."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.clock import utcnow
from app.core.config import Settings
from app.domain.attachments.models import Attachment
from app.domain.attachments.purge import purge_attachments
from app.domain.attachments.storage import INCOMING, final_path
from tests.factories import make_project, make_task, make_user

pytestmark = pytest.mark.committed


async def _attachment(sm: Any, settings: Settings, *, deleted_days: float | None) -> Path:
    now = utcnow()
    async with sm() as s:
        user = await make_user(s, role="business_admin")
        project = await make_project(s, workspace_id=user.workspace_id, owner_id=user.id)
        task = await make_task(
            s, project_id=project.id, workspace_id=user.workspace_id, created_by=user.id
        )
        key = uuid.uuid4().hex
        s.add(
            Attachment(
                workspace_id=user.workspace_id,
                task_id=task.id,
                project_id=project.id,
                created_by=user.id,
                original_name="f.pdf",
                kind="pdf",
                content_type="application/pdf",
                size_bytes=5,
                sha256="a" * 64,
                storage_key=key,
                deleted_at=None if deleted_days is None else now - timedelta(days=deleted_days),
            )
        )
        await s.commit()
    path = final_path(settings.attachments_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-")
    return path


def _orphan(settings: Settings, rel: str, *, hours_old: float) -> Path:
    path = settings.attachments_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = (utcnow() - timedelta(hours=hours_old)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


async def test_011_ac7_purge_after_retention_and_orphans(
    committed: Any, settings: Settings
) -> None:
    expired = await _attachment(committed, settings, deleted_days=31)
    recent = await _attachment(committed, settings, deleted_days=29)
    live = await _attachment(committed, settings, deleted_days=None)
    old_orphan = _orphan(settings, "ab/" + "ab" * 16, hours_old=2)
    young_orphan = _orphan(settings, "cd/" + "cd" * 16, hours_old=0.1)
    stale_upload = _orphan(settings, f"{INCOMING}/" + "ef" * 16, hours_old=3)

    dry = await purge_attachments(committed, settings, now=utcnow(), dry_run=True)
    assert (dry.attachments_purged, dry.files_removed, dry.orphan_files_removed) == (1, 1, 2)
    assert expired.exists() and old_orphan.exists()

    report = await purge_attachments(committed, settings, now=utcnow(), dry_run=False)
    assert (report.attachments_purged, report.files_removed, report.orphan_files_removed) == (
        1,
        1,
        2,
    )
    assert not expired.exists() and not old_orphan.exists() and not stale_upload.exists()
    assert recent.exists() and live.exists() and young_orphan.exists()
    async with committed() as s:
        assert (await s.execute(select(func.count()).select_from(Attachment))).scalar_one() == 2

    again = await purge_attachments(committed, settings, now=utcnow(), dry_run=False)
    assert (again.attachments_purged, again.files_removed, again.orphan_files_removed) == (0, 0, 0)
