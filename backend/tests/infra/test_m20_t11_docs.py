"""M20-T11: документация интеграции с агентами (AC-12, ADR-0018).

Проверяем, что ``docs/ai-integration.md`` существует, содержит команды подключения для Claude Code
и Codex CLI, перечисляет все инструменты реестра и не обещает поддержки облачных клиентов в R1.
"""

from __future__ import annotations

from pathlib import Path

from app.api.mcp.tools import default_registry

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "ai-integration.md"
README = ROOT / "README.md"


def _guide() -> str:
    assert GUIDE.is_file(), "нет docs/ai-integration.md"
    return GUIDE.read_text(encoding="utf-8")


def test_m20_t11_guide_has_claude_code_and_codex_commands() -> None:
    text = _guide()
    assert "claude mcp add" in text
    assert "codex mcp add" in text
    assert "gtrack mcp" in text
    assert "GTRACK_TOKEN" in text


def test_m20_t11_guide_lists_every_registered_tool() -> None:
    text = _guide()
    missing = [
        spec.name
        for spec in default_registry().visible_for(_business_role())
        if spec.name not in text
    ]
    assert missing == []


def test_m20_t11_guide_states_cloud_clients_are_out_of_r1() -> None:
    text = _guide()
    assert "ChatGPT" in text
    assert "R1" in text
    assert "ADR-0018" in text


def test_m20_t11_readme_links_to_guide_in_both_languages() -> None:
    text = README.read_text(encoding="utf-8")
    assert text.count("docs/ai-integration.md") >= 2
    assert "## Работа с AI-агентами (MCP)" in text
    assert "## AI agents (MCP)" in text


def _business_role() -> object:
    from app.domain.access.roles import Role

    return Role.BUSINESS_ADMIN
