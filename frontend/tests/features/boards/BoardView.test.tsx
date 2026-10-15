// T86: канбан-доска (вкладка «Доска» страницы проекта).
// AC: UF-5, FR-18a (4 колонки), FR-28/FR-28a (клиент передаёт соседей), FR-29 (опрос),
//     FR-19b (отказ 403 - откат с сообщением), AC-5 (ручной, подготовка), AC-97 (клавиатура),
//     NFR-5 (срок без пересчёта пояса), NFR-6 (строки из словаря), NFR-7 (доступность).
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorMessage, t } from "../../../src/shared/i18n";
import {
  BOARD,
  CA,
  CB,
  CC,
  CD,
  CE,
  INITIAL,
  MOVE,
  STATUSES,
  TA,
  TB,
  TC,
  TD,
  TE,
  boardBody,
  card,
  cardEl,
  column,
  dict,
  err,
  idsIn,
  installLayout,
  j,
  keyboardDrag,
  NO_CONTENT,
  openBoard,
  pointerDrag,
  ru,
} from "./helpers";

const f_ = (scope: ParentNode, n: string) => scope.querySelector<HTMLElement>(`[data-field="${n}"]`);
const DICT = Object.values(ru) as string[];

afterEach(() => {
  vi.useRealTimers();
});

async function body(r: Request) {
  const b = (await r.clone().json()) as Record<string, unknown>;
  return {
    status: b.status,
    after: (b.after_task_id ?? null) as string | null,
    before: (b.before_task_id ?? null) as string | null,
  };
}

describe("rendering", () => {
  it("fr18a_four_columns_in_order_with_dictionary_titles", async () => {
    const { container } = await openBoard();
    const cols = Array.from(container.querySelectorAll<HTMLElement>("[data-column]"));
    expect(cols.map((c) => c.dataset.column)).toEqual([...STATUSES]);
    for (const c of cols) {
      const labelId = c.getAttribute("aria-labelledby");
      expect(labelId).toBeTruthy();
      expect(document.getElementById(labelId!)?.textContent).toBe(
        ru[`tasks.status.${c.dataset.column}` as keyof typeof ru],
      );
    }
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
    expect(idsIn(container, "in_progress")).toEqual([TD]);
    expect(idsIn(container, "done")).toEqual([TE]);
  });

  it("uf5_card_shows_title_link_priority_due_assignee_progress", async () => {
    const { container } = await openBoard();
    const a = cardEl(container, TA)!;
    const link = f_(a, "title")!.querySelector("a")!;
    expect(link.getAttribute("href")).toBe(`/tasks/${TA}`);
    expect(link.textContent).toBe(CA.title);
    expect(f_(a, "priority")!.textContent).toBe(ru["tasks.priority.high"]);
    expect(f_(cardEl(container, TB)!, "priority")!.textContent).toBe(ru["tasks.priority.base"]);
    const time = f_(a, "due_date")!.querySelector("time")!;
    expect(time.getAttribute("datetime")).toBe("2026-12-31");
    expect(time.textContent).toBe("31.12.2026");
    expect(f_(a, "assignee")!.textContent).toBe("kuznetsov");
    expect(f_(a, "progress")!.textContent).toBe(t("tasks.progress_value", { percent: 50 }));
  });

  it("uf5_card_without_due_assignee_progress_uses_dictionary_texts", async () => {
    const { container } = await openBoard();
    const b = cardEl(container, TB)!;
    expect(f_(b, "due_date")!.textContent).toBe(ru["tasks.due_none"]);
    expect(f_(b, "due_date")!.querySelector("time")).toBeNull();
    expect(f_(b, "assignee")!.textContent).toBe(ru["tasks.assignee_none"]);
    expect(f_(b, "progress")!.textContent).toBe(ru["tasks.progress_none"]);
  });

  it("uf5_zero_progress_is_a_number_not_none", async () => {
    const { container } = await openBoard();
    expect(f_(cardEl(container, TC)!, "progress")!.textContent).toBe(
      t("tasks.progress_value", { percent: 0 }),
    );
    expect(f_(cardEl(container, TC)!, "due_date")!.querySelector("time")!.textContent).toBe("05.01.2026");
  });

  it("nfr5_due_date_does_not_depend_on_timezone_or_date", async () => {
    const dateSpy = vi.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(-720);
    const { container } = await openBoard();
    expect(f_(cardEl(container, TA)!, "due_date")!.querySelector("time")!.textContent).toBe("31.12.2026");
    dateSpy.mockRestore();
  });

  it("fr18a_empty_column_shows_dictionary_text", async () => {
    const { container } = await openBoard();
    const review = column(container, "review")!;
    expect(review.querySelector("[data-task-id]")).toBeNull();
    expect(within(review).getByText(dict("boards.empty_column"))).toBeTruthy();
    expect(column(container, "todo")!.querySelector('[data-role="empty"]')).toBeNull();
  });

  it("nfr6_all_visible_texts_are_from_dictionary_or_data", async () => {
    const { container } = await openBoard();
    const titles = [CA, CB, CC, CD, CE].map((c) => c.title);
    for (const col of Array.from(container.querySelectorAll<HTMLElement>("[data-column]"))) {
      for (const el of Array.from(col.querySelectorAll<HTMLElement>("h3, [data-role=empty], [data-field]"))) {
        if (el.dataset.field === "title") {
          expect(titles).toContain(el.textContent);
        } else if (el.dataset.field === "assignee" && el.textContent !== ru["tasks.assignee_none"]) {
          expect(["kuznetsov", "admin"]).toContain(el.textContent);
        } else if (el.dataset.field === "progress" && /^\d+%$/.test(el.textContent ?? "")) {
          expect(el.textContent).toBe(t("tasks.progress_value", { percent: parseInt(el.textContent!, 10) }));
        } else if (el.querySelector("time")) {
          expect(el.textContent).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
        } else {
          expect(DICT).toContain(el.textContent);
        }
      }
    }
  });
});

describe("accessibility", () => {
  it("nfr7_columns_lists_and_cards_have_names_and_ru_dnd_descriptions", async () => {
    const { container } = await openBoard();
    for (const s of STATUSES) {
      const list = column(container, s)!.querySelector<HTMLElement>('[data-role="column-cards"]')!;
      expect(list.getAttribute("aria-label")).toContain(ru[`tasks.status.${s}` as keyof typeof ru]);
    }
    const a = cardEl(container, TA)!;
    expect(a.tabIndex).toBe(0);
    expect(a.getAttribute("aria-roledescription")).toBe(dict("boards.card_roledescription"));
    const descId = a.getAttribute("aria-describedby");
    expect(descId).toBeTruthy();
    expect(document.getElementById(descId!)?.textContent).toBe(dict("boards.dnd_instructions"));
  });

  it("ac97_focus_stays_on_card_after_keyboard_move", async () => {
    installLayout();
    const { container } = await openBoard();
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(document.activeElement).toBe(cardEl(container, TB)));
    expect(document.activeElement?.getAttribute("data-task-id")).toBe(TB);
  });

  it("nfr7_live_announcements_are_russian_without_ids", async () => {
    installLayout();
    const { container } = await openBoard();
    const el = cardEl(container, TB)!;
    el.focus();
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.keyDown(el, { key: " ", code: "Space" });
    await new Promise((r) => setTimeout(r, 10));
    const live = Array.from(document.querySelectorAll('[aria-live]'))
      .map((n) => n.textContent ?? "")
      .join(" ");
    expect(live.trim().length).toBeGreaterThan(0);
    expect(live).not.toMatch(/[A-Za-z]/);
    expect(live).toContain(CB.title);
  });
});

describe("keyboard move", () => {
  it("fr28a_keyboard_move_down_within_column_posts_neighbors", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(1));
    expect(await body(f.last(MOVE(TB)))).toEqual({ status: "todo", after: TC, before: null });
  });

  it("fr28a_keyboard_move_up_within_column_posts_neighbors", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TC)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TC)!, ["ArrowUp", "ArrowUp"]);
    await waitFor(() => expect(f.count(MOVE(TC))).toBe(1));
    expect(await body(f.last(MOVE(TC)))).toEqual({ status: "todo", after: null, before: TA });
  });

  it("fr28_keyboard_move_to_empty_column_posts_target_status_without_neighbors", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TD)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TD)!, ["ArrowRight"]);
    await waitFor(() => expect(f.count(MOVE(TD))).toBe(1));
    expect(await body(f.last(MOVE(TD)))).toEqual({ status: "review", after: null, before: null });
  });

  it("fr28a_keyboard_move_to_column_with_card_posts_adjacent_slot", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TA)!, ["ArrowRight"]);
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    // раскладка: центры карточек A и D совпадают (y=65) - ровно по центру, значит над D
    expect(await body(f.last(MOVE(TA)))).toEqual({ status: "in_progress", after: null, before: TD });
  });

  it("fr28_escape_cancels_without_request", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"], "Escape");
    await new Promise((r) => setTimeout(r, 20));
    expect(f.count(MOVE(TB))).toBe(0);
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
  });

  it("fr28_drop_on_same_place_sends_no_request", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TB)!, []);
    await new Promise((r) => setTimeout(r, 20));
    expect(f.count(MOVE(TB))).toBe(0);
  });
});

const LONG = {
  ...INITIAL,
  in_progress: [0, 1, 2, 3, 4].map((i) => card(`c${i}c${i}c${i}c${i}-0000-4000-8000-00000000000${i}`, `Долгая ${i}`, "in_progress", i)),
  review: [],
};
const LONG_IDS = LONG.in_progress.map((c) => c.id);

describe("review fixes", () => {
  it("b1_enter_and_space_on_title_link_do_not_start_drag", async () => {
    const { container } = await openBoard();
    const link = f_(cardEl(container, TB)!, "title")!.querySelector("a")!;
    link.focus();
    const { fireEvent } = await import("@testing-library/react");
    expect(fireEvent.keyDown(link, { key: "Enter", code: "Enter" })).toBe(true);
    expect(fireEvent.keyDown(link, { key: " ", code: "Space" })).toBe(true);
    await new Promise((r) => setTimeout(r, 10));
    const live = Array.from(document.querySelectorAll("[aria-live]"))
      .map((n) => n.textContent ?? "")
      .join(" ");
    expect(live).not.toContain(CB.title);
  });

  it("b1_space_on_card_itself_starts_drag", async () => {
    installLayout();
    const { container } = await openBoard();
    const el = cardEl(container, TB)!;
    el.focus();
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.keyDown(el, { key: " ", code: "Space" });
    await new Promise((r) => setTimeout(r, 10));
    const live = Array.from(document.querySelectorAll("[aria-live]"))
      .map((n) => n.textContent ?? "")
      .join(" ");
    expect(live).toContain(CB.title);
  });

  it("m13_pickup_announcement_has_title_and_is_not_over_itself", async () => {
    installLayout();
    const { container } = await openBoard();
    const el = cardEl(container, TB)!;
    el.focus();
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.keyDown(el, { key: " ", code: "Space" });
    await new Promise((r) => setTimeout(r, 10));
    const live = Array.from(document.querySelectorAll("[aria-live]"))
      .map((n) => n.textContent ?? "")
      .join(" ");
    expect(live).toContain(CB.title);
    expect(live).not.toContain(`над карточкой «${CB.title}»`);
  });

  it("b2_drop_in_lower_part_of_empty_column_goes_to_that_column", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() }, LONG);
    expect(idsIn(container, "in_progress")).toEqual(LONG_IDS);
    // «Проверка» - третья колонка: x 600..880; y=450 далеко ниже её списка и над длинной соседней
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 740, y: 450 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(await body(f.last(MOVE(TA)))).toEqual({ status: "review", after: null, before: null });
  });

  it("m4_drop_below_last_card_of_non_empty_column_goes_to_its_end", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TD)]: () => NO_CONTENT() });
    await pointerDrag(cardEl(container, TD)!, { x: 440, y: 65 }, { x: 140, y: 450 });
    await waitFor(() => expect(f.count(MOVE(TD))).toBe(1));
    expect(await body(f.last(MOVE(TD)))).toEqual({ status: "todo", after: TC, before: null });
  });

  it("b3_pointer_drop_on_lower_half_of_card_in_other_column_goes_after_it", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() });
    // центр A = 65, центр D = 65; сдвиг на +15 по y -> центр A ниже центра D
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 440, y: 80 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(await body(f.last(MOVE(TA)))).toEqual({ status: "in_progress", after: TD, before: null });
  });

  it("b3_pointer_drop_on_upper_half_of_card_in_other_column_goes_before_it", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() });
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 440, y: 55 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(await body(f.last(MOVE(TA)))).toEqual({ status: "in_progress", after: null, before: TD });
  });
});

describe("gaps and headings (R1)", () => {
  it("r1_drop_into_gap_between_cards_of_other_column_goes_between_them", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() }, LONG);
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 440, y: 95 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(await body(f.last(MOVE(TA)))).toEqual({
      status: "in_progress",
      after: LONG_IDS[0],
      before: LONG_IDS[1],
    });
  });

  it("r1_drop_into_gap_below_in_same_column_goes_between_neighbors", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() });
    // A (центр 65) -> промежуток между B (100..150) и C (160..210): центр 155
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 140, y: 155 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(await body(f.last(MOVE(TA)))).toEqual({ status: "todo", after: TB, before: TC });
  });

  it("r1_drop_into_gap_above_in_same_column_goes_between_neighbors", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TC)]: () => NO_CONTENT() });
    // C (центр 185) -> промежуток между A (40..90) и B (100..150), ближе к B
    await pointerDrag(cardEl(container, TC)!, { x: 140, y: 185 }, { x: 140, y: 96 });
    await waitFor(() => expect(f.count(MOVE(TC))).toBe(1));
    expect(await body(f.last(MOVE(TC)))).toEqual({ status: "todo", after: TA, before: TB });
  });

  it("r1_drop_into_gap_next_to_own_place_sends_no_request", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => NO_CONTENT() });
    // B (центр 125) -> промежуток между A и B: порядок A,B,C не меняется
    await pointerDrag(cardEl(container, TB)!, { x: 140, y: 125 }, { x: 140, y: 95 });
    await new Promise((r) => setTimeout(r, 30));
    expect(f.count(MOVE(TB))).toBe(0);
  });

  it("r1_drop_on_column_heading_goes_to_start_of_column", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TD)]: () => NO_CONTENT() });
    await pointerDrag(cardEl(container, TD)!, { x: 440, y: 65 }, { x: 140, y: 20 });
    await waitFor(() => expect(f.count(MOVE(TD))).toBe(1));
    expect(await body(f.last(MOVE(TD)))).toEqual({ status: "todo", after: null, before: TA });
  });
});

describe("frozen and moving (R3/R4)", () => {
  it("r3_poll_tick_during_keyboard_drag_does_not_change_dom_until_escape", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installLayout();
    let step = 0;
    const { container } = await openBoard({
      [BOARD]: () => j(200, boardBody(step === 0 ? INITIAL : { ...INITIAL, todo: [CB, CC] })),
    });
    const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const el = cardEl(container, TB)!;
    el.focus();
    fireEvent.keyDown(el, { key: " ", code: "Space" });
    await tick();
    step = 1;
    await vi.advanceTimersByTimeAsync(15_000);
    await tick();
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
    fireEvent.keyDown(document.activeElement ?? el, { key: "Escape", code: "Escape" });
    await tick();
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
  });

  it("r4_second_move_is_not_sent_while_first_post_is_in_flight", async () => {
    installLayout();
    let release: () => void = () => {};
    const { f, container } = await openBoard({
      [MOVE(TB)]: () =>
        new Promise<Response>((r) => {
          release = () => r(NO_CONTENT());
        }),
      [MOVE(TA)]: () => NO_CONTENT(),
    });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(1));
    await keyboardDrag(cardEl(container, TA)!, ["ArrowDown"]);
    await new Promise((r) => setTimeout(r, 20));
    expect(f.count(MOVE(TA))).toBe(0);
    const boards = f.count(BOARD);
    release();
    await waitFor(() => expect(f.count(BOARD)).toBe(boards + 1));
    await keyboardDrag(cardEl(container, TA)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
  });
});

describe("after move", () => {
  it("fr28_success_invalidates_board_and_shows_server_order", async () => {
    installLayout();
    let moved = false;
    const { f, container } = await openBoard({
      [MOVE(TB)]: () => {
        moved = true;
        return NO_CONTENT();
      },
      [BOARD]: () =>
        j(200, boardBody(moved ? { ...INITIAL, todo: [CA, CC, { ...CB, position: 40 }] } : INITIAL)),
    });
    const before = f.count(BOARD);
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(BOARD)).toBe(before + 1));
    expect(f.last(BOARD).headers.get("X-GT-Background")).toBeNull();
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TC, TB]));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    [403, "forbidden"],
    [422, "invalid_neighbors"],
    [503, "service_busy"],
  ])("fr19b_move_error_%i_shows_single_alert_and_returns_server_data", async (status, code) => {
    installLayout();
    const { f, container } = await openBoard({
      [MOVE(TB)]: () => err(status, code),
    });
    const before = f.count(BOARD);
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    await waitFor(() => expect(f.count(BOARD)).toBe(before + 1));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC]));
    expect(f.count(MOVE(TB))).toBe(1);
  });

  it("fr19b_next_successful_move_clears_previous_error", async () => {
    installLayout();
    let fail = true;
    const { f, container } = await openBoard({
      [MOVE(TB)]: () => (fail ? err(403, "forbidden") : NO_CONTENT()),
    });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await screen.findByRole("alert");
    await waitFor(() => expect(f.count(BOARD)).toBe(2));
    fail = false;
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(2));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("polling and load errors", () => {
  it("fr29_board_is_polled_with_background_header", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { f } = await openBoard();
    expect(f.last(BOARD).headers.get("X-GT-Background")).toBeNull();
    const n = f.count(BOARD);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(n));
    expect(f.last(BOARD).headers.get("X-GT-Background")).toBe("1");
  });

  it("fr29_poll_tick_updates_cards", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let step = 0;
    const { container } = await openBoard({
      [BOARD]: () => j(200, boardBody(step === 0 ? INITIAL : { ...INITIAL, todo: [CB, CA, CC] })),
    });
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
    step = 1;
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TA, TC]));
  });

  it("uf5_load_error_shows_single_alert_without_columns", async () => {
    const { installFetch, renderApp } = await import("./helpers");
    const { boardRoutes, PID } = await import("./helpers");
    installFetch(boardRoutes({ [BOARD]: () => err(403, "forbidden") }));
    const view = renderApp(`/projects/${PID}`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(view.container.querySelector("[data-column]")).toBeNull();
  });
});

// T86 review 3: высокие карточки, M6, move_busy, finally.
function tallLayout(tops: Record<string, [number, number]>) {
  installLayout();
  const rect = (x: number, y: number, w: number, h: number): DOMRect =>
    ({ x, y, left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, toJSON() {} }) as DOMRect;
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const el = this as HTMLElement;
    const col = el.closest("[data-column]") as HTMLElement | null;
    if (!col) return rect(0, 0, 0, 0);
    const ci = STATUSES.indexOf(col.dataset.column as (typeof STATUSES)[number]);
    const x = Math.max(ci, 0) * 300;
    if (el === col) return rect(x, 0, 280, 600);
    const c = el.closest("[data-task-id]") as HTMLElement | null;
    if (c) {
      const t = tops[c.dataset.taskId!];
      return t ? rect(x, t[0], 280, t[1]) : rect(x, 40, 280, 50);
    }
    if (el.matches('[data-role="column-cards"]')) return rect(x, 40, 280, 330);
    return rect(x, 0, 280, 40);
  });
}

describe("tall cards (review 3)", () => {
  it("r1_tall_card_grabbed_at_top_dropped_in_gap_below_lands_between_neighbors", async () => {
    tallLayout({ [TA]: [40, 200], [TB]: [250, 50], [TC]: [310, 50] });
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() });
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 45 }, { x: 140, y: 308 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(await body(f.last(MOVE(TA)))).toEqual({ status: "todo", after: TB, before: TC });
  });

  it("r1_tall_card_grabbed_at_bottom_dropped_in_gap_above_lands_between_neighbors", async () => {
    // A 40-90, B 100-150, C 160-360 (высокая)
    tallLayout({ [TA]: [40, 50], [TB]: [100, 50], [TC]: [160, 200] });
    const { f, container } = await openBoard({ [MOVE(TC)]: () => NO_CONTENT() });
    await pointerDrag(cardEl(container, TC)!, { x: 140, y: 355 }, { x: 140, y: 95 });
    await waitFor(() => expect(f.count(MOVE(TC))).toBe(1));
    expect(await body(f.last(MOVE(TC)))).toEqual({ status: "todo", after: TA, before: TB });
  });
});

describe("link, busy and finally (review 3)", () => {
  it("m6_title_link_has_no_pointer_events_during_keyboard_drag_only", async () => {
    installLayout();
    const { container } = await openBoard({ [MOVE(TB)]: () => NO_CONTENT() });
    const link = f_(cardEl(container, TB)!, "title")!.querySelector("a")!;
    expect(link.style.pointerEvents).not.toBe("none");
    const el = cardEl(container, TB)!;
    el.focus();
    fireEvent.keyDown(el, { key: " ", code: "Space" });
    await waitFor(() => expect(f_(cardEl(container, TB)!, "title")!.querySelector("a")!.style.pointerEvents).toBe("none"));
    fireEvent.keyDown(document.activeElement ?? el, { key: "Escape", code: "Escape" });
    await waitFor(() =>
      expect(f_(cardEl(container, TB)!, "title")!.querySelector("a")!.style.pointerEvents).not.toBe("none"),
    );
  });

  it("r4_move_busy_notice_shown_for_second_move_and_gone_after_response", async () => {
    installLayout();
    let release: () => void = () => {};
    const { f, container } = await openBoard({
      [MOVE(TB)]: () =>
        new Promise<Response>((r) => {
          release = () => r(NO_CONTENT());
        }),
      [MOVE(TA)]: () => NO_CONTENT(),
    });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(1));
    await keyboardDrag(cardEl(container, TA)!, ["ArrowDown"]);
    await screen.findByText(t("boards.move_busy"));
    expect(f.count(MOVE(TA))).toBe(0);
    release();
    await waitFor(() => expect(screen.queryByText(t("boards.move_busy"))).toBeNull());
  });

  it.each([
    [403, "forbidden"],
    [500, "internal"],
  ])("r4_finally_after_%i_on_first_move_next_move_is_sent", async (status, code) => {
    installLayout();
    let first = true;
    const { f, container } = await openBoard({
      [MOVE(TB)]: () => {
        if (first) {
          first = false;
          return err(status, code);
        }
        return NO_CONTENT();
      },
    });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(1));
    await screen.findByRole("alert");
    await waitFor(() => expect(f.count(BOARD)).toBe(2));
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(2));
  });
});
