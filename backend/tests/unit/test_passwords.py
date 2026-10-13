"""Юнит-тесты паролей (plan §4.2, §7.3; T08).

AC-3, AC-27, AC-28, AC-115; FR-2, FR-52, FR-53, FR-57; OI-108, OI-111.
БД и сеть не нужны. Argon2 — дешёвые параметры (общие условия tasks.md).
"""

from __future__ import annotations

import hashlib
import random
import threading
from pathlib import Path
from typing import Any

import pytest

SHA256 = "fa1ea0cf2f673458b58be3a7171d2b7fc6f2e704b4691e69c13a9a8511f5cf31"
COMMIT = "913b327317496d062bcc7cace524aaad8a693be2"
DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "security" / "data"
LIST_FILE = DATA_DIR / "common-passwords-10k.txt"
NOTICE_FILE = DATA_DIR / "NOTICE.md"

CHEAP: dict[str, int] = {"time_cost": 1, "memory_cost_kib": 1024, "parallelism": 1}


@pytest.fixture
def pw() -> Any:
    from app.core.security import passwords

    return passwords


@pytest.fixture
def cp() -> Any:
    from app.core.security import common_passwords

    return common_passwords


@pytest.fixture
def hasher(pw: Any) -> Any:
    return pw.PasswordHasher(**CHEAP)


def _list_entries() -> list[str]:
    return LIST_FILE.read_text(encoding="utf-8").split("\n")[:-1]


def _policy_code(pw: Any, password: str) -> str | None:
    """Код отказа политики или None, если пароль принят."""
    try:
        pw.validate_new_password(password)
    except pw.PasswordPolicyError as exc:
        return str(exc.code)
    return None


# ---- PasswordHasher (AC-3, FR-2) ----


def test_ac3_hash_is_argon2id_and_has_no_plaintext(hasher: Any) -> None:
    password = "correct horse battery staple"
    value = hasher.hash(password)
    assert isinstance(value, str)
    assert value.startswith("$argon2id$")
    assert password not in value


def test_ac3_verify_true_for_correct_password(hasher: Any) -> None:
    value = hasher.hash("correct horse battery staple")
    assert hasher.verify(value, "correct horse battery staple") is True


def test_ac3_verify_false_for_wrong_password(hasher: Any) -> None:
    value = hasher.hash("correct horse battery staple")
    assert hasher.verify(value, "correct horse battery stapl") is False
    assert hasher.verify(value, "Correct horse battery staple") is False
    assert hasher.verify(value, "") is False


def test_fr2_different_salts_give_different_hashes(hasher: Any) -> None:
    first = hasher.hash("same password 123")
    second = hasher.hash("same password 123")
    assert first != second
    assert hasher.verify(first, "same password 123") is True
    assert hasher.verify(second, "same password 123") is True


def test_fr2_parameters_come_from_arguments(pw: Any) -> None:
    from argon2 import extract_parameters

    params = extract_parameters(pw.PasswordHasher(**CHEAP).hash("some password 1234"))
    assert (params.time_cost, params.memory_cost, params.parallelism) == (1, 1024, 1)

    other = pw.PasswordHasher(time_cost=2, memory_cost_kib=2048, parallelism=2)
    params = extract_parameters(other.hash("some password 1234"))
    assert (params.time_cost, params.memory_cost, params.parallelism) == (2, 2048, 2)


def test_fr2_verify_works_across_hasher_instances_with_other_params(pw: Any) -> None:
    value = pw.PasswordHasher(**CHEAP).hash("some password 1234")
    other = pw.PasswordHasher(time_cost=2, memory_cost_kib=2048, parallelism=1)
    assert other.verify(value, "some password 1234") is True


def test_fr2_unicode_password_roundtrip(hasher: Any) -> None:
    password = "пароль-с-юникодом-😀"
    assert hasher.verify(hasher.hash(password), password) is True


# ---- needs_rehash / dummy_verify ----


def test_needs_rehash_false_for_own_parameters(hasher: Any) -> None:
    assert hasher.needs_rehash(hasher.hash("some password 1234")) is False


@pytest.mark.parametrize(
    "changed",
    [
        {"time_cost": 2},
        {"memory_cost_kib": 2048},
        {"parallelism": 2},
    ],
)
def test_needs_rehash_true_when_parameters_change(
    pw: Any, hasher: Any, changed: dict[str, int]
) -> None:
    value = hasher.hash("some password 1234")
    stronger = pw.PasswordHasher(**{**CHEAP, **changed})
    assert stronger.needs_rehash(value) is True


def test_dummy_verify_returns_none_and_does_not_raise(hasher: Any) -> None:
    assert hasher.dummy_verify("whatever password") is None
    assert hasher.dummy_verify("") is None
    assert hasher.dummy_verify("пароль-😀" * 20) is None


def test_dummy_verify_does_not_break_real_verification(hasher: Any) -> None:
    value = hasher.hash("some password 1234")
    hasher.dummy_verify("some password 1234")
    assert hasher.verify(value, "some password 1234") is True


# ---- hash_in_thread / verify_in_thread ----


async def test_hash_in_thread_returns_argon2id_hash(pw: Any, hasher: Any) -> None:
    value = await pw.hash_in_thread(hasher, "threaded password 1")
    assert value.startswith("$argon2id$")
    assert hasher.verify(value, "threaded password 1") is True


async def test_verify_in_thread_matches_sync_result(pw: Any, hasher: Any) -> None:
    value = hasher.hash("threaded password 1")
    assert await pw.verify_in_thread(hasher, value, "threaded password 1") is True
    assert await pw.verify_in_thread(hasher, value, "threaded password 2") is False


async def test_in_thread_helpers_run_off_the_event_loop_thread(pw: Any) -> None:
    seen: dict[str, int] = {}

    class Spy(pw.PasswordHasher):  # type: ignore[misc]
        def hash(self, password: str) -> str:
            seen["hash"] = threading.get_ident()
            return super().hash(password)  # type: ignore[no-any-return]

        def verify(self, password_hash: str, password: str) -> bool:
            seen["verify"] = threading.get_ident()
            return super().verify(password_hash, password)  # type: ignore[no-any-return]

    spy = Spy(**CHEAP)
    main = threading.get_ident()
    value = await pw.hash_in_thread(spy, "threaded password 1")
    assert await pw.verify_in_thread(spy, value, "threaded password 1") is True
    assert seen["hash"] != main
    assert seen["verify"] != main


# ---- validate_new_password (AC-27, AC-28, AC-115, FR-52, FR-53, FR-57) ----


def test_policy_min_length_constant(pw: Any) -> None:
    assert pw.MIN_PASSWORD_LENGTH == 12


def test_ac27_eleven_chars_rejected_as_too_short(pw: Any) -> None:
    with pytest.raises(pw.PasswordPolicyError) as info:
        pw.validate_new_password("qzxwvkjhgfd")  # 11, нет в списке
    assert info.value.code == "password_too_short"


def test_ac27_twelve_lowercase_not_in_list_accepted(pw: Any) -> None:
    assert pw.validate_new_password("qzxwvkjhgfdl") is None


def test_fr52_no_composition_rules(pw: Any) -> None:
    assert _policy_code(pw, "aaaaaaaaaaaaaaaa") is None
    assert _policy_code(pw, "zzzzzzzzzzzz") is None


def test_ac28_common_password_with_length_ge_12_rejected(pw: Any) -> None:
    with pytest.raises(pw.PasswordPolicyError) as info:
        pw.validate_new_password("unbelievable")
    assert info.value.code == "password_too_common"


def test_ac28_every_common_entry_ge_12_rejected(pw: Any) -> None:
    long_entries = [e for e in _list_entries() if len(e) >= 12]
    assert long_entries
    for entry in long_entries:
        assert _policy_code(pw, entry) == "password_too_common", entry


def test_ac115_case_differing_password_is_not_common(pw: Any) -> None:
    assert _policy_code(pw, "unbelievable") == "password_too_common"
    assert _policy_code(pw, "Unbelievable") is None
    assert _policy_code(pw, "unbelievablE") is None


def test_ac115_one_lowercase_letter_uppercased_is_accepted_for_all_long_entries(
    pw: Any, cp: Any
) -> None:
    checked = 0
    for entry in (e for e in _list_entries() if len(e) >= 12):
        idx = next((i for i, ch in enumerate(entry) if ch.islower()), None)
        if idx is None:
            continue
        variant = entry[:idx] + entry[idx].upper() + entry[idx + 1 :]
        if cp.is_common_password(variant):
            continue  # сам вариант есть в списке — это отдельная запись
        assert _policy_code(pw, variant) is None, variant
        checked += 1
    assert checked >= 1


def test_ac27_length_counted_in_characters_not_bytes(pw: Any) -> None:
    assert _policy_code(pw, "я" * 11) == "password_too_short"
    assert _policy_code(pw, "я" * 12) is None
    assert _policy_code(pw, "😀" * 11) == "password_too_short"
    assert _policy_code(pw, "😀" * 12) is None
    # 6 эмодзи = 24 байта UTF-8, но 6 символов
    assert _policy_code(pw, "😀" * 6) == "password_too_short"


def test_fr52_empty_and_whitespace_only(pw: Any) -> None:
    assert _policy_code(pw, "") == "password_too_short"
    assert _policy_code(pw, " ") == "password_too_short"
    assert _policy_code(pw, " " * 11) == "password_too_short"
    assert _policy_code(pw, "\t\n ") == "password_too_short"


def test_fr57_error_message_does_not_contain_password(pw: Any) -> None:
    secret_short = "Sh0rt-Pw-xQ"  # 11 символов
    secret_common = "unbelievable"
    for secret in (secret_short, secret_common):
        with pytest.raises(pw.PasswordPolicyError) as info:
            pw.validate_new_password(secret)
        exc = info.value
        assert secret not in str(exc)
        assert secret not in repr(exc)
        assert all(secret not in str(a) for a in exc.args)
        assert secret not in repr(vars(exc))


# ---- generate_password ----


def test_generate_default_length_is_20_and_passes_policy(pw: Any) -> None:
    value = pw.generate_password()
    assert isinstance(value, str)
    assert len(value) == 20
    assert pw.validate_new_password(value) is None


@pytest.mark.parametrize("length", [12, 16, 40])
def test_generate_respects_length_parameter(pw: Any, length: int) -> None:
    value = pw.generate_password(length)
    assert len(value) == length
    assert pw.validate_new_password(value) is None


def test_generate_alphabet_is_ascii_letters_and_digits(pw: Any) -> None:
    sample = "".join(pw.generate_password(40) for _ in range(50))
    assert all(ch.isascii() and ch.isalnum() for ch in sample)
    assert any(ch.isdigit() for ch in sample)
    assert any(ch.isalpha() for ch in sample)


def test_generate_values_are_unique_in_1000_calls(pw: Any) -> None:
    values = {pw.generate_password() for _ in range(1000)}
    assert len(values) == 1000


def test_generate_is_independent_of_random_seed(pw: Any) -> None:
    """secrets, а не random: сброс seed не делает результат повторяемым."""
    random.seed(12345)
    first = pw.generate_password()
    random.seed(12345)
    second = pw.generate_password()
    assert first != second


# ---- common_passwords (plan §7.3, ADR-0004, FR-53) ----


def test_data_file_sha256_matches(cp: Any) -> None:
    assert cp.COMMON_PASSWORDS_SHA256 == SHA256
    assert hashlib.sha256(LIST_FILE.read_bytes()).hexdigest() == SHA256


def test_data_file_has_10000_unique_nonempty_utf8_lines() -> None:
    raw = LIST_FILE.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    entries = raw.decode("utf-8").split("\n")[:-1]
    assert len(entries) == 10_000
    assert all(entries)
    assert len(set(entries)) == 10_000


def test_data_file_has_ten_entries_of_length_ge_12() -> None:
    entries = _list_entries()
    long_entries = {e for e in entries if len(e) >= 12}
    assert len([e for e in entries if len(e) >= 12]) == 10
    assert long_entries == {
        "masterbating",
        "unbelievable",
        "businessbabe",
        "contortionist",
        "masterbaiting",
        "masturbation",
        "pornographic",
        "scandinavian",
        "films+pic+galeries",
        "motherfucker",
    }


@pytest.mark.parametrize("known", ["password", "123456", "unbelievable"])
def test_is_common_password_known_entries(cp: Any, known: str) -> None:
    assert known in _list_entries()
    assert cp.is_common_password(known) is True


def test_is_common_password_covers_whole_file(cp: Any) -> None:
    assert all(cp.is_common_password(e) for e in _list_entries())


def test_is_common_password_exact_match_case_sensitive(cp: Any) -> None:
    assert cp.is_common_password("Unbelievable") is False
    assert cp.is_common_password("UNBELIEVABLE") is False
    assert cp.is_common_password("unbelievable ") is False
    assert cp.is_common_password(" unbelievable") is False


def test_is_common_password_unknown_and_empty(cp: Any) -> None:
    assert cp.is_common_password("qzxwvkjhgfdl") is False
    assert cp.is_common_password("") is False


def test_common_passwords_loaded_from_package_data_without_network(
    cp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def _no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access is forbidden (NFR-4)")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    assert cp.is_common_password("password") is True


def test_notice_has_source_commit_and_mit_text() -> None:
    text = NOTICE_FILE.read_text(encoding="utf-8")
    assert "github.com/danielmiessler/SecLists" in text
    assert "Passwords/Common-Credentials/10k-most-common.txt" in text
    assert COMMIT in text
    assert "MIT" in text
    assert "Permission is hereby granted, free of charge" in text
    assert "Daniel Miessler" in text
    assert "2018" in text
    assert "WITHOUT WARRANTY OF ANY KIND" in text
