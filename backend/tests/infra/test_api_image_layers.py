"""T26 (перенос T10/T20): слои образа api - зависимости до исходников, чистка следов сборки.

Статический разбор backend/Dockerfile. Правка исходников не должна сбрасывать слой с
зависимостями; в итоговом образе нет ``/app/build`` и ``*.egg-info``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.infra_static

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def _instructions() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    buf = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("#") or (not line.strip() and not buf):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        item = (buf + line).strip()
        buf = ""
        head, _, rest = item.partition(" ")
        out.append((head.upper(), rest.strip()))
    return out


def _copy_sources_index(ins: list[tuple[str, str]]) -> int:
    for i, (head, args) in enumerate(ins):
        if head == "COPY" and re.match(r"(--\S+\s+)*\.\s+\S+", args):
            return i
    raise AssertionError("нет COPY . /app (копирование исходников)")


def test_t20_dependencies_are_installed_before_sources_are_copied() -> None:
    """Слой зависимостей: до COPY исходников копируется только pyproject.toml и ставятся
    зависимости (pip install -r ...), затем исходники."""
    ins = _instructions()
    src = _copy_sources_index(ins)
    before = ins[:src]
    copies = [a for h, a in before if h == "COPY"]
    assert any("pyproject.toml" in a for a in copies), "до исходников нет COPY pyproject.toml"
    dep_runs = [
        i
        for i, (h, a) in enumerate(before)
        if h == "RUN" and re.search(r"pip\s+install\b.*(-r\b|--requirement\b)", a)
    ]
    assert dep_runs, "до COPY исходников нет установки зависимостей (pip install -r ...)"


def test_t20_sources_installed_without_deps_and_build_traces_removed_in_same_layer() -> None:
    """После исходников: pip install --no-deps, в том же RUN удаляются /app/build и *.egg-info."""
    ins = _instructions()
    src = _copy_sources_index(ins)
    after = [a for h, a in ins[src + 1 :] if h == "RUN"]
    install = [a for a in after if re.search(r"pip\s+install\b", a)]
    assert install, "после исходников нет pip install"
    run = install[0]
    assert "--no-deps" in run
    assert re.search(r"rm\s+-rf?\b[^&;]*/app/build", run) or "/app/build" in run
    assert "egg-info" in run
    assert re.search(r"rm\s+-[a-z]*r[a-z]*f?\b", run)
