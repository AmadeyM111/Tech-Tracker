// R7-T19: метка «ИИ» (007/FR-31, FR-29, AC-37 - автотесты компонентов; сам AC ручной).
// Карточка задачи: исполнитель и автор; комментарии; компонент UserName (plan 4.10, PD-16, З-7).
import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { ID_KUZNETSOV, TID1, NO_PERMS, ALL_PERMS, card, j, openCard, page, ref } from "./taskpage-helpers";

const COMMENTS_GET = `GET /api/v1/tasks/${TID1}/comments`;
const BOT = { ...ref("99999999-9999-4999-8999-999999999991", "bot-agent"), is_agent: true };
const HUMAN = { ...ref(ID_KUZNETSOV, "kuznetsov"), is_agent: false };
const MARK = "abbr.ui-agent-mark";

const cell = (name: string) => document.querySelector<HTMLElement>(`dl.ui-props dd[data-field="${name}"]`)!;
const marks = (el: ParentNode) => Array.from(el.querySelectorAll<HTMLElement>(MARK));
const dtTexts = () => Array.from(document.querySelectorAll("dl.ui-props dt")).map((e) => e.textContent);

function expectAgentMark(scope: ParentNode, login: string) {
  const m = marks(scope);
  expect(m).toHaveLength(1);
  expect(m[0]!.tagName).toBe("ABBR");
  expect(m[0]!.textContent).toBe("ИИ");
  expect(m[0]!.getAttribute("title")).toBe("ИИ-агент");
  // метка не единственный носитель информации: логин рядом, в том же элементе
  expect((scope as HTMLElement).textContent).toContain(login);
  expect((scope as HTMLElement).textContent!.replace("ИИ", "").trim()).toBe(login);
}

describe("R7-T19 словарь", () => {
  it("007_fr31_dictionary_keys_exist", () => {
    const dict = ru as Record<string, string | undefined>;
    expect(dict["users.agent_mark"]).toBe("ИИ");
    expect(dict["users.agent_mark_title"]).toBe("ИИ-агент");
    expect(dict["tasks.author_label"]).toBe("Автор");
  });
});

describe("R7-T19 UserName", () => {
  it("007_fr31_username_exported_from_user_picker", async () => {
    const mod = (await import("../../../src/shared/ui/UserPicker")) as Record<string, unknown>;
    expect(typeof mod["UserName"]).toBe("function");
  });

  it("007_fr31_username_renders_mark_only_for_agent", async () => {
    const mod = (await import("../../../src/shared/ui/UserPicker")) as Record<string, unknown>;
    const UserName = mod["UserName"] as (p: { user: { login: string; is_agent: boolean } }) => JSX.Element;
    expect(typeof UserName).toBe("function");
    const { render } = await import("@testing-library/react");
    const { createElement } = await import("react");
    const a = render(createElement(UserName, { user: { login: "bot", is_agent: true } }));
    expectAgentMark(a.container, "bot");
    a.unmount();
    const h = render(createElement(UserName, { user: { login: "ivan", is_agent: false } }));
    expect(marks(h.container)).toHaveLength(0);
    expect(h.container.textContent).toBe("ivan");
  });
});

describe("R7-T19 карточка задачи", () => {
  it("007_fr31_card_agent_author_and_agent_assignee_marked_readonly", async () => {
    await openCard(() => card({ assignee: BOT, author: BOT, permissions: NO_PERMS }));
    expectAgentMark(cell("assignee"), "bot-agent");
    expectAgentMark(cell("author"), "bot-agent");
  });

  it("007_fr31_card_agent_assignee_marked_with_assignee_picker", async () => {
    await openCard(() => card({ assignee: BOT, author: HUMAN, permissions: ALL_PERMS }));
    const dd = cell("assignee");
    const m = marks(dd);
    expect(m).toHaveLength(1);
    expect(m[0]!.textContent).toBe("ИИ");
    expect(m[0]!.getAttribute("title")).toBe("ИИ-агент");
    expect(dd.textContent).toContain("bot-agent");
    expect(marks(cell("author"))).toHaveLength(0);
  });

  it("007_fr31_card_humans_have_no_mark_and_author_shows_login", async () => {
    await openCard(() => card({ assignee: HUMAN, author: HUMAN, permissions: NO_PERMS }));
    expect(cell("assignee").textContent).toBe("kuznetsov");
    expect(cell("author").textContent).toBe("kuznetsov");
    expect(marks(document)).toHaveLength(0);
  });

  it("007_fr31_card_unassigned_has_no_mark", async () => {
    await openCard(() => card({ assignee: null, author: BOT, permissions: NO_PERMS }));
    expect(cell("assignee").textContent).toBe(ru["tasks.assignee_none"]);
    expect(marks(cell("assignee"))).toHaveLength(0);
    expectAgentMark(cell("author"), "bot-agent");
  });

  it("007_fr29_author_row_is_last_and_previous_order_unchanged", async () => {
    await openCard(() => card({ assignee: BOT, author: BOT, permissions: NO_PERMS }));
    expect(dtTexts()).toEqual([
      ru["tasks.col_status"],
      ru["tasks.col_priority"],
      ru["tasks.col_assignee"],
      ru["tasks.col_due"],
      ru["tasks.col_project"],
      ru["tasks.field_description"],
      "Автор",
    ]);
    const dd = document.querySelector("dl.ui-props")!.lastElementChild as HTMLElement;
    expect(dd.tagName).toBe("DD");
    expect(dd.getAttribute("data-field")).toBe("author");
  });
});

describe("R7-T19 комментарии", () => {
  const comment = (id: string, author: typeof BOT) => ({
    id,
    task_id: "a1a1a1a1-0000-4000-8000-000000000001",
    author,
    body: "Текст",
    created_at: "2026-10-12T21:30:00Z",
    edited_at: null,
    is_deleted: false,
    permissions: { edit: false, delete: false },
  });
  const C1 = "d1d1d1d1-0000-4000-8000-000000000001";
  const C2 = "d2d2d2d2-0000-4000-8000-000000000002";
  const C3 = "d3d3d3d3-0000-4000-8000-000000000003";

  it("007_fr31_comment_author_mark_only_for_agent", async () => {
    await openCard(() => card(), {
      [COMMENTS_GET]: () => j(200, page([comment(C1, BOT), comment(C2, HUMAN)])),
    });
    await waitFor(() => expect(document.querySelector(`[data-comment-id="${C1}"]`)).not.toBeNull());
    const a = document.querySelector<HTMLElement>(`[data-comment-id="${C1}"] [data-field="author"]`)!;
    const h = document.querySelector<HTMLElement>(`[data-comment-id="${C2}"] [data-field="author"]`)!;
    expectAgentMark(a, "bot-agent");
    expect(h.textContent).toBe("kuznetsov");
    expect(marks(h)).toHaveLength(0);
  });

  it("007_fr31_deleted_comment_of_agent_keeps_author_mark", async () => {
    await openCard(() => card(), {
      [COMMENTS_GET]: () => j(200, page([{ ...comment(C3, BOT), body: null, is_deleted: true }])),
    });
    await waitFor(() => expect(document.querySelector(`[data-comment-id="${C3}"]`)).not.toBeNull());
    const a = document.querySelector<HTMLElement>(`[data-comment-id="${C3}"] [data-field="author"]`)!;
    expectAgentMark(a, "bot-agent");
  });
});
