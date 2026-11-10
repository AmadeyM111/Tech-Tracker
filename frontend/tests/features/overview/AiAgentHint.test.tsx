// 026 «Подключить ИИ-агента к GTrack» on «Сводка» (spec 026): AC-1...AC-8.
// The card is a complementary landmark above the heading; closing is kept in localStorage per user id.
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { installFetch, j, page, renderApp } from "../admin/helpers";

const ME = "GET /api/v1/me";
const COUNTS = "GET /api/v1/me/overview";
const TASKS = "GET /api/v1/me/overview/tasks";
const PROJECTS = "GET /api/v1/me/overview/projects";
const TOKENS = "GET /api/v1/me/tokens";

const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const USER_CAPS = ["business_access"];
const TA_CAPS = ["manage_accounts", "assign_roles"];
const BA_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const USER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const TA_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const OTHER_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

const COUNTS_24 = { total: 24, todo: 6, in_progress: 9, review: 4, done: 5, needs_review: 2 };
const TITLE = ru["ai_hint.title"];
const CLOSE_NAME = ru["ai_hint.close_aria"];
const TOKENS_LINK = ru["ai_hint.link_tokens"];
const INSTRUCTIONS_LINK = ru["ai_hint.link_instructions"];

const keyFor = (id: string) => `gtrack.hint.ai_agent.${id}`;

function profile(id: string, capabilities: string[], role: string) {
  return { id, login: `user-${id.slice(0, 4)}`, role, must_change_password: false, capabilities };
}

function setup(me: unknown) {
  return installFetch({
    [ME]: () => j(200, me),
    [COUNTS]: () => j(200, COUNTS_24),
    [TASKS]: () => j(200, { items: [], page: 1, page_size: 50, has_next: false, total: 0 }),
    [PROJECTS]: () => j(200, page([])),
    [TOKENS]: () => j(200, []),
  });
}

const card = () => screen.queryByRole("complementary", { name: TITLE });
const closeButton = () => screen.findByRole("button", { name: CLOSE_NAME });
const summaryHeading = () => screen.findByRole("heading", { level: 1, name: "Сводка" });

beforeEach(() => {
  localStorage.clear();
  // jsdom has no layout: the anchor scroll on /profile/agents is checked by the call only.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  localStorage.clear();
});

describe("AiAgentHint on the summary screen", () => {
  it.each([
    ["БА", BA_ID, BA_CAPS, "business_admin"],
    ["Пользователь", USER_ID, USER_CAPS, "user"],
  ])("ac1_card_above_heading_and_tiles_with_text_and_two_links_for_%s", async (_name, id, caps, role) => {
    setup(profile(id, caps, role));
    renderApp("/summary");
    const aside = await screen.findByRole("complementary", { name: TITLE });
    expect(within(aside).getByRole("heading", { level: 2, name: TITLE })).toBeTruthy();
    expect(within(aside).getByText(ru["ai_hint.text"])).toBeTruthy();
    expect(aside.textContent).toContain("увидит и сможет изменить");
    const tokens = within(aside).getByRole("link", { name: TOKENS_LINK });
    const instructions = within(aside).getByRole("link", { name: INSTRUCTIONS_LINK });
    expect(tokens.getAttribute("href")).toBe("/profile/agents");
    expect(instructions.getAttribute("href")).toBe("/profile/agents#claude-code-instructions");
    const h1 = await summaryHeading();
    const tiles = await screen.findByRole("list", { name: "Счётчики задач" });
    expect(aside.compareDocumentPosition(h1) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(aside.compareDocumentPosition(tiles) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("ac2_hide_removes_card_and_keeps_it_hidden_after_reload_under_user_key", async () => {
    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    const first = renderApp("/summary");
    fireEvent.click(await closeButton());
    expect(card()).toBeNull();
    expect(localStorage.getItem(keyFor(BA_ID))).not.toBeNull();
    first.unmount();

    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    renderApp("/summary");
    await summaryHeading();
    expect(card()).toBeNull();
  });

  it("ac3_another_user_in_the_same_browser_still_sees_the_card", async () => {
    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    const first = renderApp("/summary");
    fireEvent.click(await closeButton());
    first.unmount();

    setup(profile(OTHER_ID, USER_CAPS, "user"));
    renderApp("/summary");
    expect(await screen.findByRole("complementary", { name: TITLE })).toBeTruthy();
    expect(localStorage.getItem(keyFor(OTHER_ID))).toBeNull();
  });

  it("ac4_storage_write_failure_hides_card_without_error_on_screen", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("storage is denied", "QuotaExceededError");
    });
    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    renderApp("/summary");
    fireEvent.click(await closeButton());
    expect(card()).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(await summaryHeading()).toBeTruthy();
  });

  it("ac4_storage_read_failure_shows_card_without_error_on_screen", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("storage is denied", "SecurityError");
    });
    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    renderApp("/summary");
    expect(await screen.findByRole("complementary", { name: TITLE })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ac5_ta_has_no_summary_and_no_card", async () => {
    setup(profile(TA_ID, TA_CAPS, "tech_admin"));
    renderApp("/summary");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(card()).toBeNull();
    expect(screen.queryByRole("heading", { name: "Сводка" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Сводка" })).toBeNull();
  });

  it("ac6_card_text_does_not_mention_cloud_agents", () => {
    const text = Object.entries(ru)
      .filter(([key]) => key.startsWith("ai_hint."))
      .map(([, value]) => value)
      .join(" ");
    expect(text).toContain("увидит и сможет изменить");
    expect(text).not.toMatch(/chatgpt|облачн|облак/i);
  });

  it("ac7_instruction_link_leads_to_block_on_agent_access_page", async () => {
    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    renderApp("/summary");
    fireEvent.click(await screen.findByRole("link", { name: INSTRUCTIONS_LINK }));
    const block = await screen.findByRole("region", { name: ru["agent_tokens.instructions_title"] });
    expect(block.id).toBe("claude-code-instructions");
    expect(screen.getByRole("heading", { level: 1, name: ru["agent_tokens.title"] })).toBeTruthy();
  });

  it("ac8_keyboard_close_moves_focus_to_summary_heading", async () => {
    setup(profile(BA_ID, BA_CAPS, "business_admin"));
    renderApp("/summary");
    const button = await closeButton();
    expect(button.getAttribute("type")).toBe("button");
    expect(button.className).toContain("ui-btn-secondary");
    button.focus();
    expect(document.activeElement).toBe(button);
    // Enter and Space on a native button fire a click; the focus move below is the code under test.
    fireEvent.click(button);
    expect(card()).toBeNull();
    const h1 = await summaryHeading();
    expect(h1.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(h1);
  });
});
