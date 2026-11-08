// 012/AC-8, FR-2, FR-5: значок в меню, список уведомлений, «прочитано», подсказка «@».
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MentionSuggest, insertMention, mentionAt } from "../../../src/features/comments/MentionSuggest";
import { installFetch, j, meWith, page, renderApp } from "../admin/helpers";

const ME = "GET /api/v1/me";
const UNREAD = "GET /api/v1/me/notifications/unread";
const LIST = "GET /api/v1/me/notifications";
const READ = "POST /api/v1/me/notifications/read";
const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const TASK = "44444444-4444-4444-8444-444444444444";
const P1 = "33333333-3333-4333-8333-333333333333";

function note(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    kind: "assigned",
    task: { id: TASK, title: "Сверить остатки" },
    project: { id: P1, name: "Магазин" },
    actor: { id: "u1", login: "ivanov" },
    created_at: "2026-11-08T09:00:00Z",
    read: false,
    ...over,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("notifications", () => {
  it("ac8_menu_badge_shows_unread_count", async () => {
    installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 3 }),
      "GET /api/v1/projects": () => j(200, page([])),
    });
    const { container } = renderApp("/projects");
    await waitFor(() => expect(container.querySelector('[data-unread="3"]')).not.toBeNull());
    const link = container.querySelector('a[href="/notifications"]');
    expect(link?.getAttribute("aria-label")).toBe("Уведомления, непрочитанных: 3");
  });

  it("list_click_marks_read_and_opens_task", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 1 }),
      [LIST]: () =>
        j(200, { items: [note("n1"), note("n2", { kind: "mentioned", read: true, actor: null })], page: 1, page_size: 50, has_next: false, unread: 1 }),
      [READ]: () => new Response(null, { status: 204 }),
      [`GET /api/v1/tasks/${TASK}`]: () => j(404, { detail: "x", code: "not_found" }),
    });
    renderApp("/notifications");
    const first = await screen.findByRole("button", { name: /Вас назначили исполнителем: Сверить остатки/ });
    expect(screen.getByText(/Вас упомянули в комментарии: Сверить остатки/)).toBeTruthy();
    fireEvent.click(first);
    await waitFor(() => expect(f.count(READ)).toBe(1));
    expect(await f.last(READ).json()).toEqual({ ids: ["n1"], all: false });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/tasks/${TASK}`));
  });

  it("read_all_sends_all_true", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 1 }),
      [LIST]: () => j(200, { items: [note("n1")], page: 1, page_size: 50, has_next: false, unread: 1 }),
      [READ]: () => new Response(null, { status: 204 }),
    });
    renderApp("/notifications");
    fireEvent.click(await screen.findByRole("button", { name: "Прочитать все" }));
    await waitFor(() => expect(f.count(READ)).toBe(1));
    expect(await f.last(READ).json()).toEqual({ all: true });
  });

  it("empty_list_text", async () => {
    installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 0 }),
      [LIST]: () => j(200, { items: [], page: 1, page_size: 50, has_next: false, unread: 0 }),
    });
    renderApp("/notifications");
    expect(await screen.findByText("Уведомлений за 30 дней нет")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Прочитать все" })).toBeNull();
  });
});

describe("mention suggestions (FR-2)", () => {
  it("parses_the_token_before_the_caret", () => {
    expect(mentionAt("привет @iv", 10)).toBe("iv");
    expect(mentionAt("привет @", 8)).toBe("");
    expect(mentionAt("mail x@iv", 9)).toBeNull();
    expect(mentionAt("@iv потом", 9)).toBeNull();
    expect(insertMention("привет @iv", 10, "ivanov")).toEqual({ text: "привет @ivanov ", caret: 15 });
  });

  it("suggests_active_members_by_prefix_and_requests_only_on_at", async () => {
    const f = installFetch({
      [`GET /api/v1/projects/${P1}/members`]: () =>
        j(200, page([
          { user: { id: "a", login: "ivanov" }, role: "user", is_blocked: false, is_owner: false },
          { user: { id: "b", login: "ivanova" }, role: "user", is_blocked: true, is_owner: false },
          { user: { id: "c", login: "petrov" }, role: "user", is_blocked: false, is_owner: false },
        ], 1, false, 100)),
    });
    const onPick = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <MentionSuggest projectId={P1} partial={null} onPick={onPick} />
      </QueryClientProvider>,
    );
    expect(f.calls).toHaveLength(0);
    rerender(
      <QueryClientProvider client={qc}>
        <MentionSuggest projectId={P1} partial="iv" onPick={onPick} />
      </QueryClientProvider>,
    );
    const option = await screen.findByRole("button", { name: "@ivanov" });
    expect(screen.queryByRole("button", { name: "@ivanova" })).toBeNull();
    expect(screen.queryByRole("button", { name: "@petrov" })).toBeNull();
    fireEvent.click(option);
    expect(onPick).toHaveBeenCalledWith("ivanov");
  });
});
