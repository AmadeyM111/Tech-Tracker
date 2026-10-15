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
    ("which", "heading_re", "trash", "sessions", "no_sched"),
    [
        (
            0,
            r"Регулярное обслуживание",
            r"корзин\w*.{0,200}30\s*(дн|суток)|30\s*(дн|суток).{0,200}корзин",
            r"сесси",
            r"(нет|не\s+(запуска|использ|добав)\w*).{0,160}(планировщик|сервис)"
            r"|(планировщик|сервис).{0,160}(нет|не\s+(входит|добавл)\w*)",
        ),
        (
            1,
            r"Regular maintenance",
            r"trash.{0,200}30\s*days|30\s*days.{0,200}trash|30-day",
            r"session",
            r"(no|not|without).{0,160}(scheduler|background|compose service)"
            r"|(scheduler|background).{0,160}(not|no\b|absent)",
        ),
    ],
    ids=["ru", "en"],
)
def test_t31_readme_maintenance_explains_why_and_no_scheduler(
    which: int, heading_re: str, trash: str, sessions: str, no_sched: str
) -> None:
    section = _maintenance_section(_parts()[which], heading_re)
    assert _has(section, trash), "не сказано про срок корзины 30 дней"
    assert _has(section, sessions), "не сказано про истёкшие сессии"
    assert _has(section, no_sched), "нет пометки: фонового планировщика/сервиса compose в R1 нет"


def test_t31_readme_maintenance_cron_example_and_dry_run_hint() -> None:
    """Пример crontab с `-T` (без TTY) в обеих частях; `--dry-run` упомянут как проверка."""
    for part in _parts():
        assert _has(part, r"(?m)^\s*\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+[^\n]*" + re.escape(_CRON_CMD))
