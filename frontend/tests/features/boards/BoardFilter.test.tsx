// T91 (3): клиентский фильтр доски по исполнителю. Контракт - в шапке ./helpers.
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BOARD,
  CA,
  CB,
  CC,
  CD,
  CE,
  INITIAL,
  MOVE,
  NEW_TITLE,
  NO_CONTENT,
  PID,
  PROJ_CREATE,
  R_KUZNETSOV,
  R_ME,
  TA,
  TB,
  TC,
  TD,
  TE,
  TN,
  boardBody,
  cardEl,
  column,
  dict,
  filterSelect,
  idsIn,
  installLayout,
  j,
  keyboardDrag,
  liveBoard,
  openBoard,
  openCreate,
  pickFilter,
  titleInput,
  where,
} from "./helpers";
import { fireEvent } from "@testing-library/react";

afterEach(() => {
  vi.useRealTimers();
});

const body = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
const empty = (c: ParentNode, s: string) => !!column(c, s)!.querySelector('[data-role="empty"]');

describe("T91 assignee filter", () => {
  it("t91_filter_dictionary_keys", () => {
    expect(dict("boards.filter_all")).toBe("Все исполнители");
    expect(dict("boards.filter_none")).toBe("Без исполнителя");
    expect(dict("boards.filter_label").length).toBeGreaterThan(0);
  });

  it("t91_select_is_labelled_inside_board_with_all_none_and_board_assignees_sorted", async () => {
    const { container } = await openBoard();
    const sel = filterSelect();
    expect(container.querySelector('[data-role="board"]')!.contains(sel)).toBe(true);
    expect(sel.getAttribute("name")).toBe("board-assignee");
    const opts = Array.from(sel.options).map((o) => [o.value, o.textContent]);
    expect(opts).toEqual([
      ["", dict("boards.filter_all")],
      ["none", dict("boards.filter_none")],
      [R_ME.id, "admin"],
      [R_KUZNETSOV.id, "kuznetsov"],
    ]);
    expect(sel.value).toBe("");
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
  });

  it("t91_filter_by_member_hides_other_cards_keeps_columns", async () => {
    const { container } = await openBoard();
    pickFilter(R_KUZNETSOV.id);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA]));
    expect(idsIn(container, "in_progress")).toEqual([]);
    expect(idsIn(container, "done")).toEqual([]);
    expect(Array.from(container.querySelectorAll("[data-column]"))).toHaveLength(4);
    for (const s of ["in_progress", "review", "done"]) expect(empty(container, s)).toBe(true);
    expect(empty(container, "todo")).toBe(false);
    expect(column(container, "todo")!.querySelector("h3")!.textContent).toBe("К выполнению");
    expect(cardEl(container, TB)).toBeNull();
  });

  it("t91_filter_none_shows_only_unassigned", async () => {
    const { container } = await openBoard();
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    expect(idsIn(container, "in_progress")).toEqual([]);
    expect(empty(container, "in_progress")).toBe(true);
    expect(idsIn(container, "done")).toEqual([TE]);
  });

  it("t91_back_to_all_restores_every_card", async () => {
    const { container } = await openBoard();
    pickFilter(R_ME.id);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([]));
    expect(idsIn(container, "in_progress")).toEqual([TD]);
    pickFilter("");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC]));
    expect(idsIn(container, "done")).toEqual([TE]);
  });

  it("t91_poll_keeps_filter_and_applies_new_data_to_it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let step = 0;
    const { container, f } = await openBoard({
      [BOARD]: () =>
        j(200, boardBody(step === 0 ? INITIAL : { ...INITIAL, todo: [CB, CA, CC], done: [CE, { ...CE, id: TN, title: "Нов" }] })),
    });
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    step = 1;
    const n = f.count(BOARD);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(n));
    await waitFor(() => expect(idsIn(container, "done")).toEqual([TE, TN]));
    expect(filterSelect().value).toBe("none");
    expect(idsIn(container, "todo")).toEqual([TB, TC]);
  });

  it("t91_filter_is_component_state_only", async () => {
    const { container } = await openBoard();
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    expect(where()).toBe(`/projects/${PID}`);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("t91_filter_does_not_add_alerts", async () => {
    await openBoard();
    pickFilter("none");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("T91 filter with move and create", () => {
  it("t91_move_above_first_visible_card_uses_full_column_order", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TC)]: () => NO_CONTENT() });
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    await keyboardDrag(cardEl(container, TC)!, ["ArrowUp"]);
    await waitFor(() => expect(f.count(MOVE(TC))).toBe(1));
    // в полном порядке A,B,C: C встаёт между A (скрыта фильтром) и B
    expect(await body(f.last(MOVE(TC)))).toMatchObject({ status: "todo", after_task_id: TA, before_task_id: TB });
  });

  it("t91_move_into_visibly_empty_column_with_hidden_cards_goes_to_full_end", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TC)]: () => NO_CONTENT() });
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "in_progress")).toEqual([]));
    await keyboardDrag(cardEl(container, TC)!, ["ArrowRight"]);
    await waitFor(() => expect(f.count(MOVE(TC))).toBe(1));
    const b = await body(f.last(MOVE(TC)));
    expect(b.status).toBe("in_progress");
    expect(b.after_task_id).toBe(TD);
    expect(b.before_task_id ?? null).toBeNull();
  });

  it("t91_filter_survives_a_move", async () => {
    installLayout();
    // серверное состояние меняется после move: перечитывание отдаёт новый порядок A,C,B
    let todo: unknown[] = [CA, CB, CC];
    const { f, container } = await openBoard({
      [BOARD]: () => j(200, boardBody({ ...INITIAL, todo })),
      [MOVE(TC)]: () => {
        todo = [CA, CC, CB];
        return NO_CONTENT();
      },
    });
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    const reads = f.count(BOARD);
    await keyboardDrag(cardEl(container, TC)!, ["ArrowUp"]);
    await waitFor(() => expect(f.count(MOVE(TC))).toBe(1));
    expect(await body(f.last(MOVE(TC)))).toMatchObject({ status: "todo", after_task_id: TA, before_task_id: TB });
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(reads));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TC, TB]));
    expect(filterSelect().value).toBe("none");
    expect(cardEl(container, TA)).toBeNull();
  });

  it("t91_create_with_filter_keeps_filter_and_shows_new_unassigned_card", async () => {
    const live = liveBoard();
    const { container, f } = await openBoard(live.routes);
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    const form = openCreate(container, "review");
    fireEvent.change(titleInput(form), { target: { value: NEW_TITLE } });
    fireEvent.submit(form);
    await waitFor(() => expect(idsIn(container, "review")).toEqual([TN]));
    expect(await body(f.last(PROJ_CREATE))).toEqual({ title: NEW_TITLE });
    expect(filterSelect().value).toBe("none");
    expect(idsIn(container, "todo")).toEqual([TB, TC]);
    expect(f.count(MOVE(TN))).toBe(1);
  });

  it("t91_create_under_other_member_filter_still_posts_and_hides_unassigned_new_card", async () => {
    const live = liveBoard();
    const { container, f } = await openBoard(live.routes);
    pickFilter(R_KUZNETSOV.id);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA]));
    const form = openCreate(container, "todo");
    fireEvent.change(titleInput(form), { target: { value: NEW_TITLE } });
    fireEvent.submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect(await body(f.last(PROJ_CREATE))).toEqual({ title: NEW_TITLE });
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(1));
    expect(filterSelect().value).toBe(R_KUZNETSOV.id);
    expect(idsIn(container, "todo")).toEqual([TA]);
    pickFilter("");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC, TN]));
    void CD;
  });
});

describe("T91-R vanished assignee", () => {
  it("t91r_filter_resets_to_all_when_assignee_vanishes_and_stays_all_when_he_returns", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let step = 0;
    const gone = { ...INITIAL, todo: [CB, CC] };
    const { container, f } = await openBoard({
      [BOARD]: () => j(200, boardBody(step === 1 ? gone : INITIAL)),
    });
    pickFilter(R_KUZNETSOV.id);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA]));
    step = 1;
    let n = f.count(BOARD);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(n));
    await waitFor(() => expect(filterSelect().value).toBe(""));
    expect(idsIn(container, "todo")).toEqual([TB, TC]);
    expect(idsIn(container, "in_progress")).toEqual([TD]);
    step = 2; // карточка исполнителя вернулась
    n = f.count(BOARD);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(n));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC]));
    expect(filterSelect().value).toBe("");
    expect(idsIn(container, "done")).toEqual([TE]);
  });
});
