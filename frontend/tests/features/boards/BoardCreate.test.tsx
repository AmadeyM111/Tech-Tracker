// 004 (R5-T06, R5-T07): на Доске нет создания задач. Создание - диалог бокового меню и вкладка «Задачи».
// AC-1, AC-2, AC-7 (R5-T06); AC-8 (R5-T07). Фикстуры BA/U/P1 - spec 004, раздел 5.
//
// Замена удалённых тестов T91 (plan §6.2):
//   t91_add_button_*, t91_no_add_buttons_*, t91_click_opens_* -> 004_ac1_*
//   t91_escape_*, t91_cancel_button_* -> CreateTaskDialog.test.tsx / app/create-task-button.test.tsx 004_ac32_*
//   t91_blank_title_* -> CreateTaskDialogSubmit.test.tsx 004_ac23_*
//   t91_todo_column_posts_*, t91_role_%s_never_sends_assignee -> 004_ac25_*
//   t91_column_%s_creates_then_moves_*, t91_move_failure_*, t91r_move_failure_after_create_* -> без замены (spec, раздел 9);
//     отсутствие запросов создания с Доски проверяет 004_ac2_*
//   t91_double_submit_*, t91r_submit_button_is_aria_busy_* -> 004_ac30_*
//   t91_create_error_%i_* -> 004_ac28_*
//   t91r_%s_during_request_then_reopen_* -> 004_ac31_*, 004_ac35_*
//   t91_dictionary_keys_exist_with_expected_texts -> 004_ac8_*
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { createForm, openTasksTab, taskItem, taskRow } from "../tasks/helpers";
import {
  BOARD,
  BUSINESS,
  CA,
  CB,
  CC,
  INITIAL,
  ME,
  MOVE,
  NO_CONTENT,
  ONE,
  PERM_READ,
  PROJ_CREATE,
  PROJ_TASKS_GET,
  TA,
  TB,
  TC,
  TD,
  TN,
  USER_CAPS,
  boardBody,
  card,
  cardEl,
  column,
  detail,
  err,
  idsIn,
  installLayout,
  j,
  keyboardDrag,
  meWith,
  openBoard,
  page,
  pickFilter,
  pointerDrag,
  taskDetail,
  R_KUZNETSOV,
  type Handler,
} from "./helpers";

afterEach(() => {
  vi.useRealTimers();
});

const STATUS_LIST = ["todo", "in_progress", "review", "done"];
const ADD_TASK_TEXT = "Добавить задачу";

/** Любые POST создания задачи в любом проекте: /api/v1/projects/{id}/tasks. */
const createPosts = (f: { calls: Request[] }) =>
  f.calls.filter((r) => r.method === "POST" && /^\/api\/v1\/projects\/[^/]+\/tasks$/.test(new URL(r.url).pathname));

describe("004 AC-1: на Доске нет создания", () => {
  it.each([
    ["BA с create_task", "business_admin", BUSINESS, PERM_READ],
    ["U с create_task", "user", USER_CAPS, PERM_READ],
    ["BA без create_task", "business_admin", BUSINESS, { ...PERM_READ, create_task: false }],
  ])("004_ac1_%s_no_button_form_input_or_add_text_on_board", async (_n, role, caps, perms) => {
    const { container } = await openBoard({
      [ME]: () => j(200, meWith(caps, role)),
      [ONE]: () => j(200, detail({ permissions: perms })),
    });
    for (const s of STATUS_LIST) {
      const col = column(container, s)!;
      expect(col).toBeTruthy();
      expect(col.querySelector("button")).toBeNull();
      expect(col.querySelector("form")).toBeNull();
      expect(col.querySelector("input, textarea")).toBeNull();
      expect(col.textContent).not.toContain(ADD_TASK_TEXT);
      expect(col.querySelector("h3")).toBeTruthy();
      expect(col.querySelector('[data-role="column-cards"]')).toBeTruthy();
    }
    // доска действительно показана (проверка не вырождена)
    expect(idsIn(container, "todo")).toEqual([TA, TB, TC]);
    const panel = container.querySelector('[role="tabpanel"]')!;
    expect(panel.querySelector('[data-role="board"]')).toBeTruthy();
    expect(panel.querySelector("form")).toBeNull();
    expect(panel.querySelector('input[name="title"]')).toBeNull();
    expect(panel.querySelector('[data-action="add-task"], [data-form]')).toBeNull();
    expect(panel.textContent).not.toContain(ADD_TASK_TEXT);
    expect(screen.queryByRole("button", { name: ADD_TASK_TEXT })).toBeNull();
    expect(screen.queryByText(ADD_TASK_TEXT)).toBeNull();
  });
});

describe("004 AC-2: сценарии Доски не создают задач", () => {
  it("004_ac2_pointer_move_sends_move_only", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TA)]: () => NO_CONTENT() });
    await pointerDrag(cardEl(container, TA)!, { x: 140, y: 65 }, { x: 140, y: 155 });
    await waitFor(() => expect(f.count(MOVE(TA))).toBe(1));
    expect(createPosts(f)).toHaveLength(0);
  });

  it("004_ac2_keyboard_move_sends_move_only", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TD)]: () => NO_CONTENT() });
    await keyboardDrag(cardEl(container, TD)!, ["ArrowRight"]);
    await waitFor(() => expect(f.count(MOVE(TD))).toBe(1));
    expect(createPosts(f)).toHaveLength(0);
  });

  it("004_ac2_filter_change_sends_no_create", async () => {
    const { f, container } = await openBoard();
    pickFilter("none");
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TB, TC]));
    pickFilter(R_KUZNETSOV.id);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA]));
    expect(createPosts(f)).toHaveLength(0);
  });

  it("004_ac2_poll_tick_sends_no_create", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let step = 0;
    const { f, container } = await openBoard({
      [BOARD]: () =>
        j(200, boardBody(step === 0 ? INITIAL : { ...INITIAL, todo: [...INITIAL.todo, card(TN, "Нов", "todo", 1000)] })),
    });
    step = 1;
    const n = f.count(BOARD);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(n));
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC, TN]));
    expect(createPosts(f)).toHaveLength(0);
  });

  it("004_ac2_move_error_single_alert_and_no_create", async () => {
    installLayout();
    const { f, container } = await openBoard({ [MOVE(TB)]: () => err(403, "forbidden") });
    await keyboardDrag(cardEl(container, TB)!, ["ArrowDown"]);
    const a = await screen.findByRole("alert");
    expect(a.textContent).toBe(errorMessage("forbidden"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([TA, TB, TC]));
    expect(createPosts(f)).toHaveLength(0);
    expect(f.count(PROJ_CREATE)).toBe(0);
  });
});

describe("004 AC-7: создание через вкладку «Задачи», на Доске кнопки нет", () => {
  it("004_ac7_user_creates_on_tasks_tab_card_appears_on_board_without_add_button", async () => {
    const created: unknown[] = [];
    const todo = [CA, CB, CC];
    const routes: Record<string, Handler> = {
      [ME]: () => j(200, meWith(USER_CAPS, "user")),
      [PROJ_TASKS_GET]: () => j(200, page(created)),
      [BOARD]: () => j(200, boardBody({ ...INITIAL, todo: [...todo, ...(created.length ? [card(TN, "Проверка", "todo", 1000)] : [])] })),
      [PROJ_CREATE]: async (r) => {
        const b = (await r.clone().json()) as { title: string };
        created.push(taskItem(TN, b.title));
        return j(201, taskDetail({ id: TN, title: b.title, status: "todo" }));
      },
    };
    const { f, container } = await openBoard(routes);
    await openTasksTab();
    await waitFor(() => expect(createForm(container)).toBeTruthy());
    const form = createForm(container)!;
    fireEvent.change(form.querySelector<HTMLInputElement>('input[name="title"]')!, { target: { value: "Проверка" } });
    fireEvent.submit(form);
    await waitFor(() => expect(taskRow(container, TN)).toBeTruthy());
    expect(f.count(PROJ_CREATE)).toBe(1);
    expect(createPosts(f)).toHaveLength(1);
    expect(new URL(createPosts(f)[0]!.url).pathname).toMatch(/\/projects\/[^/]+\/tasks$/);
    expect(((await createPosts(f)[0]!.clone().json()) as { title: string }).title).toBe("Проверка");

    const boardTab = document.querySelector<HTMLElement>('[role="tab"][data-tab="board"]')!;
    fireEvent.click(boardTab);
    await waitFor(() => expect(boardTab.getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(cardEl(container, TN)).toBeTruthy());
    expect(column(container, "todo")!.contains(cardEl(container, TN))).toBe(true);
    expect(cardEl(container, TN)!.textContent).toContain("Проверка");
    expect(column(container, "todo")!.querySelector("button")).toBeNull();
    expect(container.textContent).not.toContain(ADD_TASK_TEXT);
    expect(screen.queryByRole("button", { name: ADD_TASK_TEXT })).toBeNull();
    expect(createPosts(f)).toHaveLength(1);
  });
});

describe("004 AC-8: словарь и стили создания из колонки удалены", () => {
  const REMOVED_KEYS = [
    "boards.add_task",
    "boards.create_form_label",
    "boards.create_title_label",
    "boards.create_submit",
    "boards.create_cancel",
    "boards.create_move_failed",
  ];

  it("004_ac8_removed_keys_are_absent_from_ru", () => {
    const keys = Object.keys(ru);
    for (const k of REMOVED_KEYS) expect(keys, k).not.toContain(k);
    expect(keys.filter((k) => /^boards\.(add_task|create_)/.test(k))).toEqual([]);
  });

  it("004_ac8_no_value_add_task_or_created_but_not_moved", () => {
    const values = Object.values(ru as Record<string, string>);
    expect(values.filter((v) => v.includes(ADD_TASK_TEXT))).toEqual([]);
    expect(values.filter((v) => /Задача создана в колонке .*но не перенесена/.test(v))).toEqual([]);
  });

  it("004_ac8_ui_css_has_no_create_from_column_rules", () => {
    const css = readFileSync(resolve(process.cwd(), "src/shared/ui/ui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const cls of ["ui-add-task", "ui-create-form", "ui-create-form-actions"]) {
      expect(new RegExp(`\\.${cls}(?![\\w-])`).test(css), cls).toBe(false);
    }
  });

  it("004_ac8_remaining_board_keys_are_kept", () => {
    // уборка не задела нужное: фильтр и пустая колонка остаются
    for (const k of ["boards.filter_label", "boards.filter_all", "boards.filter_none", "boards.empty_column"]) {
      expect(typeof (ru as Record<string, unknown>)[k], k).toBe("string");
    }
  });
});
