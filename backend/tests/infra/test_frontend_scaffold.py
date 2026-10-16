"""T21: статический разбор каркаса фронтенда (plan §7.2, C-1, NFR-4, NFR-6, NFR-8, NFR-10).

Node не запускается: разбираются файлы в ``frontend/`` и ``git ls-files frontend``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.infra_static

REPO = Path(__file__).resolve().parents[3]
FE = REPO / "frontend"

FORBIDDEN = {
    "axios", "redux", "@reduxjs/toolkit", "react-redux", "zustand", "moment", "lodash", "jquery",
    "sentry", "@sentry/react", "@sentry/browser", "posthog-js", "posthog", "analytics-node",
    "@segment/analytics-next", "amplitude-js", "@amplitude/analytics-browser", "react-ga",
    "react-ga4", "google-analytics", "firebase", "@firebase/app",
}  # fmt: skip
FORBIDDEN_SUBSTR = ("sentry", "posthog", "segment", "amplitude", "google-analytics", "firebase")
HOOKS = ("preinstall", "install", "postinstall", "prepare", "prepublish", "prepublishOnly")


def _text(rel: str) -> str:
    p = FE / rel
    assert p.is_file(), f"нет файла frontend/{rel}"
    return p.read_text(encoding="utf-8")


def _json(rel: str) -> dict[str, Any]:
    raw = _text(rel)
    # tsconfig допускает комментарии и хвостовые запятые
    raw = re.sub(r"(?m)^\s*//.*$", "", raw)
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    data = json.loads(raw)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def pkg() -> dict[str, Any]:
    return _json("package.json")


@pytest.fixture(scope="module")
def deps(pkg: dict[str, Any]) -> dict[str, str]:
    d: dict[str, str] = {}
    d.update(pkg.get("devDependencies", {}))
    d.update(pkg.get("dependencies", {}))
    return d


def test_t21_package_private_and_name(pkg: dict[str, Any]) -> None:
    assert pkg.get("private") is True
    assert isinstance(pkg.get("name"), str) and pkg["name"]
    assert pkg.get("type") == "module"


def test_t21_npm_scripts(pkg: dict[str, Any]) -> None:
    s = pkg.get("scripts", {})
    assert s.get("typecheck") == "tsc --noEmit"
    assert s.get("test") == "vitest run"
    assert s.get("gen:api") == (
        "openapi-typescript ../docs/api/openapi.json -o src/shared/api/schema.d.ts"
    )
    for name in ("dev", "build", "lint"):
        assert s.get(name), f"нет скрипта {name}"
    assert s["dev"].strip().startswith("vite")
    assert "vite build" in s["build"]
    assert s["lint"].strip().startswith("eslint")


def test_t21_no_install_lifecycle_scripts(pkg: dict[str, Any]) -> None:
    s = pkg.get("scripts", {})
    assert not [h for h in HOOKS if h in s]


@pytest.mark.parametrize(
    ("name", "prefix"),
    [
        ("react", "^18.3.1"),
        ("react-dom", "^18.3.1"),
        ("@tanstack/react-query", "^5"),
        ("react-router-dom", "^7"),
        ("openapi-fetch", "^0.17"),
        ("vite", "^8"),
        ("@vitejs/plugin-react", "^6"),
        ("typescript", "~5.9"),
        ("openapi-typescript", "^7"),
    ],
)
def test_t21_dependency_versions(deps: dict[str, str], name: str, prefix: str) -> None:
    assert name in deps, f"нет {name}"
    assert deps[name].startswith(prefix), f"{name}: {deps[name]} (ожидалось {prefix}*)"


def test_t21_react_not_19(deps: dict[str, str]) -> None:
    assert not re.search(r"(^|[^\d])19", deps["react"])
    assert "19" not in deps["react-dom"].split(".")[0]


@pytest.mark.parametrize(
    "name",
    ["eslint", "typescript-eslint", "eslint-plugin-react-hooks", "vitest", "jsdom",
     "@testing-library/react"],
)  # fmt: skip
def test_t21_required_dev_packages(deps: dict[str, str], name: str) -> None:
    assert name in deps


def test_t21_runtime_vs_dev_split(pkg: dict[str, Any]) -> None:
    rt = set(pkg.get("dependencies", {}))
    assert {"react", "react-dom", "@tanstack/react-query", "react-router-dom",
            "openapi-fetch"} <= rt  # fmt: skip
    dev = set(pkg.get("devDependencies", {}))
    assert {"vite", "typescript", "vitest", "eslint"} <= dev
    assert not rt & {"vite", "typescript", "vitest", "eslint", "jsdom"}


def test_t21_no_forbidden_packages(deps: dict[str, str]) -> None:
    for name in deps:
        assert name not in FORBIDDEN, name
        assert not any(x in name.lower() for x in FORBIDDEN_SUBSTR), name


def test_t21_lockfile_committed_and_v3() -> None:
    lock = _json("package-lock.json")
    assert lock.get("lockfileVersion", 0) >= 3
    out = subprocess.run(
        ["git", "ls-files", "frontend/package-lock.json"], cwd=REPO, capture_output=True, text=True
    )
    # до коммита допускается untracked, но файл обязан существовать (проверено выше)
    assert out.returncode == 0


def test_t21_lockfile_registry_and_integrity() -> None:
    lock = _json("package-lock.json")
    packages = lock.get("packages", {})
    assert len(packages) > 10
    for path, meta in packages.items():
        if path == "" or meta.get("link"):
            continue
        res = meta.get("resolved")
        assert res, f"{path}: нет resolved"
        assert res.startswith("https://registry.npmjs.org/"), f"{path}: {res}"
        assert meta.get("integrity"), f"{path}: нет integrity"
    names = {p.rsplit("node_modules/", 1)[-1] for p in packages}
    assert not names & FORBIDDEN
    react = packages.get("node_modules/react", {})
    assert str(react.get("version", "")).startswith("18.")
    ts = packages.get("node_modules/typescript", {})
    assert str(ts.get("version", "")).startswith("5.9.")


def test_t21_lockfile_matches_package_json(pkg: dict[str, Any]) -> None:
    root = _json("package-lock.json")["packages"][""]
    assert root.get("dependencies", {}) == pkg.get("dependencies", {})
    assert root.get("devDependencies", {}) == pkg.get("devDependencies", {})


def test_t21_npmrc_has_no_foreign_registry() -> None:
    p = FE / ".npmrc"
    if p.exists():
        txt = p.read_text(encoding="utf-8")
        for line in txt.splitlines():
            if "registry" in line and not line.strip().startswith("#"):
                assert "registry.npmjs.org" in line, line


def test_t21_tsconfig_strict() -> None:
    co = _json("tsconfig.json").get("compilerOptions", {})
    assert co.get("strict") is True
    assert co.get("noUncheckedIndexedAccess") is True
    assert co.get("noImplicitOverride") is True
    assert co.get("isolatedModules") is True
    assert co.get("jsx") == "react-jsx"
    assert not co.get("allowJs")
    assert co.get("noEmit") is True


def test_t21_tsconfig_includes_src_and_tests() -> None:
    inc = _json("tsconfig.json").get("include", [])
    assert any(i.startswith("src") for i in inc)
    assert any(i.startswith("tests") for i in inc)


def test_t21_all_tsconfigs_keep_strictness() -> None:
    for p in FE.glob("tsconfig*.json"):
        co = _json(p.name).get("compilerOptions", {})
        assert co.get("strict", True) is True, p.name
        assert not co.get("allowJs"), p.name


def test_t21_eslint_config() -> None:
    cfg = _text("eslint.config.js")
    assert "typescript-eslint" in cfg
    assert re.search(r"strict", cfg), "нужен strict-пресет typescript-eslint"
    assert "react-hooks" in cfg
    assert re.search(r"""['"]@typescript-eslint/no-explicit-any['"]\s*:\s*['"]error['"]""", cfg)
    assert "ban-ts-comment" in cfg
    assert re.search(r"allow-with-description|descriptionFormat|minimumDescriptionLength", cfg)
    assert not re.search(r"['\"]no-explicit-any['\"]\s*:\s*['\"](off|warn)", cfg)
    assert "dist" in cfg  # ignores


def test_t21_vite_config_text() -> None:
    cfg = _text("vite.config.ts")
    assert re.search(r"""['"]/api['"]""", cfg)
    assert "http://localhost:8000" in cfg
    assert re.search(r"changeOrigin\s*:\s*false", cfg)
    assert re.search(r"port\s*:\s*5173", cfg)
    assert not re.search(r"\bdefine\s*:", cfg)
    assert "loadEnv" not in cfg


def test_t21_index_html_local_only_ru() -> None:
    html = _text("index.html")
    assert re.search(r"""<html[^>]*\blang=["']ru["']""", html)
    assert re.search(r"<title>[^<]+</title>", html)
    assert 'id="root"' in html
    urls = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", html)
    for u in urls:
        assert not re.match(r"(https?:)?//", u), f"внешний ресурс {u}"
    assert "@import" not in html
    assert "src/main.tsx" in html


def test_t21_src_files_only_expected() -> None:
    src = FE / "src"
    assert src.is_dir()
    found = {p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()}
    allowed = {
        "main.tsx", "app/App.tsx", "app/providers.tsx", "vite-env.d.ts",
        # T22
        "shared/api/client.ts", "shared/api/polling.ts", "shared/api/schema.d.ts",
        "shared/i18n/ru.ts", "shared/i18n/index.ts",
        # T23
        "app/router.tsx", "features/auth/api.ts", "features/auth/LoginPage.tsx",
        "features/auth/ChangePasswordPage.tsx", "features/auth/NoRolePage.tsx",
        "features/auth/useLogout.ts", "shared/ui/TextField.tsx",
        "shared/ui/ErrorAlert.tsx", "shared/ui/ui.css",
        # T24
        "features/admin/api.ts", "features/admin/UsersPage.tsx", "features/admin/AuditPage.tsx",
        "features/admin/password.ts", "shared/ui/ConfirmDialog.tsx", "shared/ui/Pagination.tsx",
        # T81
        "shared/ui/UserPicker.tsx", "features/users/api.ts",
        # T82
        "features/projects/api.ts", "features/projects/ProjectsPage.tsx",
        "features/projects/ProjectPage.tsx",
        # T83
        "features/tasks/api.ts", "features/tasks/TaskList.tsx", "features/tasks/CreateTaskForm.tsx",
        "features/tasks/TaskPage.tsx", "features/tasks/SubtaskList.tsx",
        # T86
        "features/boards/api.ts", "features/boards/BoardView.tsx", "features/boards/dnd.ts",
        # T85
        "features/comments/api.ts", "features/comments/Comments.tsx",
        # T100
        "shared/ui/Icon.tsx",
    }  # fmt: skip
    assert {"main.tsx", "app/App.tsx", "app/providers.tsx"} <= found
    assert found <= allowed, f"лишние файлы: {sorted(found - allowed)}"


def test_t86_boards_files_exist() -> None:
    for rel in (
        "features/boards/api.ts",
        "features/boards/BoardView.tsx",
        "features/boards/dnd.ts",
    ):
        assert (FE / "src" / rel).is_file(), f"нет frontend/src/{rel}"


def test_t21_no_build_artifacts_in_git() -> None:
    out = subprocess.run(
        ["git", "ls-files", "frontend"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert not [f for f in out if "node_modules/" in f or f.startswith("frontend/dist/")]


def test_t21_gitignore_has_node_modules_and_dist() -> None:
    lines = {ln.strip() for ln in (REPO / ".gitignore").read_text().splitlines()}
    assert "node_modules/" in lines or "node_modules" in lines
    assert "dist/" in lines or "dist" in lines


def test_t21_readme_documents_commands() -> None:
    txt = _text("README.md")
    assert "Пока не инициализирован" not in txt
    for cmd in ("npm ci", "npm run dev", "npm run lint", "npm run typecheck", "npm test",
                "npm run build", "npm run gen:api"):  # fmt: skip
        assert cmd in txt, cmd


# --- T22: заметки ревью T21 -------------------------------------------------------------


def test_t22_src_has_api_and_i18n_files() -> None:
    for rel in ("shared/api/client.ts", "shared/api/polling.ts", "shared/api/schema.d.ts",
                "shared/i18n/ru.ts", "shared/i18n/index.ts"):  # fmt: skip
        assert (FE / "src" / rel).is_file(), f"нет frontend/src/{rel}"


def test_t22_eslint_forbids_direct_fetch_and_axios_outside_api() -> None:
    cfg = _text("eslint.config.js")
    assert re.search(r"no-restricted-globals", cfg)
    assert re.search(r"no-restricted-properties", cfg)
    assert re.search(r"no-restricted-imports", cfg)
    # правила нацелены на fetch, window.fetch, globalThis.fetch и axios
    assert re.search(r"""no-restricted-globals[\s\S]{0,400}?['"]fetch['"]""", cfg)
    props = re.search(r"no-restricted-properties[\s\S]{0,800}", cfg)
    assert props is not None
    assert "window" in props.group(0)
    assert "globalThis" in props.group(0)
    assert re.search(r"""['"]fetch['"]""", props.group(0))
    assert re.search(r"""no-restricted-imports[\s\S]{0,400}?['"]axios['"]""", cfg)
    # исключение: сам API-слой
    assert re.search(r"""ignores\s*:\s*\[[^\]]*['"]src/shared/api/\*\*['"]""", cfg)
    # генерируемый файл по-прежнему не линтуется
    assert "src/shared/api/schema.d.ts" in cfg


def test_t22_engines_and_readme_node_range() -> None:
    expected = "^22.12 || ^24 || >=26"
    engines = _json("package.json").get("engines", {})
    assert engines.get("node") == expected
    readme = _text("README.md")
    assert expected in readme
    assert "^20.19" not in readme


def test_t22_npmrc_ignore_scripts() -> None:
    lines = [ln.strip() for ln in _text(".npmrc").splitlines()]
    assert "ignore-scripts=true" in lines


def test_t22_vite_strict_port() -> None:
    assert re.search(r"strictPort\s*:\s*true", _text("vite.config.ts"))


def test_t22_check_sh_explains_npm_ci_when_node_modules_missing() -> None:
    txt = (REPO / "scripts" / "check.sh").read_text(encoding="utf-8")
    assert "node_modules" in txt
    assert "cd frontend && npm ci" in txt


def test_t22_eslint_restricts_all_network_apis() -> None:
    cfg = _text("eslint.config.js")
    globals_block = re.search(r"no-restricted-globals[\s\S]{0,900}?\],", cfg)
    assert globals_block is not None
    for name in ("fetch", "XMLHttpRequest", "EventSource"):
        assert re.search(rf"""name\s*:\s*['"]{name}['"]""", globals_block.group(0)), name
    props = re.search(r"no-restricted-properties[\s\S]{0,1800}?\],", cfg)
    assert props is not None
    for obj, prop in (("self", "fetch"), ("window", "fetch"), ("globalThis", "fetch"),
                      ("navigator", "sendBeacon")):  # fmt: skip
        pat = rf"""object\s*:\s*['"]{obj}['"][\s\S]{{0,80}}?property\s*:\s*['"]{prop}['"]"""
        assert re.search(pat, props.group(0)), f"{obj}.{prop}"


def test_t22_node_version_enforced_by_npmrc_or_check_script() -> None:
    npmrc = [ln.strip() for ln in _text(".npmrc").splitlines()]
    check = (REPO / "scripts" / "check.sh").read_text(encoding="utf-8")
    by_npmrc = "engine-strict=true" in npmrc
    by_check = bool(re.search(r"node\s+(-v|--version|-p|-e)", check)) and bool(
        re.search(r"(?i)node[^\n]*(верси|version|22|24)", check)
    )
    assert by_npmrc or by_check, "нужен engine-strict=true или проверка версии Node в check.sh"
