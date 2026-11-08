"""Определение типа вложения по расширению И содержимому (spec 011 FR-4; plan PA-2, PA-7).

Клиентскому ``Content-Type`` не верим. OOXML проверяется по оглавлению zip и
``[Content_Types].xml`` без распаковки частей (защита от zip-бомб). Текст — без NUL и управляющих
символов, в UTF-8 или Windows-1251 (Q-3). SVG, HTML, макросы и всё вне списка — отказ (Q-1).
"""

from __future__ import annotations

import unicodedata
import zipfile
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

from app.core.errors import ErrorCode, Unprocessable


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    TXT = "txt"
    CSV = "csv"
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"


EXTENSIONS: Final[dict[str, FileKind]] = {
    "pdf": FileKind.PDF,
    "docx": FileKind.DOCX,
    "xlsx": FileKind.XLSX,
    "pptx": FileKind.PPTX,
    "txt": FileKind.TXT,
    "csv": FileKind.CSV,
    "png": FileKind.PNG,
    "jpg": FileKind.JPEG,
    "jpeg": FileKind.JPEG,
    "gif": FileKind.GIF,
    "webp": FileKind.WEBP,
}
CONTENT_TYPES: Final[dict[FileKind, str]] = {
    FileKind.PDF: "application/pdf",
    FileKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileKind.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    FileKind.TXT: "text/plain; charset=utf-8",
    FileKind.CSV: "text/csv; charset=utf-8",
    FileKind.PNG: "image/png",
    FileKind.JPEG: "image/jpeg",
    FileKind.GIF: "image/gif",
    FileKind.WEBP: "image/webp",
}
# Показ в браузере (FR-6): только растровые картинки.
INLINE: Final = frozenset({FileKind.PNG, FileKind.JPEG, FileKind.GIF, FileKind.WEBP})
_OOXML_MAIN: Final[dict[FileKind, str]] = {
    FileKind.DOCX: "wordprocessingml.document.main+xml",
    FileKind.XLSX: "spreadsheetml.sheet.main+xml",
    FileKind.PPTX: "presentationml.presentation.main+xml",
}
_MAX_CONTENT_TYPES_XML: Final = 1024 * 1024
_TEXT_CONTROLS_OK: Final = frozenset("\t\n\r\f")
NAME_MAX: Final = 255


def _refuse() -> Unprocessable:
    return Unprocessable(
        "Тип файла не поддерживается: PDF, DOCX, XLSX, PPTX, TXT, CSV, PNG, JPEG, GIF, WebP",
        code=ErrorCode.attachment_type_not_allowed,
    )


def clean_name(raw: str) -> str:
    """Имя для метаданных: последняя часть пути, без управляющих символов, NFC, ≤ 255."""
    base = PureWindowsPath(PurePosixPath(raw).name).name
    text = unicodedata.normalize("NFC", base)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C").strip()
    if text in {"", ".", ".."}:
        raise Unprocessable("Укажите имя файла", code=ErrorCode.validation_error)
    if len(text) > NAME_MAX:
        stem, dot, ext = text.rpartition(".")
        keep = NAME_MAX - len(dot + ext)
        text = (stem[:keep] + dot + ext) if dot and keep > 0 else text[:NAME_MAX]
    return text


def _extension_kind(name: str) -> FileKind:
    _, dot, ext = name.rpartition(".")
    kind = EXTENSIONS.get(ext.lower()) if dot else None
    if kind is None:
        raise _refuse()
    return kind


def _signature_ok(kind: FileKind, head: bytes) -> bool:
    match kind:
        case FileKind.PDF:
            return head.startswith(b"%PDF-")
        case FileKind.PNG:
            return head.startswith(b"\x89PNG\r\n\x1a\n")
        case FileKind.JPEG:
            return head.startswith(b"\xff\xd8\xff")
        case FileKind.GIF:
            return head.startswith((b"GIF87a", b"GIF89a"))
        case FileKind.WEBP:
            return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
        case FileKind.DOCX | FileKind.XLSX | FileKind.PPTX:
            return head.startswith(b"PK\x03\x04")
        case FileKind.TXT | FileKind.CSV:
            return True


def _ooxml_ok(kind: FileKind, path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                return False
            info = zf.getinfo("[Content_Types].xml")
            if info.file_size > _MAX_CONTENT_TYPES_XML:
                return False
            types = zf.read(info).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError, NotImplementedError):
        return False
    return "macroenabled" not in types.lower() and _OOXML_MAIN[kind] in types


def _text_ok(path: Path) -> bool:
    raw = path.read_bytes()  # ≤ ATTACHMENT_MAX_BYTES (10 МБ)
    if b"\x00" in raw:
        return False
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError:
            return False
    return all(ch in _TEXT_CONTROLS_OK or unicodedata.category(ch) != "Cc" for ch in text)


def detect_kind(name: str, head: bytes, path: Path) -> FileKind:
    """Тип вложения; любое несоответствие — 422 ``attachment_type_not_allowed``."""
    kind = _extension_kind(name)
    if not _signature_ok(kind, head):
        raise _refuse()
    if kind in _OOXML_MAIN and not _ooxml_ok(kind, path):
        raise _refuse()
    if kind in (FileKind.TXT, FileKind.CSV) and not _text_ok(path):
        raise _refuse()
    return kind
