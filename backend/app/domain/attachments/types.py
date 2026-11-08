"""Определение типа вложения по расширению И содержимому (spec 011 FR-4; plan PA-2, PA-7).

Клиентскому ``Content-Type`` не верим. OOXML проверяется по оглавлению zip и
``[Content_Types].xml`` без распаковки частей (защита от zip-бомб). Текст — без NUL и управляющих
символов, в UTF-8 или Windows-1251 (Q-3). SVG, HTML, макросы и всё вне списка — отказ (Q-1).
"""

from __future__ import annotations

import re
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
# Управляющие символы, недопустимые в тексте (кроме \t \n \f \r): признак двоичного файла.
_TEXT_CONTROL: Final = re.compile("[\x00-\x08\x0b\x0e-\x1f\x7f]")
# OOXML: макросы, ActiveX и OLE-объекты — отказ независимо от имени части (ревью 011, п. 7).
_OOXML_FORBIDDEN: Final = ("macroenabled", "vbaproject", "activex", "oleobject")
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
            names = [n.lower() for n in zf.namelist()]
            if any(bad in n for n in names for bad in _OOXML_FORBIDDEN):
                return False
            info = zf.getinfo("[Content_Types].xml")
            if info.file_size > _MAX_CONTENT_TYPES_XML:
                return False
            types = zf.read(info).decode("utf-8", errors="replace").lower()
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError, NotImplementedError):
        return False
    return not any(bad in types for bad in _OOXML_FORBIDDEN) and _OOXML_MAIN[kind].lower() in types


def _decode_text(raw: bytes) -> tuple[str, str] | None:
    """Текст и кодировка (UTF-8 или Windows-1251, Q-3); ``None`` — не текст."""
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1251"), "windows-1251"
    except UnicodeDecodeError:
        return None


def _text_ok(path: Path) -> bool:
    decoded = _decode_text(path.read_bytes())  # ≤ ATTACHMENT_MAX_BYTES (10 МБ)
    return decoded is not None and _TEXT_CONTROL.search(decoded[0]) is None


def content_type_for(kind: FileKind, path: Path) -> str:
    """MIME для отдачи; у текста — фактическая кодировка (UTF-8 или Windows-1251)."""
    if kind not in (FileKind.TXT, FileKind.CSV):
        return CONTENT_TYPES[kind]
    decoded = _decode_text(path.read_bytes())
    charset = "utf-8" if decoded is None else decoded[1]
    base = "text/plain" if kind is FileKind.TXT else "text/csv"
    return f"{base}; charset={charset}"


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
