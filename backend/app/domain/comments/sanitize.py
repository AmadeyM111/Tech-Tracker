"""Очистка HTML в комментариях (plan D-28, D-60; AC-58, FR-23, SC-11).

Свой фильтр на ``html.parser.HTMLParser`` с ``convert_charrefs=False``: теги, комментарии,
декларации и инструкции удаляются, содержимое ``script``/``style`` (в том числе незакрытых)
удаляется, остальной текст и ссылки на сущности сохраняются как введены. ``>`` и ``a < b``
не портятся: ``<`` вне начала тега парсер считает обычным текстом.

Результат устойчив к «склейке»: ``<<b>script>`` после удаления ``<b>`` дал бы новый тег, поэтому
проход повторяется до неизменного результата, а при исчерпании лимита проходов оставшиеся
``<`` у начала тегоподобных конструкций вырезаются (отказ в закрытую сторону).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Final

_RAW_TEXT_ELEMENTS: Final = frozenset({"script", "style"})
_MAX_PASSES: Final = 16
_TAG_START: Final = re.compile(r"<+(?=[A-Za-z/!?])")
# Завершающий символ, который скармливается парсеру после текста: без него ``&name`` в самом
# конце ввода (``AT&T``) парсер на ``close()`` теряет амперсанд. В результат не попадает.
_SENTINEL: Final = "\n"


class _Stripper(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._source = source
        # Смещения начала строк: позиция парсера (lineno, offset) -> индекс в исходной строке.
        self._line_starts = [0, *(m.end() for m in re.finditer("\n", source))]
        self._out: list[str] = []

    def result(self) -> str:
        return "".join(self._out)

    def _in_raw_text(self) -> bool:
        return self.cdata_elem in _RAW_TEXT_ELEMENTS

    def _reference_end(self, prefix: str, name: str) -> str:
        """``&name`` или ``&#name`` вместе с ``;``, если он стоял в исходном тексте."""
        lineno, offset = self.getpos()
        start = self._line_starts[lineno - 1] + offset
        text = f"{prefix}{name}"
        if self._source.startswith(text, start) and self._source.startswith(";", start + len(text)):
            return text + ";"
        return text

    def _is_final_chunk(self, data: str) -> bool:
        lineno, offset = self.getpos()
        start = self._line_starts[lineno - 1] + offset
        return data.endswith(_SENTINEL) and start + len(data) == len(self._source)

    def handle_data(self, data: str) -> None:
        if self._in_raw_text():
            return
        if self._is_final_chunk(data):
            data = data[: -len(_SENTINEL)]
        self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._in_raw_text():
            self._out.append(self._reference_end("&", name))

    def handle_charref(self, name: str) -> None:
        if not self._in_raw_text():
            self._out.append(self._reference_end("&#", name))


def _strip_once(text: str) -> str:
    source = text + _SENTINEL
    parser = _Stripper(source)
    parser.feed(source)
    parser.close()
    return parser.result()


def strip_html(text: str) -> str:
    """Текст комментария без HTML; повторный вызов на результате ничего не меняет."""
    current = text
    for _ in range(_MAX_PASSES):
        cleaned = _strip_once(current)
        if cleaned == current:
            return cleaned
        current = cleaned
    return _TAG_START.sub("", current)
