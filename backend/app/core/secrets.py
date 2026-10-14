"""Секретный ключ приложения и безопасная запись приватных файлов (plan §4.2, D-19, D-20, FR-6).

- ``write_private_file``: атомарное исключающее создание файла с режимом ``0600``;
- ``ensure_private_dir``: каталог секретов с режимом ``0700``;
- ``ensure_secret_key``: ключ из настроек или файл ``data_dir/secrets/secret_key``.

Содержимое файлов и значение ключа не попадают ни в сообщения исключений, ни в логи (FR-57).
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
from pathlib import Path
from typing import Final

from app.core.config import Settings

SECRET_KEY_FILE: Final = "secret_key"
PLACEHOLDER_SECRET_KEY: Final = "change-me"  # значение из старого .env.example: ключом не считается
GENERATED_KEY_BYTES: Final = 32  # 256 бит
MIN_ENV_KEY_BYTES: Final = 32  # минимальная длина SECRET_KEY из окружения (в байтах UTF-8)

_PRIVATE_FILE_MODE: Final = 0o600
_PRIVATE_DIR_MODE: Final = 0o700
_O_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)

_log = logging.getLogger(__name__)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _fsync_dir(directory: Path) -> None:
    """Best-effort: сохраняет запись каталога; сбой не критичен (файл уже на месте)."""
    try:
        fd = os.open(directory, os.O_RDONLY | _O_CLOEXEC)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def write_private_file(path: Path, content: str) -> None:
    """Создаёт ``path`` с режимом 0600 и содержимым ``content``; существующий путь не трогает.

    Содержимое пишется во временный файл (``O_CREAT|O_EXCL``, режим 0600 независимо от umask)
    в том же каталоге и публикуется жёсткой ссылкой ``link(tmp, path)``: операция атомарна,
    не перезаписывает существующий путь и не разыменовывает символические ссылки (в том числе
    висячие) — тогда ``FileExistsError``. Читатель видит либо отсутствие файла, либо файл целиком.
    Временный файл удаляется всегда. Исключения содержат только пути и коды ошибок ОС.
    """
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        # args исходного исключения содержат строку целиком
        raise ValueError("Содержимое файла не кодируется в UTF-8") from None

    directory = path.parent
    tmp = directory / f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC
    fd = os.open(tmp, flags, _PRIVATE_FILE_MODE)
    try:
        try:
            os.fchmod(fd, _PRIVATE_FILE_MODE)
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    _fsync_dir(directory)


def ensure_private_dir(path: Path) -> None:
    """Создаёт каталог с режимом 0700, если его нет; существующий каталог не меняет."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(path, _PRIVATE_DIR_MODE)
    except FileExistsError:
        if not path.is_dir():
            raise NotADirectoryError(f"{path} существует и не является каталогом") from None
        return
    # umask мог урезать права при создании
    os.chmod(path, _PRIVATE_DIR_MODE)


def _read_key_file(path: Path) -> bytes:
    """Читает ключ из файла: hex (как пишет ``ensure_secret_key``) или произвольные байты."""
    raw = path.read_bytes().strip()
    if not raw or raw.lower() == PLACEHOLDER_SECRET_KEY.encode():
        raise RuntimeError(f"Файл секретного ключа пуст или содержит заглушку: {path}")
    try:
        return bytes.fromhex(raw.decode("ascii"))
    except ValueError:  # не hex: ключ задан оператором как есть
        return raw


def _key_from_settings(settings: Settings) -> bytes | None:
    if settings.secret_key is None:
        return None
    value = settings.secret_key.get_secret_value()
    if not value.strip():
        return None  # SECRET_KEY="" == ключа нет (ревью T03)
    if value.strip().lower() == PLACEHOLDER_SECRET_KEY:
        _log.warning("SECRET_KEY содержит значение-заглушку и игнорируется")
        return None
    try:
        key = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("SECRET_KEY не кодируется в UTF-8") from None
    if len(key) < MIN_ENV_KEY_BYTES:
        # без отката на файл: короткий ключ из окружения — ошибка конфигурации; значение не в тексте
        raise ValueError(
            f"SECRET_KEY короче {MIN_ENV_KEY_BYTES} байт: задайте длинный случайный ключ "
            "или оставьте переменную пустой (ключ будет создан в каталоге секретов)"
        )
    return key


def ensure_secret_key(settings: Settings) -> bytes:
    """Возвращает секретный ключ приложения (D-20, FR-6).

    1. Непустой ``settings.secret_key`` (не ``change-me`` без учёта регистра и пробелов) —
       приоритетнее файла; короче 32 байт — ``ValueError`` (значение в сообщение не попадает,
       на файл не откатываемся).
    2. Иначе файл ``secrets_dir/secret_key``; при отсутствии создаётся один раз: 32 случайных
       байта в hex, режим 0600, каталог 0700. Повторные и конкурентные вызовы возвращают
       один и тот же ключ; существующий файл никогда не пересоздаётся.
    """
    from_settings = _key_from_settings(settings)
    if from_settings is not None:
        return from_settings

    path = settings.secrets_dir / SECRET_KEY_FILE
    try:
        return _read_key_file(path)
    except FileNotFoundError:
        pass

    ensure_private_dir(settings.secrets_dir)
    key = secrets.token_bytes(GENERATED_KEY_BYTES)
    try:
        write_private_file(path, key.hex() + "\n")
    except FileExistsError:
        # проиграли гонку: файл опубликован целиком (link), читаем чужой ключ
        return _read_key_file(path)
    return key
