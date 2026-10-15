"""T79: очистка HTML в комментариях, чистая функция (plan D-28, D-60; AC-58, FR-23, SC-11).

Ожидаемый интерфейс: ``app.domain.comments.sanitize.strip_html(text: str) -> str``
(``html.parser.HTMLParser``, ``convert_charrefs=False``): теги (открывающие, закрывающие,
самозакрывающиеся), комментарии, декларации и инструкции удаляются; содержимое ``script`` и
``style`` (включая незакрытые) удаляется; ссылки на сущности и прочий текст — как есть.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def strip_html() -> Any:
    from app.domain.comments.sanitize import strip_html as fn

    return fn


@pytest.mark.parametrize(
    "text",
    [
        "обычный текст",
        "",
        "строка 1\n\nстрока 2\n\tотступ",
        "> цитата\n- пункт\n**жирный** `код` [ссылка](http://x.y)",
        "Привет, мир! Ёё 日本語 \U0001f600",
        "a < b and c > d",
        "1 < 2 > 0",
        "3 <4 and 5> 2",
        "x <= y >= z",
    ],
)
def test_ac58_plain_text_and_markdown_unchanged(strip_html: Any, text: str) -> None:
    assert strip_html(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<b>жирный</b>", "жирный"),
        ("a<b>b</b>c", "abc"),
        ("<div><p>text</p></div>", "text"),
        ("one<br>two<br/>three<br />four", "onetwothreefour"),
        ('<a href="http://x" title="a>b">link</a>', "link"),
        ("<img src=x onerror=alert(1)>ok", "ok"),
        ("<IMG SRC=x ONERROR=alert(1)>ok", "ok"),
        ("</b>stray", "stray"),
        ("<b>bo<i>ld</b></i>", "bold"),
        ("<b><i><u>deep</u></i></b>", "deep"),
    ],
)
def test_ac58_tags_removed_text_kept(strip_html: Any, text: str, expected: str) -> None:
    assert strip_html(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a<!-- hidden -->b", "ab"),
        ("a<!-- <b>x</b> -->b", "ab"),
        ("a<!-- <script>alert(1)</script> -->b", "ab"),
        ("<!DOCTYPE html>text", "text"),
        ("<?php echo 1; ?>text", "text"),
        ("<?xml version='1.0'?>text", "text"),
    ],
)
def test_ac58_comments_declarations_instructions_removed(
    strip_html: Any, text: str, expected: str
) -> None:
    assert strip_html(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("before<script>alert(1)</script>after", "beforeafter"),
        ("before<SCRIPT>alert(1)</SCRIPT>after", "beforeafter"),
        ("before<script type='text/javascript'>alert(1)</script>after", "beforeafter"),
        ("before<script>if (a<b) {x()}</script>after", "beforeafter"),
        ("before<script>var s = '<b>';</script>after", "beforeafter"),
        ("before<style>body{display:none}</style>after", "beforeafter"),
        ("before<STYLE type='text/css'>a>b{}</STYLE>after", "beforeafter"),
        ("a<script>1</script>b<style>2</style>c", "abc"),
        ("<script></script>x", "x"),
    ],
)
def test_ac58_script_and_style_content_removed(strip_html: Any, text: str, expected: str) -> None:
    assert strip_html(text) == expected


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        ("hi <script>alert(1)", "alert"),
        ("hi <script>alert(1)<b>bold</b>", "alert"),
        ("hi <style>body{display:none}", "display"),
        ("hi <SCRIPT SRC=x>steal()", "steal"),
    ],
)
def test_ac58_unclosed_script_and_style_swallow_rest(
    strip_html: Any, text: str, marker: str
) -> None:
    out = strip_html(text)
    assert marker not in out
    assert out.startswith("hi")
    assert "<" not in out


@pytest.mark.parametrize(
    "text",
    [
        "&lt;script&gt;alert(1)&lt;/script&gt;",
        "&#60;b&#62; &#x3C;i&#x3E;",
        "Tom &amp; Jerry &copy; 2026 &nbsp;",
        "a &lt; b &gt; c",
        "&amp;lt;",
    ],
)
def test_ac58_entities_kept_as_is(strip_html: Any, text: str) -> None:
    """convert_charrefs=False: сущности не раскрываются (иначе &lt;script&gt; стал бы тегом)."""
    assert strip_html(text) == text


def test_ac58_entity_next_to_tag(strip_html: Any) -> None:
    assert strip_html("<b>&lt;i&gt;</b>") == "&lt;i&gt;"


def test_ac58_result_is_idempotent(strip_html: Any) -> None:
    raw = "<b>x</b> &lt;script&gt; a < b > c <!-- c --> <script>1</script>y"
    once = strip_html(raw)
    assert strip_html(once) == once


def test_ac58_no_angle_tag_survives_nested_obfuscation(strip_html: Any) -> None:
    """Вложенный/сломанный тег не должен «склеиваться» в новый тег после удаления."""
    out = strip_html("<scr<b>ipt>alert(1)</scr</b>ipt>")
    assert "<script" not in out.lower()
    assert "alert" in out or out == ""  # вне script: либо текст, либо пусто, но не тег
    assert strip_html(out) == out


def test_ac58_result_type_is_str(strip_html: Any) -> None:
    assert isinstance(strip_html("<b>x</b>"), str)


MULTILAYER = [
    "<" * 18 + "b>" * 16 + "img src=x onerror=alert(1)>",
    "<" * 18 + "b>" * 16 + "script>alert(document.cookie)</script>",
    "<" * 40 + "b>" * 40 + "img src=x onerror=alert(1)>",
    "<" * 3 + "b>" * 2 + "img src=x onerror=alert(1)>",
    "<<b>script>alert(1)</script>",
]


@pytest.mark.parametrize("raw", MULTILAYER)
def test_ac58_multilayer_input_leaves_no_tag_and_is_idempotent(strip_html: Any, raw: str) -> None:
    """Слоёв больше лимита проходов: результат не содержит ``<`` перед буквой/``/``/``!``/``?``
    и устойчив к повторному вызову (нельзя вернуть частично очищенную склейку)."""
    import re

    out = strip_html(raw)
    assert not re.search(r"<[A-Za-z/!?]", out), out
    assert "<img" not in out.lower()
    assert "<script" not in out.lower()
    assert strip_html(out) == out


def test_ac58_single_extra_pass_is_required(strip_html: Any) -> None:
    """Один проход оставил бы ``<script>``: ``<<b>script>`` -> ``<script>``."""
    out = strip_html("<<b>script>alert(1)</script>")
    assert "<script" not in out.lower()
    assert strip_html(out) == out


@pytest.mark.parametrize(
    "raw",
    ["AT&T", "R&D", "Q&A", "x &y", "http://h/?a=1&b", "&x", "&", "a &", "x&", "&&", "&a&b"],
)
def test_sc11_ampersand_kept_as_typed(strip_html: Any, raw: str) -> None:
    assert strip_html(raw) == raw
