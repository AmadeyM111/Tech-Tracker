// 012 по утверждённым макетам: значок (99+), список (Новое, Прочитано, Прочитать все), пустое
// состояние, подсказка «@» (стрелки, Enter, нет совпадений), упоминание в тексте — не ссылка.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Comments } from "../../../src/features/comments/Comments";
import { MentionText, insertMention, mentionAt } from "../../../src/features/comments/MentionSuggest";
import { badgeText } from "../../../src/features/notifications/Badge";
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
    created_at: "2026-11-08T06:12:00Z",
    read: false,
    ...over,
  };
}

const listOf = (items: unknown[], unread: number) => ({ items, page: 1, page_size: 50, has_next: false, unread });

afterEach(() => vi.unstubAllGlobals());

describe("notifications", () => {
  it("ac8_menu_badge_shows_unread_count", async () => {
    installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 3 }),
      "GET /api/v1/projects": () => j(200, page([])),
    });
    const { container } = renderApp("/projects");
    await waitFor(() => expect(container.querySelector('.nav-badge[data-unread="3"]')?.textContent).toBe("3"));
    const link = container.querySelector('a[href="/notifications"]');
    expect(link?.getAttribute("aria-label")).toBe("Уведомления, непрочитанных: 3");
  });

  it("badge_caps_at_99_plus", () => {
    expect(badgeText(7)).toBe("7");
    expect(badgeText(99)).toBe("99");
    expect(badgeText(100)).toBe("99+");
  });

  it("list_layout_new_tag_mark_read_and_open", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 1 }),
      [LIST]: () => j(200, listOf([note("n1"), note("n2", { kind: "review_requested", read: true, actor: null })], 1)),
      [READ]: () => new Response(null, { status: 204 }),
      [`GET /api/v1/tasks/${TASK}`]: () => j(404, { detail: "x", code: "not_found" }),
    });
    const { container } = renderApp("/notifications");
    expect(await screen.findByText("За последние 90 дней · новые сверху")).toBeTruthy();
    const unread = container.querySelector<HTMLElement>('li[data-notification-id="n1"]')!;
    expect(unread.className).toContain("is-unread");
    expect(within(unread).getByText("Новое")).toBeTruthy();
    expect(unread.querySelector(".notif-meta")?.textContent).toBe("Сверить остатки · Магазин · ivanov · 08.11, 09:12");
    const read = container.querySelector<HTMLElement>('li[data-notification-id="n2"]')!;
    expect(within(read).getByRole("button", { name: "Задача перешла на проверку" })).toBeTruthy();
    expect(within(read).queryByRole("button", { name: "Прочитано" })).toBeNull();

    fireEvent.click(within(unread).getByRole("button", { name: "Прочитано" }));
    await waitFor(() => expect(f.count(READ)).toBe(1));
    expect(await f.last(READ).json()).toEqual({ ids: ["n1"], all: false });

    fireEvent.click(within(unread).getByRole("button", { name: "Вас назначили исполнителем" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/tasks/${TASK}`));
  });

  it("read_all_sends_all_true", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 1 }),
      [LIST]: () => j(200, listOf([note("n1")], 1)),
      [READ]: () => new Response(null, { status: 204 }),
    });
    renderApp("/notifications");
    fireEvent.click(await screen.findByRole("button", { name: "Прочитать все" }));
    await waitFor(() => expect(f.count(READ)).toBe(1));
    expect(await f.last(READ).json()).toEqual({ all: true });
  });

  it("empty_state_texts", async () => {
    installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [UNREAD]: () => j(200, { unread: 0 }),
      [LIST]: () => j(200, listOf([], 0)),
    });
    renderApp("/notifications");
    expect(await screen.findByText("Уведомлений пока нет")).toBeTruthy();
    expect(screen.getByText("Здесь появятся назначения, проверки, упоминания и сроки за последние 90 дней.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Прочитать все" })).toBeNull();
  });
});

describe("mentions (FR-1, FR-2)", () => {
  it("token_parsing_like_server", () => {
    expect(mentionAt("привет @iv", 10)).toBe("iv");
    expect(mentionAt("привет @", 8)).toBe("");
    expect(mentionAt("mail x@iv", 9)).toBeNull();
    expect(mentionAt("привет@iv", 9)).toBeNull();
    expect(mentionAt("@iv потом", 9)).toBeNull();
    expect(insertMention("привет @iv", 10, "ivanov")).toEqual({ text: "привет @ivanov ", caret: 15 });
  });

  it("mention_in_text_is_highlighted_not_a_link", () => {
    const { container } = render(<MentionText text="Пишу @smirnova, чтобы x@mail.ru не считался" />);
    const spans = container.querySelectorAll(".mention");
    expect(Array.from(spans).map((s) => s.textContent)).toEqual(["@smirnova"]);
    expect(container.querySelector("a")).toBeNull();
  });

  it("suggest_arrows_enter_and_no_match", async () => {
    const f = installFetch({
      [`GET /api/v1/tasks/${TASK}/comments`]: () => j(200, page([])),
      [`GET /api/v1/projects/${P1}/members`]: () =>
        j(
          200,
          page(
            [
              { user: { id: "a", login: "ivanov" }, role: "user", is_blocked: false, is_owner: false },
              { user: { id: "b", login: "ivashkin" }, role: "user", is_blocked: false, is_owner: false },
              { user: { id: "c", login: "ivanova" }, role: "user", is_blocked: true, is_owner: false },
            ],
            1,
            false,
            100,
          ),
        ),
    });
    const alert = { message: null as string | null, seq: 0, show: vi.fn(), clear: vi.fn() };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <Comments taskId={TASK} projectId={P1} alert={alert} />
      </QueryClientProvider>,
    );
    const area = await screen.findByRole("textbox");
    expect(f.count(`GET /api/v1/projects/${P1}/members`)).toBe(0);
    fireEvent.change(area, { target: { value: "Проверьте, @iv", selectionStart: 14 } });
    const list = await screen.findByRole("listbox");
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["@ivanov", "@ivashkin"]);
    expect(screen.getByText("Логины участников проекта, до 10. Enter — вставить логин.")).toBeTruthy();
    fireEvent.keyDown(area, { key: "ArrowDown" });
    expect(within(list).getByRole("option", { selected: true }).textContent).toBe("@ivashkin");
    fireEvent.keyDown(area, { key: "Enter" });
    await waitFor(() => expect((area as HTMLTextAreaElement).value).toBe("Проверьте, @ivashkin "));

    fireEvent.change(area, { target: { value: "Спасибо, @zz", selectionStart: 12 } });
    expect(await screen.findByText("Нет участников с логином, начинающимся на «zz».")).toBeTruthy();
  });
});
