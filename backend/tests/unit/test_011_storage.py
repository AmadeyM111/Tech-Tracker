"""A11-T02: потоковая запись вложения (spec 011 FR-2, FR-5, NFR-1, NFR-3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.errors import PayloadTooLarge, StorageFull, Unprocessable
from app.domain.attachments import storage


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for p in parts:
        yield p


async def test_011_stream_limit_without_content_length(tmp_path: Path) -> None:
    with pytest.raises(PayloadTooLarge):
        await storage.stage(tmp_path, _chunks(b"a" * 6, b"b" * 5), max_bytes=10)
    assert list((tmp_path / storage.INCOMING).iterdir()) == [], "временный файл удалён"


async def test_011_stage_publish_roundtrip(tmp_path: Path) -> None:
    staged = await storage.stage(tmp_path, _chunks(b"%PDF-", b"", b"x" * 100), max_bytes=1000)
    assert staged.size == 105 and staged.head.startswith(b"%PDF-") and len(staged.head) == 64
    assert (staged.path.stat().st_mode & 0o777) == 0o600
    target = storage.publish(tmp_path, staged)
    assert target == tmp_path / staged.key[:2] / staged.key
    assert target.read_bytes() == b"%PDF-" + b"x" * 100 and not staged.path.exists()


async def test_011_empty_stream_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Unprocessable) as err:
        await storage.stage(tmp_path, _chunks(), max_bytes=10)
    assert err.value.code == "attachment_empty"


@pytest.mark.parametrize("key", ["../../etc/passwd", "A" * 32, "a" * 31, ""])
def test_011_final_path_accepts_only_hex_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="ключ"):
        storage.final_path(tmp_path, key)


def test_011_free_space_threshold(tmp_path: Path) -> None:
    storage.check_free_space(tmp_path, 0)
    with pytest.raises(StorageFull):
        storage.check_free_space(tmp_path, 10**12)
