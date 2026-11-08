"""A11-T01: тип вложения по расширению и содержимому, имя файла (spec 011 FR-4, FR-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import Unprocessable
from app.domain.attachments.types import FileKind, clean_name, detect_kind
from tests import attachments_support as fx


def _detect(tmp_path: Path, name: str, data: bytes) -> FileKind:
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    return detect_kind(name, data[:64], path)


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [
        ("отчёт.pdf", fx.PDF, FileKind.PDF),
        ("план.docx", fx.ooxml("docx"), FileKind.DOCX),
        ("смета.XLSX", fx.ooxml("xlsx"), FileKind.XLSX),
        ("слайды.pptx", fx.ooxml("pptx"), FileKind.PPTX),
        ("заметка.txt", fx.TXT_UTF8, FileKind.TXT),
        ("заметка-1251.txt", fx.TXT_1251, FileKind.TXT),
        ("выгрузка.csv", fx.CSV, FileKind.CSV),
        ("скрин.png", fx.PNG, FileKind.PNG),
        ("фото.jpg", fx.JPEG, FileKind.JPEG),
        ("фото.jpeg", fx.JPEG, FileKind.JPEG),
        ("анимация.gif", fx.GIF, FileKind.GIF),
        ("картинка.webp", fx.WEBP, FileKind.WEBP),
    ],
)
def test_011_ac2_allowed_types(tmp_path: Path, name: str, data: bytes, kind: FileKind) -> None:
    assert _detect(tmp_path, name, data) is kind


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("setup.exe", b"MZ\x90\x00"),
        ("run.sh", b"#!/bin/sh\necho hi\n"),
        ("app.js", b"alert(1)"),
        ("page.html", b"<html><script>alert(1)</script></html>"),
        ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("macro.docm", fx.ooxml("docx")),
        ("macro.docx", fx.ooxml("docx", macro=True)),
        (
            "hidden.docx",
            fx.ooxml_with_type("docx", "word/data.bin", "application/vnd.ms-office.vbaProject"),
        ),
        ("activex.docx", fx.ooxml("docx", extra=("word/activeX/activeX1.xml", "<ax/>"))),
        ("ole.xlsx", fx.ooxml("xlsx", extra=("xl/embeddings/oleObject1.bin", "x"))),
        ("fake.pdf", fx.PNG),
        ("fake.docx", fx.ooxml("xlsx")),
        ("broken.docx", b"PK\x03\x04garbage"),
        ("bin.txt", b"text\x00binary"),
        ("ctrl.txt", b"text\x07bell"),
        ("noext", fx.PDF),
    ],
)
def test_011_ac2_refused_types(tmp_path: Path, name: str, data: bytes) -> None:
    with pytest.raises(Unprocessable) as err:
        _detect(tmp_path, name, data)
    assert err.value.code in {"attachment_type_not_allowed"}


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\отчёт.pdf", "отчёт.pdf"),
        ("имя\x00\x1f.pdf", "имя.pdf"),
        ("  пробелы.txt  ", "пробелы.txt"),
    ],
)
def test_011_ac6_clean_name(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


def test_011_long_name_keeps_extension() -> None:
    name = clean_name("я" * 300 + ".pdf")
    assert len(name) == 255 and name.endswith(".pdf")


@pytest.mark.parametrize("raw", ["", "   ", "..", "\x00"])
def test_011_empty_name_is_refused(raw: str) -> None:
    with pytest.raises(Unprocessable):
        clean_name(raw)
