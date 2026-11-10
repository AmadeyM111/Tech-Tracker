// 026 FR-4 / AC-7: "Доступ для агентов" carries the "Инструкция для Claude Code" block (id claude-code-instructions).
// The commands take the origin of the page; the token is never printed (only the $GTRACK_TOKEN variable).
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { installFetch, j, renderApp } from "../admin/helpers";

const ME = "GET /api/v1/me";
const LIST = "GET /api/v1/me/tokens";
const BLOCK_ID = "claude-code-instructions";

function setup() {
  return installFetch({
    [ME]: () =>
      j(200, {
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        login: "anna",
        role: "user",
        must_change_password: false,
        capabilities: ["business_access"],
      }),
    [LIST]: () => j(200, []),
  });
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("AgentAccessPage: Claude Code instructions", () => {
  it("ac7_block_has_anchor_heading_and_origin_commands_without_token", async () => {
    setup();
    const { container } = renderApp("/profile/agents");
    const heading = await screen.findByRole("heading", { level: 2, name: ru["agent_tokens.instructions_title"] });
    const block = container.querySelector<HTMLElement>(`#${BLOCK_ID}`);
    expect(block).not.toBeNull();
    expect(block?.contains(heading)).toBe(true);
    const text = block?.textContent ?? "";
    expect(text).toContain(`claude mcp add --transport http gtrack ${window.location.origin}/mcp`);
    expect(text).toContain(`GTRACK_URL=${window.location.origin}`);
    expect(text).toContain("$GTRACK_TOKEN");
    expect(text).not.toMatch(/gtrk_/);
  });

  it("ac7_hash_in_link_scrolls_to_the_block", async () => {
    setup();
    renderApp(`/profile/agents#${BLOCK_ID}`);
    await screen.findByRole("heading", { level: 2, name: ru["agent_tokens.instructions_title"] });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });
});
