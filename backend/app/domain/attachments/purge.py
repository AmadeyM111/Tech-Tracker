"""Окончательное удаление вложений и файлов-сирот (spec 011 FR-7; ADR-0010).

Вызывается из ``gtrack maintenance``. Вложение, удалённое раньше ``now - TRASH_RETENTION``,
теряет файл и строку. Сирота — файл в ``attachments/`` без строки ``attachment`` (сбой
``COMMIT`` после записи файла) или незавершённая загрузка в ``.incoming``; удаляется, если старше
``ORPHAN_GRACE`` (идущая загрузка не задевается). ``dry_run`` — только счёт.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete, select

from app.core.config import Settings
from app.core.db import transaction
from app.domain.attachments.models import Attachment
from app.domain.attachments.storage import INCOMING, final_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ORPHAN_GRACE: Final = timedelta(hours=1)
_KEY: Final = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class PurgeReport:
    attachments_purged: int
    files_removed: int
    orphan_files_removed: int


def _old(path: Path, now: datetime) -> bool:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC) < now - ORPHAN_GRACE


def _orphans(root: Path, known: set[str], now: datetime) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.glob("*/*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.parent.name == INCOMING:
            if _old(path, now):
                found.append(path)
        elif _KEY.fullmatch(path.name) and path.name not in known and _old(path, now):
            found.append(path)
    return found


async def purge_attachments(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
    dry_run: bool,
) -> PurgeReport:
    """Удаляет просроченные в корзине вложения и сирот; возвращает счётчики."""
    root = settings.attachments_dir
    cutoff = now - settings.trash_retention
    async with transaction(sessionmaker) as db:
        expired = list(
            (
                await db.execute(
                    select(Attachment.id, Attachment.storage_key)
                    .where(Attachment.deleted_at < cutoff)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if expired and not dry_run:
            ids = [r.id for r in expired]
            await db.execute(delete(Attachment).where(Attachment.id.in_(ids)))
        known = set((await db.execute(select(Attachment.storage_key))).scalars())
    # файлы — после фиксации удаления строк: сбой COMMIT не оставляет строк без файлов
    paths = [final_path(root, r.storage_key) for r in expired]
    existing = [p for p in paths if p.exists()]
    if not dry_run:
        for path in existing:
            path.unlink(missing_ok=True)
    files_removed = len(existing)
    orphans = _orphans(root, known, now)
    if not dry_run:
        for path in orphans:
            path.unlink(missing_ok=True)
    return PurgeReport(len(expired), files_removed, len(orphans))
