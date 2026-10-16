"""T28: статическая проверка документации R1.0 (без docker).

Покрывает NFR-11 (часть), NFR-3 (инструкция), FR-63, OI-70.
Ожидаемые якоря README (порядок языковых частей не важен):
``## Быстрый старт`` (русская часть) и ``## Quick start`` (английская часть);
часть заканчивается там, где начинается другая, или в конце файла.
"""

# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.infra_static

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
DATA_MODEL = ROOT / "docs" / "data-model.md"

RU_HEADING = "## Быстрый старт"
EN_HEADING = "## Quick start"


def _text(path: Path) -> str:
    assert path.is_file(), f"нет файла {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def _parts() -> tuple[str, str]:
    """(русская часть, английская часть) README."""
    text = _text(README)
    ru = re.search(rf"^{re.escape(RU_HEADING)}\s*$", text, re.M)
    en = re.search(rf"^{re.escape(EN_HEADING)}\s*$", text, re.M)
    assert ru, f"в README нет заголовка «{RU_HEADING}»"
    assert en, f"в README нет заголовка «{EN_HEADING}»"
    if ru.start() < en.start():
        return text[ru.start() : en.start()], text[en.start() :]
    return text[ru.start() :], text[en.start() : ru.start()]


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.I | re.S) is not None


# --- 1. README: команды и разделы ------------------------------------------------

QUICK_START_COMMANDS = [
    "git clone",
    "cp .env.example .env",
    "docker compose up",
    "docker compose exec api cat /data/secrets/initial-admin-password.txt",
]


def test_nfr11_readme_has_ru_and_en_parts() -> None:
    ru, en = _parts()
    assert re.search(r"[а-яё]{4,}", ru, re.I), "русская часть без русского текста"
    assert re.search(r"\b(the|and|to|your)\b", en, re.I), "английская часть без английского"


@pytest.mark.parametrize("command", QUICK_START_COMMANDS)
def test_nfr11_quick_start_command_in_both_languages(command: str) -> None:
    ru, en = _parts()
    assert command in ru, f"нет «{command}» в русской части"
    assert command in en, f"нет «{command}» в английской части"


# (регэксп для русской части, регэксп для английской части, описание)
PROSE_TERMS: list[tuple[str, str, str]] = [
    (r"самоподпис", r"self-signed", "FR-63 самоподписанный сертификат"),
    (r"браузер", r"browser", "предупреждение браузера"),
    (
        r"tls\.crt.*tls\.key|tls\.key.*tls\.crt",
        r"tls\.crt.*tls\.key|tls\.key.*tls\.crt",
        "tls.crt/tls.key",
    ),
    (r"deploy/tls", r"deploy/tls", "каталог deploy/tls"),
    (
        r"HTTP_PORT.*HTTPS_PORT|HTTPS_PORT.*HTTP_PORT",
        r"HTTP_PORT.*HTTPS_PORT|HTTPS_PORT.*HTTP_PORT",
        "смена портов",
    ),
    (
        r"downgrade 0002.*журнал|журнал.*downgrade 0002",
        r"downgrade 0002.*(audit|journal|log|event)|(audit|journal|log|event).*downgrade 0002",
        "downgrade 0002 удаляет журнал",
    ),
    (r"128\s*МиБ", r"128\s*MiB", "m=128 МиБ"),
    (r"900\s*МиБ", r"900\s*MiB", "пик ~900 МиБ"),
    (r"параллельн", r"concurrent|parallel", "лимит параллельных хешей"),
    (r"uvicorn\.run", r"uvicorn\.run", "не uvicorn.run(app)"),
    (r"--forwarded-allow-ips", r"--forwarded-allow-ips", "forwarded-allow-ips"),
    (r"SECRET_KEY.*32|32.*SECRET_KEY", r"SECRET_KEY.*32|32.*SECRET_KEY", "SECRET_KEY >= 32 байт"),
    (r"change-me", r"change-me", "заглушка change-me"),
    (r"/data/secrets/secret_key", r"/data/secrets/secret_key", "ключ по умолчанию"),
    (
        r"POSTGRES_PASSWORD.*(кодиров|@)",
        r"POSTGRES_PASSWORD.*(encod|@)",
        "POSTGRES_PASSWORD без URL-кодирования",
    ),
    (
        r"INITIAL_ADMIN_LOGIN.*пробел",
        r"INITIAL_ADMIN_LOGIN.*(space|whitespace)",
        "INITIAL_ADMIN_LOGIN без пробелов",
    ),
    (r"tls-generated", r"tls-generated", "том tls-generated"),
    (r"TLS_SERVER_NAME", r"TLS_SERVER_NAME", "смена TLS_SERVER_NAME"),
    (r"SAN", r"SAN", "SAN: IP как DNS"),
    (r"access-log|access_log|журнал доступа", r"access[- _]log", "access-log nginx пишет query"),
    (r"query|строк[аиу] запроса|параметр", r"query", "query в access-log"),
    (r"30\s*с", r"30\s*s(ec)?", "таймаут 30 с"),
    (r"60\s*с", r"60\s*s(ec)?", "таймаут 60 с"),
    (r"unless-stopped", r"unless-stopped", "restart: unless-stopped"),
    (r"lock_timeout", r"lock_timeout", "lock_timeout=0"),
    (r"up --wait|--wait", r"up --wait|--wait", "up --wait висит"),
    (r"/healthz", r"/healthz", "healthz"),
    (r"down -v", r"down -v", "infra_stack требует свежий стек"),
    (r"infra_stack", r"infra_stack", "маркер infra_stack"),
    (r"TEST_DATABASE_URL", r"TEST_DATABASE_URL", "TEST_DATABASE_URL"),
    (r"pytest", r"pytest", "запуск тестов"),
    (r"\^22\.12 \|\| \^24 \|\| >=26", r"\^22\.12 \|\| \^24 \|\| >=26", "требование к Node"),
    (r"shim|proto", r"shim|proto", "подсказка про node shim"),
    (r"-f deploy/compose\.dev\.yml", r"-f deploy/compose\.dev\.yml", "dev-compose"),
    (r"set -a", r"set -a", "set -a"),
    (r"\. deploy/dev\.env\.example", r"\. deploy/dev\.env\.example", "загрузка dev.env.example"),
    (r"set \+a", r"set \+a", "set +a"),
]


@pytest.mark.parametrize(("ru_re", "en_re", "label"), PROSE_TERMS, ids=[t[2] for t in PROSE_TERMS])
def test_nfr11_readme_term_in_both_languages(ru_re: str, en_re: str, label: str) -> None:
    ru, en = _parts()
    assert _has(ru, ru_re), f"русская часть README: нет «{label}» (/{ru_re}/)"
    assert _has(en, en_re), f"английская часть README: нет «{label}» (/{en_re}/)"


def test_nfr11_readme_no_delete_in_ui_note() -> None:
    """Нет UI/эндпоинта удаления учётных записей (FR-16, пользователи не удаляются)."""
    ru, en = _parts()
    assert _has(ru, r"(не удал|нельзя удалить|удалени[ея].{0,40}(нет|не предусмотр))"), (
        "русская часть: нет пометки об отсутствии удаления учётных записей"
    )
    assert _has(
        en,
        r"(cannot be deleted|not deleted|no (ui|endpoint|button).{0,40}delet|delet.{0,40}(not (available|supported)|is not))",
    ), "английская часть: нет пометки об отсутствии удаления учётных записей"


# --- 2. ссылки на файлы ------------------------------------------------------------

PATH_RE = re.compile(r"(?:deploy|docs|scripts|specs)/[\w./*-]+")


def _readme_paths() -> set[str]:
    text = _text(README)
    out: set[str] = set()
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^[a-z][a-z0-9+.-]*:|^#|^mailto:", target, re.I):
            continue
        out.add(target.split("#", 1)[0])
    for code in re.findall(r"`([^`\n]+)`", text):
        out.update(PATH_RE.findall(code))
    for line in re.findall(r"^(?:    |\t).*$", text, re.M):
        out.update(PATH_RE.findall(line))
    return {p.rstrip(".,;:") for p in out if p}


def test_nfr11_readme_file_links_exist() -> None:
    paths = _readme_paths()
    assert paths, "в README нет ссылок на файлы репозитория"
    missing = []
    for rel in sorted(paths):
        if "*" in rel:
            continue
        if not (ROOT / rel).exists():
            missing.append(rel)
    assert not missing, f"README ссылается на несуществующие пути: {missing}"


def test_nfr11_readme_links_cover_key_docs() -> None:
    paths = _readme_paths()
    for must in ("deploy/compose.dev.yml", "deploy/dev.env.example", "docs/data-model.md"):
        assert must in paths, f"README не ссылается на {must}"


# --- 3. docs/data-model.md ------------------------------------------------------------


def _model_tables() -> dict[str, list[str]]:
    import app.domain.registry  # noqa: F401  (регистрирует модели в metadata)
    from app.core.models import Base

    return {name: [c.name for c in t.columns] for name, t in Base.metadata.tables.items()}


def _table_section(text: str, table: str) -> str | None:
    """Текст от заголовка, упоминающего таблицу, до заголовка того же или старшего уровня."""
    for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M):
        if re.search(rf"(?<![\w]){re.escape(table)}(?![\w])", m.group(2)):
            level = len(m.group(1))
            rest = text[m.end() :]
            nxt = re.search(rf"^#{{1,{level}}}\s", rest, re.M)
            return rest[: nxt.start()] if nxt else rest
    return None


def test_nfr11_data_model_exists() -> None:
    assert DATA_MODEL.is_file(), "нет docs/data-model.md"


def test_nfr11_data_model_covers_every_table_and_column() -> None:
    text = _text(DATA_MODEL)
    problems: list[str] = []
    for table, columns in sorted(_model_tables().items()):
        section = _table_section(text, table)
        if section is None:
            problems.append(f"{table}: нет раздела с заголовком, содержащим имя таблицы")
            continue
        for col in columns:
            if not re.search(rf"(?<![\w]){re.escape(col)}(?![\w])", section):
                problems.append(f"{table}.{col}: столбец не описан")
    assert not problems, "docs/data-model.md неполон:\n" + "\n".join(problems)


def test_nfr11_data_model_documents_append_only_and_indexes() -> None:
    text = _text(DATA_MODEL)
    section = _table_section(text, "domain_event")
    assert section is not None, "нет раздела domain_event"
    assert _has(section, r"append-only|только дописывается|только добавлени"), "нет append-only"
    assert _has(section, r"триггер|trigger"), "нет упоминания триггеров"
    assert _has(section, r"UPDATE") and _has(section, r"DELETE") and _has(section, r"TRUNCATE")
    assert _has(section, r"индекс|index"), "нет индексов domain_event"
    assert "(workspace_id, id DESC)" in section or "workspace_id, id DESC" in section
    assert _has(section, r"in_audit")


# --- 4. AGENTS.md ----------------------------------------------------------------------

DEV_DB_COMMAND = (
    "docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db"
)


def _commands_block(text: str) -> str:
    m = re.search(r"^## Команды\s*$(.*?)(?=^## )", text, re.M | re.S)
    assert m, "в AGENTS.md нет раздела «Команды»"
    return m.group(1)


def test_oi70_agents_commands_has_dev_db_command() -> None:
    block = _commands_block(_text(AGENTS))
    assert DEV_DB_COMMAND in block, "в блоке «Команды» нет команды dev-БД из plan D-18"
    assert "определяется в plan.md" not in block, "комментарий-заглушка не заменён"


def test_oi70_agents_commands_has_dev_env_and_test_url() -> None:
    block = _commands_block(_text(AGENTS))
    assert "TEST_DATABASE_URL" in block
    assert "set -a" in block and "deploy/dev.env.example" in block and "set +a" in block


@pytest.mark.parametrize(
    "rule",
    [
        "Слои не смешиваются.",
        "Мультиарендность.",
        "Проверка прав — в сервисном слое",
        "Правка существующих применённых миграций запрещена.",
        "Ответ с ошибкой —",
        "Ломающие изменения API требуют",
        "Деньги",
        "Никаких float.",
        "журнал аудита; журнал",
        "TypeScript strict, `any` запрещён.",
        "Не выполнять `git push` и не трогать чужие ветки.",
        "Не ослаблять тесты и проверки прав, чтобы прогон стал зелёным.",
        "Не менять `docs/brief/*`",
        "Не запускать деструктивные операции с БД вне тестового окружения",
        "Не добавлять телеметрию, аналитику и внешние вызовы без явного решения в ADR.",
        "При противоречии ТЗ и спецификации остановись и спроси, не выбирай сам.",
    ],
)
def test_oi70_agents_rules_unchanged(rule: str) -> None:
    assert rule in _text(AGENTS), f"правило AGENTS.md изменено или удалено: {rule}"


# --- 5. T28 attempt 2: точность утверждений README (ревью) ------------------------------


def _windows(text: str, needle: str, radius: int) -> list[str]:
    out = []
    for m in re.finditer(needle, text):
        out.append(text[max(0, m.start() - radius) : m.end() + radius])
    return out


def _item(text: str, needle: str) -> str:
    """Пункт маркированного списка (с «- » в колонке 0), содержащий needle (регэксп)."""
    for chunk in re.split(r"\n(?=- )", text):
        piece = chunk.split("\n\n")[0]
        if re.search(needle, piece):
            return piece
    raise AssertionError(f"нет пункта списка с /{needle}/")


def test_t28_api_start_not_via_cli() -> None:
    """Ревью 1: у CLI нет команды запуска API."""
    ru, en = _parts()
    for name, part in (("ru", ru), ("en", en)):
        wins = _windows(part, r"uvicorn\.run", 200)
        assert wins, f"{name}: нет uvicorn.run"
        for w in wins:
            assert not re.search(r"\bCLI\b", w), f"{name}: запуск API «через CLI»: {w!r}"
        assert "uvicorn app.main:app" in part, f"{name}: нет uvicorn app.main:app"


def test_t28_startup_lock_says_unhealthy_not_hangs() -> None:
    """Ревью 2: up --wait завершается ошибкой, а не висит."""
    ru, en = _parts()
    for name, part in (("ru", ru), ("en", en)):
        item = _item(part, r"lock_timeout = 0")
        assert re.search(r"unhealthy", item, re.I), f"{name}: нет «unhealthy» в пункте блокировок"
        assert not re.search(r"виси|будет висеть|hangs?\b", item, re.I), f"{name}: «висит/hangs»"


def test_t28_tls_name_change_sequence() -> None:
    """Ревью 3: down (без -v), затем docker volume rm ... tls-generated."""
    ru, en = _parts()
    for name, part in (("ru", ru), ("en", en)):
        item = _item(part, r"_tls-generated")
        assert re.search(r"docker compose down(?! -v)", item), f"{name}: нет `docker compose down`"
        assert "docker volume rm" in item, f"{name}: нет `docker volume rm`"
        assert item.index("docker compose down") < item.index("docker volume rm"), name


def test_t28_san_ip_tied_to_tls_server_name() -> None:
    """Ревью 4: IP в TLS_SERVER_NAME попадает в SAN как DNS."""
    ru, en = _parts()
    for name, part in (("ru", ru), ("en", en)):
        item = _item(part, r"\bSAN\b")
        assert "TLS_SERVER_NAME" in item, f"{name}: SAN без привязки к TLS_SERVER_NAME"
        assert re.search(r"\bIP\b", item) and re.search(r"\bDNS\b", item), name
        for w in _windows(part, r"по IP-адресу|by IP address", 0):
            assert w and "TLS_SERVER_NAME" in item, name


def test_t28_secret_key_rules() -> None:
    """Ревью 5: короче 32 байт - ошибка запуска; change-me игнорируется, не отклоняется."""
    ru, en = _parts()
    ru_item = _item(ru, r"change-me")
    en_item = _item(en, r"change-me")
    assert "/data/secrets/secret_key" in ru_item and "/data/secrets/secret_key" in en_item
    assert re.search(r"игнор", ru_item, re.I), "ru: change-me должен быть «игнорируется»"
    assert re.search(r"ignored", en_item, re.I), "en: change-me must be «ignored»"
    assert not re.search(r"отклоня", ru_item, re.I), "ru: «отклоняется»"
    assert not re.search(r"rejected", en_item, re.I), "en: «rejected»"
    assert re.search(r"без учёта регистра", ru_item, re.I), "ru: нет «без учёта регистра»"
    assert re.search(r"case-insensitive|case insensitive|ignoring case", en_item, re.I), "en"
    assert re.search(r"ошибк|не запустится|не запуска", ru_item, re.I), "ru: нет ошибки запуска"
    assert re.search(r"error|fails? to start|will not start", en_item, re.I), "en: no startup error"


def test_t28_postgres_password_only_at_breaks() -> None:
    """Ревью 6: ломает только @; : / % не перечисляются как ломающие."""
    ru, en = _parts()
    for name, part, plain in (
        ("ru", ru, r"только буквы и цифры|буквы и цифры"),
        ("en", en, r"letters and digits"),
    ):
        item = _item(part, r"POSTGRES_PASSWORD")
        assert "@" in item, f"{name}: нет @"
        assert not re.search(r"[@:/%]\s*[,]?\s+[@:/%]", item), f"{name}: перечень «@ : / %»"
        assert re.search(plain, item, re.I), f"{name}: нет «буквы и цифры»"


def test_t28_readme_dev_db_and_test_url_match_code() -> None:
    from tests.db_support import DEFAULT_TEST_DATABASE_URL

    ru, en = _parts()
    for name, part in (("ru", ru), ("en", en)):
        assert DEV_DB_COMMAND in part, f"{name}: нет команды dev-БД"
        assert f"export TEST_DATABASE_URL={DEFAULT_TEST_DATABASE_URL}" in part, name
    assert f"export TEST_DATABASE_URL={DEFAULT_TEST_DATABASE_URL}" in _commands_block(_text(AGENTS))


INFRA_TOKENS = [
    "GT_INFRA_STACK=1",
    "GT_INFRA_PROJECT=gostracker-infratest",
    "HTTP_PORT=18080",
    "HTTPS_PORT=18443",
    "-m infra_stack",
    "-p gostracker-infratest",
]


def test_t28_infra_stack_command_matches_stack_support() -> None:
    support = (Path(__file__).parent / "stack_support.py").read_text(encoding="utf-8")
    doc = support.split('"""', 2)[1]
    ru, en = _parts()
    for tok in INFRA_TOKENS:
        assert tok in doc, f"в docstring stack_support нет {tok}"
        assert tok in ru, f"ru: нет {tok}"
        assert tok in en, f"en: нет {tok}"


def test_t28_agents_bootstrap_before_uvicorn() -> None:
    block = _commands_block(_text(AGENTS))
    assert "gostracker bootstrap" in block, "в блоке «Команды» нет gostracker bootstrap"
    assert block.index("gostracker bootstrap") < block.index("uvicorn app.main:app")


def test_t28_data_model_append_only_names_app_role() -> None:
    """Ревью 8: приложение подключается ролью tracker (superuser, владелец)."""
    section = _table_section(_text(DATA_MODEL), "domain_event")
    assert section is not None
    assert _has(section, r"`tracker`"), "нет роли `tracker`"
    assert _has(section, r"суперпользовател|superuser")
    assert _has(section, r"приложени.{0,120}`tracker`|`tracker`.{0,160}приложени"), (
        "не сказано, что приложение подключается ролью tracker"
    )
    assert "D-8" in section


def test_t28_readme_operator_cert_and_volumes() -> None:
    """Ревью 9."""
    ru, en = _parts()
    for name, part, no_start, as_is in (
        ("ru", ru, r"не запуска|не запустит|не стартует", r"как есть|без изменений|не перевыпуск"),
        (
            "en",
            en,
            r"fails? to start|will not start|does not start",
            r"as is|unchanged|not reissued",
        ),
    ):
        assert any(re.search(no_start, w, re.I | re.S) for w in _windows(part, r"tls\.key", 300)), (
            f"{name}: не сказано, что при несовпадающей паре web не стартует"
        )
        expired = r"просроч|истёк|истекш|expired|past its|expir"
        pat = rf"({expired}).{{0,200}}({as_is})|({as_is}).{{0,200}}({expired})"
        assert re.search(pat, part, re.I | re.S), f"{name}: просроченный сертификат оператора"
        assert re.search(r"TLS_SERVER_NAME.{0,300}64|64.{0,300}TLS_SERVER_NAME", part, re.S), (
            f"{name}: нет лимита 64 символа"
        )
        assert any(
            "secret_key" in w
            and "initial-admin-password" in w
            and re.search(r"содерж|хран|contains|holds|stores", w, re.I)
            for w in _windows(part, r"appdata", 250)
        ), f"{name}: не сказано, что appdata содержит secret_key и файл пароля"


# --- T31: регулярное обслуживание (FR-25b, D-42) -------------------------------------------

_CRON_CMD = "docker compose exec -T api gostracker maintenance"


def _maintenance_section(part: str, heading_re: str) -> str:
    """Текст от заголовка раздела обслуживания до следующего заголовка того же или выше уровня."""
    m = re.search(rf"^(#{{2,4}})\s+.*(?:{heading_re}).*$", part, re.M | re.I)
    assert m, f"нет заголовка раздела /{heading_re}/"
    level = len(m.group(1))
    rest = part[m.end() :]
    nxt = re.search(rf"^#{{1,{level}}}\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


@pytest.mark.parametrize(
    ("which", "heading_re"),
    [(0, r"Регулярное обслуживание"), (1, r"Regular maintenance")],
    ids=["ru", "en"],
)
def test_t31_readme_regular_maintenance_section(which: int, heading_re: str) -> None:
    """FR-25b: раздел регулярного обслуживания в обеих частях README."""
    section = _maintenance_section(_parts()[which], heading_re)
    for term in ("gostracker maintenance", "--dry-run", "crontab", _CRON_CMD):
        assert term in section, f"в разделе нет «{term}»"


@pytest.mark.parametrize(
    ("which", "heading_re", "sessions", "no_sched"),
    [
        (
            0,
            r"Регулярное обслуживание",
            r"сесси",
            r"(нет|не\s+(запуска|использ|добав)\w*).{0,160}(планировщик|сервис)"
            r"|(планировщик|сервис).{0,160}(нет|не\s+(входит|добавл)\w*)",
        ),
        (
            1,
            r"Regular maintenance",
            r"session",
            r"(no|not|without).{0,160}(scheduler|background|compose service)"
            r"|(scheduler|background).{0,160}(not|no\b|absent)",
        ),
    ],
    ids=["ru", "en"],
)
def test_t31_readme_maintenance_explains_why_and_no_scheduler(
    which: int, heading_re: str, sessions: str, no_sched: str
) -> None:
    section = _maintenance_section(_parts()[which], heading_re)
    assert _has(section, sessions), "не сказано про истёкшие сессии"
    assert _has(section, no_sched), "нет пометки: фонового планировщика/сервиса compose в R1 нет"


def test_t31_readme_maintenance_cron_example_and_dry_run_hint() -> None:
    """Пример crontab с `-T` (без TTY) в обеих частях; `--dry-run` упомянут как проверка."""
    for part in _parts():
        assert _has(part, r"(?m)^\s*\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+[^\n]*" + re.escape(_CRON_CMD))


# --- T32: быстрый старт ждёт готовности стека (приёмка R1.0, замечание 2; NFR-3) ----------

_CAT_SECRET = "docker compose exec api cat /data/secrets/initial-admin-password.txt"


@pytest.mark.parametrize("which", [0, 1], ids=["ru", "en"])
def test_t32_quick_start_waits_for_healthy_before_reading_password(which: int) -> None:
    """Файл пароля читается только после ``up -d --build --wait`` (в том же блоке кода)."""
    part = _parts()[which]
    cat_at = part.find(_CAT_SECRET)
    assert cat_at != -1, "в быстром старте нет чтения файла пароля"
    block_start = part.rfind("```", 0, cat_at)
    assert block_start != -1
    before = part[block_start:cat_at]
    ups = [
        m
        for m in re.finditer(r"^docker compose up\b[^\n]*$", before, re.M)
        if "--build" in m.group(0) and "--wait" in m.group(0)
    ]
    assert ups, "перед чтением файла нет `docker compose up -d --build --wait` в том же блоке"
    assert not re.search(r"^docker compose up\b(?![^\n]*--wait)[^\n]*$", before, re.M), (
        "в блоке остался запуск без --wait перед чтением файла пароля"
    )


# --- T88: документация MVP и чек-лист демо (NFR-3, NFR-11, AC-1 подготовка, D-64) -----------
# Проверки намеренно нестрогие к формулировкам: ключевые слова/регулярки отдельно для ru и en.

CHECKLIST = ROOT / "docs" / "acceptance" / "mvp-demo.md"
_LANGS = [0, 1]
_LANG_IDS = ["ru", "en"]

# (ru-регэксп, en-регэксп, описание)
MVP_README_TERMS: list[tuple[str, str, str]] = [
    (r"MVP", r"MVP", "название MVP"),
    (
        r"отложен|не\s+входит|вне\s+MVP",
        r"deferred|postponed|not\s+(included|part)|out\s+of\s+scope",
        "что отложено",
    ),
    (r"CRM", r"CRM", "CRM отложен"),
    (r"метк", r"labels?|tags?", "метки отложены"),
    (r"вложени", r"attachments?", "вложения отложены"),
    (r"корзин", r"trash|recycle", "корзина отложена"),
    (r"поиск", r"search", "поиск отложен"),
    (r"экспорт", r"export", "экспорт отложен"),
    (r"резервн\w*\s+копи|бэкап|backup", r"backup", "резервная копия отложена"),
    (
        r"docker compose exec api gostracker demo-data",
        r"docker compose exec api gostracker demo-data",
        "команда demo-data",
    ),
    (r"demo-passwords\.txt", r"demo-passwords\.txt", "файл паролей демо"),
    (r"reset-password", r"reset-password", "восстановление: reset-password"),
    (
        r"(удален\w+|удалени\w+|снос\w+|-v\b).{0,80}том|том.{0,80}(удал|-v\b)",
        r"(remov|delet|drop|-v\b).{0,80}volume|volume.{0,80}(remov|delet|drop|-v\b)",
        "переустановка с удалением тома",
    ),
    (r"ENV\s*=\s*production", r"ENV\s*=\s*production", "предупреждение ENV=production"),
    (r"demo\.", r"demo\.", "учётные записи demo.*"),
    (r"заблок|удал", r"block|disabl|delet|remov", "demo.* удалить/заблокировать"),
    (
        r"UF-2.{0,10}UF-6|UF-2\s*[…\-–—.]+\s*(UF-)?6",
        r"UF-2.{0,10}UF-6|UF-2\s*[…\-–—.]+\s*(UF-)?6",
        "сценарий UF-2…UF-6",
    ),
    (r"сесси", r"session", "обслуживание: истёкшие сессии"),
    (r"503", r"503", "503"),
    (r"service_busy", r"service_busy", "service_busy"),
    (r"Retry-After", r"Retry-After", "Retry-After"),
    (r"\b5\s*(с\b|сек)", r"\b5\s*(s\b|sec)", "5 секунд"),
    (r"перезапуск|restart", r"restart", "перезапуск api"),
    (r"22\.12", r"22\.12", "Node >= 22.12"),
    (r"/healthz", r"/healthz", "/healthz"),
    (r"SECRET_KEY", r"SECRET_KEY", "правила SECRET_KEY"),
    (r"docker compose down", r"docker compose down", "смена имени TLS: down"),
    (r"\s-p\s|`-p`|--project-name", r"\s-p\s|`-p`|--project-name", "каталог клона и -p"),
    (r"date\s+-u", r"date\s+-u", "date -u"),
    (r"docs/acceptance/mvp-demo\.md", r"docs/acceptance/mvp-demo\.md", "ссылка на чек-лист"),
]


@pytest.mark.parametrize("which", _LANGS, ids=_LANG_IDS)
@pytest.mark.parametrize(
    ("ru_re", "en_re", "label"), MVP_README_TERMS, ids=[t[2] for t in MVP_README_TERMS]
)
def test_t88_readme_mvp_term(which: int, ru_re: str, en_re: str, label: str) -> None:
    """NFR-11, D-64: README в обеих частях описывает MVP-демо и эксплуатацию."""
    part = _parts()[which]
    if (
        MVP_README_TERMS.index((ru_re, en_re, label)) < 9
    ):  # состав MVP/отложенное — в разделе про MVP
        part = _mvp_section(part)
    assert _has(part, ru_re if which == 0 else en_re), f"в README ({_LANG_IDS[which]}) нет: {label}"


@pytest.mark.parametrize("which", _LANGS, ids=_LANG_IDS)
def test_t88_readme_maintenance_is_sessions_only_no_trash(which: int) -> None:
    """Обслуживание MVP: только истёкшие сессии; корзины нет (D-64)."""
    heading = r"Регулярное обслуживание" if which == 0 else r"Regular maintenance"
    section = _maintenance_section(_parts()[which], heading)
    assert _has(section, r"сесси" if which == 0 else r"session")
    no_trash = (
        r"корзин\w*.{0,120}(нет|не\s+\w+|отложен)|(нет|не\s+\w+|отложен\w*).{0,120}корзин"
        if which == 0
        else r"trash.{0,120}(no\b|not|deferred|absent)|(no|not|without|deferred).{0,120}trash"
    )
    assert _has(section, no_trash), "в разделе обслуживания не сказано, что корзины в MVP нет"
    assert not _has(
        section,
        r"корзин\w*.{0,200}30\s*(дн|суток)" if which == 0 else r"trash.{0,200}30[\s-]*days?",
    ), "обслуживание не должно обещать очистку корзины через 30 дней"


_DEFER_MARK = re.compile(
    r"отложен|не\s+входит|нет\b|не\s+(реализ|поддерж|доступн|предусмотр|умеет)|вне\s+MVP"
    r"|deferred|postponed|not\s+(included|part|supported|available|implemented)"
    r"|\bno\b|without|out\s+of\s+scope|later|future|planned",
    re.I,
)
_UNSUPPORTED = re.compile(r"корзин|восстановлен|вложени|\bCRM\b|trash|restor|attachment", re.I)


def _mvp_section(part: str) -> str:
    m = re.search(r"^(#{2,4})\s+.*\bMVP\b.*$", part, re.M)
    assert m, "в части README нет заголовка раздела про MVP"
    level = len(m.group(1))
    rest = part[m.end() :]
    nxt = re.search(rf"^#{{1,{level}}}\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


@pytest.mark.parametrize("which", _LANGS, ids=_LANG_IDS)
def test_t88_readme_unsupported_features_only_as_deferred(which: int) -> None:
    """Корзина/восстановление/вложения/CRM в разделе MVP упоминаются только как отложенные."""
    section = _mvp_section(_parts()[which])
    paragraphs = re.split(r"\n\s*\n|\n(?=\s*[-*]\s)", section)
    hits = [p for p in paragraphs if _UNSUPPORTED.search(p)]
    assert hits, "в разделе MVP нет перечня отложенного"
    bad = [p.strip()[:100] for p in hits if not _DEFER_MARK.search(p)]
    assert not bad, f"неподдерживаемое подано без пометки «отложено»: {bad}"


# --- T88: команды README совпадают с реальным CLI ----------------------------------------


def test_t88_readme_cli_commands_exist_in_parser() -> None:
    import argparse

    from app.cli.main import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert "demo-data" in sub.choices
    assert "maintenance" in sub.choices
    maint_opts = {o for a in sub.choices["maintenance"]._actions for o in a.option_strings}
    assert "--dry-run" in maint_opts
    for part in _parts():
        assert "gostracker demo-data" in part
        assert re.search(r"gostracker maintenance\s+--dry-run", part)
        # в README нет несуществующих подкоманд gostracker
        for name in re.findall(r"gostracker\s+([a-z][a-z-]+)", part):
            if name in {"is", "and", "the", "to", "command", "cli"}:
                continue
            assert name in sub.choices, f"README ссылается на неизвестную команду gostracker {name}"


def test_t88_readme_demo_passwords_file_matches_code() -> None:
    src = (ROOT / "backend/app/cli/commands/demo_data.py").read_text(encoding="utf-8")
    assert "demo-passwords.txt" in src
    for part in _parts():
        assert "demo-passwords.txt" in part


# --- T88: docs/data-model.md, раздел MVP -------------------------------------------------


def test_t88_data_model_mvp_section() -> None:
    text = _text(DATA_MODEL)
    m = re.search(r"^#{2,3}\s+.*\bMVP\b.*$", text, re.M)
    assert m, "в docs/data-model.md нет раздела про MVP"
    nxt = re.search(r"^#{1,2}\s", text[m.end() :], re.M)
    section = text[m.end() : m.end() + nxt.start()] if nxt else text[m.end() :]
    assert "deleted_batch_id" in section
    assert _has(section, r"мягк\w+\s+удален|soft[- ]delet")
    assert _has(
        section,
        r"корзин.{0,120}(нет|не\s|отложен)|(нет|без|не\s).{0,120}корзин|no\s+trash|without.{0,40}trash",
    )
    assert _has(section, r"событ|event")
    # D-55: задачи/проекты событий не пишут
    assert _has(
        section,
        r"(задач|проект).{0,160}(не\s+(пиш|создают|порожда|ведут)|нет\s+событ|без\s+событ)"
        r"|(tasks?|projects?).{0,160}(do\s+not|don't|no\s+events?|not\s+(write|emit|record))",
    ), "не сказано, что задачи/проекты событий не пишут (D-55)"
    assert "D-55" in section or _has(section, r"audit|аудит|журнал")


# --- T88: docs/acceptance/mvp-demo.md ----------------------------------------------------


def test_t88_checklist_exists_and_is_checklist() -> None:
    text = _text(CHECKLIST)
    assert len(re.findall(r"^\s*[-*]\s+\[ \]", text, re.M)) >= 10, "нужны пункты `- [ ]`"


@pytest.mark.parametrize(
    "ac", ["AC-1", "AC-5", "AC-97", "AC-98", "AC-107", "UF-2", "UF-3", "UF-4", "UF-5", "UF-6"]
)
def test_t88_checklist_mentions(ac: str) -> None:
    assert re.search(rf"{ac}\b(?!\d)", _text(CHECKLIST)), f"в чек-листе нет {ac}"


def test_t88_checklist_polling_instead_of_ac107() -> None:
    text = _text(CHECKLIST)
    assert _has(text, r"15\s*(с\b|сек|s\b|sec)"), "нет порога опроса 15 с"
    assert _has(text, r"опрос|poll")
    # AC-107 упомянут как заменённый/отложенный, а не как проверяемый
    assert _has(
        text,
        r"AC-107.{0,200}(вместо|заменен|отложен|instead|replac|deferred)|(вместо|instead\s+of).{0,80}AC-107",
    )


@pytest.mark.parametrize(
    "pattern",
    [
        r"мыш|mouse",
        r"клавиатур|keyboard",
        r"Escape|Esc\b",
        r"Space|пробел",
        r"\bTab\b",
        r"скринридер|screen\s*reader",
        r"пуст\w+\s+колонк|empty\s+column",
        r"заголов|header|heading",
        r"Enter",
        r"Chromium",
    ],
)
def test_t88_checklist_drag_manual_items(pattern: str) -> None:
    """AC-5/AC-97: перечень ручной проверки перетаскивания из заметок ревью T86."""
    assert _has(_text(CHECKLIST), pattern), f"нет пункта /{pattern}/"


def test_t88_checklist_lists_deferred_explicitly() -> None:
    text = _text(CHECKLIST)
    m = re.search(
        r"^#{2,4}\s+.*(отложен|Deferred|не\s+проверя|Out\s+of\s+scope).*$", text, re.M | re.I
    )
    assert m, "нет раздела с перечнем отложенного"
    tail = text[m.end() :]
    for ru, en in [
        ("CRM", "CRM"),
        ("корзин", "trash"),
        ("вложени", "attachment"),
        ("метк", "label"),
        ("поиск", "search"),
    ]:
        assert _has(tail, f"{ru}|{en}"), f"в отложенном нет {ru}"


# --- T88: внутренние ссылки и пути -------------------------------------------------------

_LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
_BACKTICK_PATH_RE = re.compile(r"`((?:backend|frontend|deploy|docs|scripts|specs)/[\w./-]+)`")


def _local_refs(path: Path) -> set[Path]:
    text = _text(path)
    refs: set[Path] = set()
    for target in _LINK_RE.findall(text):
        if re.match(r"[a-z]+:", target):
            continue
        refs.add((path.parent / target).resolve())
    for target in _BACKTICK_PATH_RE.findall(text):
        if any(c in target for c in "*<{") or target.endswith("/..."):
            continue
        refs.add((ROOT / target).resolve())
    return refs


@pytest.mark.parametrize("doc", [README, CHECKLIST], ids=["README", "mvp-demo"])
def test_t88_internal_links_and_paths_exist(doc: Path) -> None:
    missing = sorted(str(r.relative_to(ROOT)) for r in _local_refs(doc) if not r.exists())
    assert not missing, f"{doc.name}: нет файлов {missing}"


def test_t88_docs_do_not_require_docker() -> None:
    """Статическая проверка: сами тесты T88 не вызывают docker."""
    src = Path(__file__).read_text(encoding="utf-8")
    assert (
        "subprocess"
        not in src.split("# --- T88")[1].split("def test_t88_docs_do_not_require_docker")[0]
    )


# --- T93: docs/data-model.md, login_display (D-66, plan §11.12) --------------------------


def test_t93_data_model_documents_login_display_and_migration_0005() -> None:
    text = _text(DATA_MODEL)
    section = _table_section(text, "app_user")
    assert section is not None, "нет раздела app_user"
    assert re.search(r"(?<![\w])login_display(?![\w])", section), "login_display не описан"
    assert "ck_app_user_login_display_lower" in section, "не описан CHECK login_display"
    assert _has(section, r"varchar\(64\)"), "не указан тип varchar(64)"
    assert re.search(r"^\|\s*`0005`\s*\|", text, re.M), "в таблице миграций нет строки 0005"
    assert "0001`–`0005" in text or "0001–0005" in text, "вступление: миграции 0001–0005"
    assert "0001`–`0004" not in text, "вступление всё ещё называет миграции 0001–0004"


# --- T99: отображаемый логин в документации (FR-73a, D-66, AC-132, R-M10) -----------------

_T99_RU = {
    "регистр логина": r"регистр\w*.{0,200}логин|логин.{0,200}регистр",
    "написание при создании": r"(написани\w+|как\s+(он\s+)?(был\s+)?введ\w+).{0,200}(созда|введ)|"
    r"(созда|введ).{0,200}(написани\w+)",
    "вход без учёта регистра": r"(вход|входе|входит).{0,200}(без\s+учёта|без\s+учета|не\s+(различа|учитыва)\w*)"
    r".{0,80}регистр|регистр.{0,80}(не\s+(различа|учитыва)\w*)",
    "занят при отличии только регистром": r"(отличающ\w+|отличи\w+|различающ\w+).{0,120}(только|лишь).{0,60}регистр\w*"
    r".{0,200}(занят|login_taken)|(занят|login_taken).{0,200}(только|лишь).{0,60}регистр",
    "INITIAL_ADMIN_LOGIN как задан": r"INITIAL_ADMIN_LOGIN.{0,300}(как\s+задан|написани|регистр)",
    "обновление без действий оператора": r"(без\s+(каких-либо\s+)?действий|ничего\s+делать\s+не\s+нужно|"
    r"действий\s+оператора\s+не\s+(нужно|требуется)).{0,400}|0005.{0,300}(старт|запуск|bootstrap|автоматическ)",
    "миграция 0005": r"\b0005\b",
    "прежние логины не меняются": r"(прежн\w+|существующ\w+|старые)\s+(логин|учётн|учетн)\w*.{0,200}"
    r"(не\s+меня\w+|без\s+изменен\w+|строчн\w+|как\s+прежде)|(логин\w*).{0,100}(не\s+меня\w+)",
    "откат теряет написание": r"(откат|downgrade|вернуть\w*\s+на).{0,300}(тер(я|ет)\w*|потер\w+|утрат\w+).{0,100}(написани|регистр)|"
    r"(тер(я|ет)\w*|потер\w+|утрат\w+).{0,100}(написани|регистр).{0,300}(откат|downgrade)",
}
_T99_EN = {
    "login case": r"\bcase\b.{0,200}login|login.{0,200}\bcase\b",
    "spelling as created": r"(spelling|as\s+(it\s+was\s+)?(typed|entered)|as\s+created).{0,200}(creat|enter|typ)|"
    r"(creat|enter|typ).{0,200}(spelling|as\s+(typed|entered))",
    "sign-in case-insensitive": r"(sign|log)[- ]?in.{0,200}(case[- ]insensitiv|ignor\w+\s+case|regardless\s+of\s+case|"
    r"not\s+case[- ]sensitiv)",
    "taken when differs only by case": r"(differ\w*|only).{0,120}\bcase\b.{0,200}(taken|login_taken|already\s+in\s+use)|"
    r"(taken|login_taken).{0,200}(differ\w*|only).{0,60}\bcase\b",
    "INITIAL_ADMIN_LOGIN as set": r"INITIAL_ADMIN_LOGIN.{0,300}(as\s+(set|given|configured|specified)|spelling|\bcase\b)",
    "upgrade without operator action": r"(no\s+(operator\s+)?action|nothing\s+to\s+do|without\s+(any\s+)?(operator\s+)?action)|"
    r"0005.{0,300}(start|bootstrap|automatic)",
    "migration 0005": r"\b0005\b",
    "existing logins unchanged": r"(existing|previous|earlier)\s+(login|account)s?.{0,200}"
    r"(unchanged|not\s+change|lower[- ]?case|as\s+before)",
    "downgrade loses spelling": r"(downgrade|roll\s*back|revert).{0,300}(lose|lost|loses|discard)\w*.{0,100}(spelling|case)|"
    r"(lose|lost|loses|discard)\w*.{0,100}(spelling|case).{0,300}(downgrade|roll\s*back|revert)",
}


@pytest.mark.parametrize("topic", sorted(_T99_RU))
def test_t99_readme_ru_covers_display_login(topic: str) -> None:
    ru, _ = _parts()
    assert _has(ru, _T99_RU[topic]), f"README (ru): нет темы «{topic}» (FR-73a)"


@pytest.mark.parametrize("topic", sorted(_T99_EN))
def test_t99_readme_en_covers_display_login(topic: str) -> None:
    _, en = _parts()
    assert _has(en, _T99_EN[topic]), f"README (en): no topic «{topic}» (FR-73a)"


def test_t99_readme_keywords_regist_and_case() -> None:
    ru, en = _parts()
    assert _has(ru, r"регистр"), "ru-часть README не упоминает регистр логина"
    assert _has(en, r"\bcase\b"), "en-часть README не упоминает case логина"


def test_t99_checklist_has_ac132_item_with_accounts_and_screens() -> None:
    text = _text(CHECKLIST)
    m = re.search(r"^\s*[-*]\s+\[ \].*AC-132(?!\d).*$", text, re.M)
    assert m, "в чек-листе нет пункта `- [ ]` с AC-132"
    start = m.start()
    nxt = re.search(r"^\s*[-*]\s+\[ \]|^#{1,3}\s", text[m.end() :], re.M)
    item = text[start : m.end() + (nxt.start() if nxt else len(text))]
    assert "Ivanov.Petr" in item
    assert "Sidorova.Anna" in item
    assert _has(item, r"нигде\s+не\s+строчн|ни\s+на\s+одном\s+экране.{0,40}строчн|not\s+in\s+lower")
    screens = {
        "учётные записи": r"учётн\w+\s+запис|учетн\w+\s+запис|управлени\w+\s+учётн",
        "профиль": r"профил",
        "проект": r"карточк\w+\s+проект|список\s+проект",
        "участники": r"участник",
        "мои задачи": r"мои\s+задачи",
        "доска": r"доск",
        "карточка задачи и комментарии": r"комментар",
        "выбор участника/исполнителя": r"выбор\w*\s+(участник|исполнител)|исполнител",
        "журнал аудита": r"журнал",
    }
    missing = [name for name, pat in screens.items() if not _has(item, pat)]
    assert not missing, f"в пункте AC-132 не перечислены экраны: {missing}"


def test_t99_docs_referenced_by_ac132_exist() -> None:
    assert CHECKLIST.is_file()
    assert README.is_file()
    assert (ROOT / "specs" / "001-pilot-r1" / "spec.md").is_file()
