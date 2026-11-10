"""Хранилище файлов вложений (spec 011 FR-2, FR-5, NFR-1, NFR-3; plan PA-3, PA-4, PA-6).

Запись потоковая: во временный файл (0600) в ``DATA_DIR/attachments/.incoming`` с подсчётом
размера и sha256; превышение лимита прерывает запись сразу. Публикация — ``os.replace`` в
``attachments/<ключ[:2]>/<ключ>``. Имя файла пользователя в путь не попадает никогда.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import uuid4

from app.core.errors import ErrorCode, PayloadTooLarge, StorageFull, Unprocessable

INCOMING: Final = ".incoming"
HEAD_BYTES: Final = 64
_KEY_LEN: Final = 32


@dataclass(frozen=True)
class StagedFile:
    """Принятый, но ещё не опубликованный файл."""

    key: str
    path: Path
    size: int
    sha256: str
    head: bytes


def final_path(root: Path, key: str) -> Path:
    """Путь файла по ключу; ключ — только 32 hex (иначе ``ValueError``)."""
    if len(key) != _KEY_LEN or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("неверный ключ хранения")
    return root / key[:2] / key


def check_free_space(root: Path, min_free_mb: int) -> None:
    """Отказ 507, если на диске каталога данных меньше порога (FR-10)."""
    probe = root if root.exists() else root.parent
    if shutil.disk_usage(probe).free < min_free_mb * 1024 * 1024:
        raise StorageFull()


def private_root(root: Path) -> None:
    """Каталог вложений и ``incoming`` — 0700 (ревью 011): ``mkdir(parents=True)`` задаёт режим
    только последнему звену, а каталог, созданный раньше (или при umask 000), мог быть шире."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    (root / INCOMING).mkdir(mode=0o700, exist_ok=True)
    (root / INCOMING).chmod(0o700)


async def stage(root: Path, chunks: AsyncIterator[bytes], *, max_bytes: int) -> StagedFile:
    """Пишет поток во временный файл; > ``max_bytes`` — 413, пустой — 422."""
    private_root(root)
    incoming = root / INCOMING
    key = uuid4().hex
    path = incoming / key
    digest = hashlib.sha256()
    size = 0
    head = b""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise PayloadTooLarge(f"Файл больше {max_bytes} байт")
                if len(head) < HEAD_BYTES:
                    head += chunk[: HEAD_BYTES - len(head)]
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise Unprocessable("Файл пуст", code=ErrorCode.attachment_empty)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return StagedFile(key=key, path=path, size=size, sha256=digest.hexdigest(), head=head)


def publish(root: Path, staged: StagedFile) -> Path:
    """Переносит файл под ключ (атомарно, тот же том) и возвращает итоговый путь."""
    target = final_path(root, staged.key)
    target.parent.mkdir(mode=0o700, exist_ok=True)
    target.parent.chmod(0o700)
    os.replace(staged.path, target)
    return target


def discard(path: Path) -> None:
    path.unlink(missing_ok=True)
