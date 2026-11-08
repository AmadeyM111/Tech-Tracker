"""Синтетические файлы для тестов 011: сигнатуры и минимальная структура, без документов."""

from __future__ import annotations

import io
import zipfile

PDF = b"%PDF-1.4\n%synthetic\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8
TXT_UTF8 = "Привет, мир\nстрока 2\n".encode()
TXT_1251 = "Привет; мир\r\n".encode("cp1251")
CSV = "проект;задача\r\nКлиника;Сверка\r\n".encode()

_MAIN = {
    "docx": ("word/document.xml", "wordprocessingml.document.main+xml"),
    "xlsx": ("xl/workbook.xml", "spreadsheetml.sheet.main+xml"),
    "pptx": ("ppt/presentation.xml", "presentationml.presentation.main+xml"),
}


def ooxml(kind: str, *, macro: bool = False, extra: tuple[str, str] | None = None) -> bytes:
    """Минимальный OOXML-zip: ``[Content_Types].xml`` и главная часть; ``macro`` — с VBA."""
    part, main = _MAIN[kind]
    ctype = f"application/vnd.openxmlformats-officedocument.{main}"
    if macro:
        ctype = "application/vnd.ms-word.document.macroEnabled.main+xml"
    types = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
        f'package/2006/content-types"><Override PartName="/{part}" ContentType="{ctype}"/></Types>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", types)
        zf.writestr(part, "<x/>")
        if macro:
            zf.writestr("word/vbaProject.bin", b"\x00vba")
        if extra is not None:
            zf.writestr(extra[0], extra[1])
    return buf.getvalue()


def ooxml_with_type(kind: str, part: str, content_type: str) -> bytes:
    """OOXML, где опасная часть объявлена типом, а имя части безобидное."""
    main_part, main = _MAIN[kind]
    types = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
        f'package/2006/content-types"><Override PartName="/{main_part}" ContentType='
        f'"application/vnd.openxmlformats-officedocument.{main}"/><Override PartName="/{part}" '
        f'ContentType="{content_type}"/></Types>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", types)
        zf.writestr(main_part, "<x/>")
        zf.writestr(part, b"\x00")
    return buf.getvalue()
