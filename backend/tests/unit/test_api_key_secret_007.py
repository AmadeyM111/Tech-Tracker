"""R7-T03: формат и секрет ключа агента (007: AC-41, FR-6, NFR-3; plan §4.2, PD-1).

Контракт ``app.core.security.api_keys``:
``generate_api_key() -> str``, ``is_api_key_format(value) -> bool``,
``api_key_digest(value) -> bytes`` (не формат -> ``ValueError`` без значения в тексте),
константы ``API_KEY_PREFIX``, ``API_KEY_RANDOM_BYTES``, ``API_KEY_FORMAT``,
``API_KEY_LEAK_PATTERN``.

Секрет не печатается: булевы значения вычисляются до ``assert``; в репозитории нет
литералов настоящих ключей (ключи собираются из байтов в рантайме).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from typing import Any

import pytest

from app.core.security import api_keys

FORMAT_RE = re.compile(r"gtk_[A-Za-z0-9_-]{43}", re.ASCII)
FIXED_BYTES = bytes(range(32))


def _key_from(raw: bytes) -> str:
    return "gtk_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_ac41_thousand_keys_are_pairwise_distinct_and_well_formed() -> None:
    """AC-41: 1 000 ключей попарно различны; каждый fullmatch формата; декодируется в 32 байта."""
    keys = [api_keys.generate_api_key() for _ in range(1000)]
    distinct = len(set(keys)) == 1000
    all_match = all(FORMAT_RE.fullmatch(k) is not None for k in keys)
    all_32 = all(len(base64.urlsafe_b64decode(k[4:] + "=")) == 32 for k in keys)
    all_len_47 = all(len(k) == 47 for k in keys)
    assert distinct, "ключи не попарно различны"
    assert all_match, "ключ не соответствует формату"
    assert all_32, "случайная часть не 32 байта"
    assert all_len_47, "длина ключа не 47"


def test_ac41_source_is_secrets_token_bytes_32(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-41 (256 бит): источник — secrets.token_bytes(32)."""
    calls: list[int] = []

    def fake_token_bytes(n: int | None = None) -> bytes:
        calls.append(n if n is not None else -1)
        return FIXED_BYTES

    monkeypatch.setattr(secrets, "token_bytes", fake_token_bytes)
    result = api_keys.generate_api_key()
    same = result == _key_from(FIXED_BYTES)
    assert same, "ключ не равен gtk_ + base64url(secrets.token_bytes(32)) без '='"
    assert calls == [32]


def test_ac41_constants_match_plan() -> None:
    assert api_keys.API_KEY_PREFIX == "gtk_"
    assert api_keys.API_KEY_RANDOM_BYTES == 32
    key = _key_from(FIXED_BYTES)
    assert api_keys.API_KEY_FORMAT.fullmatch(key) is not None
    assert api_keys.API_KEY_FORMAT.fullmatch(key + "A") is None
    assert api_keys.API_KEY_LEAK_PATTERN.fullmatch("gtk_" + "A" * 8) is not None
    assert api_keys.API_KEY_LEAK_PATTERN.fullmatch("gtk_" + "A" * 7) is None
    # R7-T16 (plan PD-11, §4.2): формат ключа не изменился
    assert api_keys.API_KEY_FORMAT.pattern == r"gtk_[A-Za-z0-9_-]{43}"
    assert api_keys.API_KEY_FORMAT.flags & re.ASCII
    # шаблон утечки: внутри допускаются / + % . и не-ASCII (ключ маскируется целиком)
    assert api_keys.API_KEY_LEAK_PATTERN.fullmatch("gtk_AAAA/AAA+%2F.я") is not None
    # совпадение обрывается перед разделителем контекста
    for sep in ['"', "'", "`", ")", "(", "&", ";", ",", "]", "[", "}", "{", "|", "<", ">"]:
        found = api_keys.API_KEY_LEAK_PATTERN.search("gtk_" + "A" * 8 + sep + "BBBBBBBB")
        assert found is not None and found.group(0) == "gtk_" + "A" * 8, f"разделитель {sep!r}"
    for space in [" ", "\n", "\t", "\xa0"]:
        found = api_keys.API_KEY_LEAK_PATTERN.search("gtk_" + "A" * 8 + space + "BBBBBBBB")
        assert found is not None and found.group(0) == "gtk_" + "A" * 8, f"пробел {space!r}"


def test_ac41_generated_key_is_format() -> None:
    assert api_keys.is_api_key_format(api_keys.generate_api_key()) is True


def _bad_formats() -> list[tuple[str, str]]:
    ok = _key_from(FIXED_BYTES)
    body = ok[4:]
    return [
        ("short-46", ok[:-1]),
        ("long-48", ok + "A"),
        ("plus", "gtk_" + body[:-1] + "+"),
        ("slash", "gtk_" + body[:-1] + "/"),
        ("padding", "gtk_" + body[:-1] + "="),
        ("non-ascii", "gtk_" + body[:-1] + "я"),
        ("upper-prefix", "GTK_" + body),
        ("no-prefix", body + "AAAA"),
        ("empty", ""),
        ("trailing-newline", ok + "\n"),
        ("leading-space", " " + ok),
    ]


@pytest.mark.parametrize(
    "value", [v for _, v in _bad_formats()], ids=[i for i, _ in _bad_formats()]
)
def test_ac41_not_a_format(value: str) -> None:
    """AC-41: 46/48 символов, + / =, не-ASCII, GTK_ — не формат."""
    result = api_keys.is_api_key_format(value)
    assert result is False


def test_ac41_digit_underscore_dash_alphabet_is_format() -> None:
    key = "gtk_" + "-_09azAZ" * 5 + "-_0"
    assert len(key) == 47
    assert api_keys.is_api_key_format(key) is True


def test_fr6_digest_is_sha256_32_bytes() -> None:
    """FR-6: в БД идёт sha256 секрета (bytea 32)."""
    key = api_keys.generate_api_key()
    digest = api_keys.api_key_digest(key)
    expected = hashlib.sha256(key.encode("ascii")).digest()
    assert isinstance(digest, bytes)
    assert len(digest) == 32
    same = digest == expected
    assert same, "дайджест не равен sha256(секрет)"


def test_fr6_digest_deterministic_and_distinct() -> None:
    a = _key_from(FIXED_BYTES)
    b = _key_from(bytes(reversed(FIXED_BYTES)))
    same_a = api_keys.api_key_digest(a) == api_keys.api_key_digest(a)
    differ = api_keys.api_key_digest(a) != api_keys.api_key_digest(b)
    assert same_a
    assert differ


def test_fr6_digest_does_not_contain_secret_bytes() -> None:
    key = _key_from(FIXED_BYTES)
    digest = api_keys.api_key_digest(key)
    leaked = key.encode("ascii")[4:12] in digest
    assert not leaked


@pytest.mark.parametrize(
    "value", [v for _, v in _bad_formats()], ids=[i for i, _ in _bad_formats()]
)
def test_fr6_digest_of_non_format_raises_without_value(value: str) -> None:
    """Не по формату -> ValueError; значение не попадает в текст исключения."""
    with pytest.raises(ValueError) as info:
        api_keys.api_key_digest(value)
    text = str(info.value) + repr(info.value) + repr(info.value.args)
    body = value[4:] if len(value) > 12 else value
    leaked = len(body) >= 8 and body[:8] in text
    assert not leaked, "значение попало в текст исключения"


def test_fr6_digest_of_non_str_does_not_succeed() -> None:
    not_a_str: Any = None
    with pytest.raises((ValueError, TypeError)):
        api_keys.api_key_digest(not_a_str)
