// T91 (2): оптимистичное обновление при переносе. Контракт - в шапке ./helpers.
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorMessage } from "../../../src/shared/i18n";
import {
  BOARD,
  CA,
  CB,
  CC,
  INITIAL,
  MOVE,
  NO_CONTENT,
  TA,
  TB,
  TC,
  TD,
  boardBody,
  cardEl,
  column,
  deferred,
  err,
  idsIn,
  installLayout,
  j,
  keyboardDrag,
  openBoard,
  pointerDrag,
} from "./helpers";

afterEach(() => {
  vi.useRealTimers();
});

const REORDERED = { ...INITIAL, todo: [CA, CC, CB] };

function server() {
  const s = { cols: INITIAL as Record<string, unknown[]> };
  return { s, handler: () => j(200, boardBody(s.cols as typeof INITIAL)) };
}

describe("T91 optimistic move", () => {
  it("t91_keyboard_reorder_shown_before_server_answer_then_reread", async () => {
    installLayout();
    const d = deferred<Response>();
    const { s, handler } = server();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => d.promise, [BOARD]: handler });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(f.count(MOVE(TB))).toBe(1));
    // сервер ещё не ответил и отдаёт старый порядок: новый порядок - оптимистичный
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TC, TB]));
    const reads = f.count(BOARD);
    s.cols = REORDERED;
    d.resolve(NO_CONTENT());
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(reads));
    expect(idsIn(container, "todo")).toEqual([TA, TC, TB]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("t91_keyboard_move_to_other_column_shown_before_answer", async () => {
    installLayout();
    const d = deferred<Response>();
    const { f, container } = await openBoard({ [MOVE(TD)]: () => d.promise });
    await keyboardDrag(cardEl(container, TD)!, ["ArrowRight"]);
    await waitFor(() => expect(f.count(MOVE(TD))).toBe(1));
    await waitFor(() => expect(idsIn(container, "review")).toEqual([TD]));
    expect(idsIn(container, "in_progress")).toEqual([]);
    expect(column(container, "in_progress")!.querySelector('[data-role="empty"]')).toBeTruthy();
    expect(column(container, "review")!.querySelector('[data-role="empty"]')).toBeNull();
    d.resolve(NO_CONTENT());
  });

  it("t91_pointer_move_shown_before_server_answer", async () => {
    installLayout();
    const d = deferred<Response>();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => d.promise });
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 140, y: 155 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TA, TC]));
    d.resolve(NO_CONTENT());
  });

  it.each([
    [403, "forbidden"],
    [422, "validation_error"],
    [503, "service_busy"],
  ])("t91_http_%i_rolls_back_to_server_data_with_single_alert", async (status, code) => {
    installLayout();
    const d = deferred<Response>();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => d.promise });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TC, TB]));
    const reads = f.count(BOARD);
    d.resolve(err(status, code));
    const a = await screen.findByRole("alert");
    expect(a.textContent).toBe(errorMessage(code));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC]));
    expect(f.count(BOARD)).toBeGreaterThan(reads);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("t91_fetch_rejection_rolls_back_with_network_alert", async () => {
    installLayout();
    let reject: (e: unknown) => void = () => {};
    const { container } = await openBoard({
      [MOVE(TB)]: () =>
        new Promise<Response>((_, rej) => {
          reject = rej;
        }),
    });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TC, TB]));
    reject(new TypeError("Failed to fetch"));
    const a = await screen.findByRole("alert");
    expect(a.textContent).toBe(errorMessage("network_error"));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC]));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("t91_poll_tick_during_request_does_not_overwrite_optimistic_state", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installLayout();
    const d = deferred<Response>();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => d.promise });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TC, TB]));
    await vi.advanceTimersByTimeAsync(15_000);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(idsIn(container, "todo")).toEqual([TA, TC, TB]);
    expect(f.count(MOVE(TB))).toBe(1);
    d.resolve(NO_CONTENT());
  });

  it("t91_focus_stays_on_card_after_optimistic_move", async () => {
    installLayout();
    const d = deferred<Response>();
    const { container } = await openBoard({ [MOVE(TB)]: () => d.promise });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TC, TB]));
    d.resolve(NO_CONTENT());
    await waitFor(() => expect(document.activeElement).toBe(cardEl(container, TB)));
  });

  it("t91_escape_keeps_server_order_and_sends_nothing", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"], "Escape");
    await new Promise((r) => setTimeout(r, 20));
    expect(f.count(MOVE(TB))).toBe(0);
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
    void CB;
  });
});
