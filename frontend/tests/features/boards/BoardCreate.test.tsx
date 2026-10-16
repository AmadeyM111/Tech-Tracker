// T91 (1): создание задачи из колонки доски. Контракт разметки и ключей - в шапке ./helpers.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage, t } from "../../../src/shared/i18n";
import {
  BOARD,
  M_ME,
  MOVE,
  NEW_TITLE,
  PERM_READ,
  PROJ_CREATE,
  ONE,
  ME,
  TN,
  USER_CAPS,
  addBtn,
  createForm,
  deferred,
  detail,
  dict,
  err,
  idsIn,
  INITIAL,
  j,
  liveBoard,
  meWith,
  openBoard,
  openCreate,
  taskDetail,
  titleInput,
  BUSINESS,
} from "./helpers";

const body = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
const submit = (form: HTMLFormElement) => fireEvent.submit(form);
const type = (form: HTMLFormElement, v: string) => fireEvent.change(titleInput(form), { target: { value: v } });

async function open(over: Record<string, import("./helpers").Handler> = {}) {
  const live = liveBoard();
  const view = await openBoard({ ...live.routes, ...over });
  return { ...view, live };
}

describe("T91 create from column: visibility", () => {
  it("t91_dictionary_keys_exist_with_expected_texts", () => {
    expect(dict("boards.add_task")).toBe("Добавить задачу");
    for (const k of ["boards.create_form_label", "boards.create_title_label", "boards.create_submit", "boards.create_cancel"]) {
      expect(dict(k).length).toBeGreaterThan(0);
    }
  });

  it("t91_add_button_in_every_column_when_create_task_permitted", async () => {
    const { container } = await open();
    for (const s of ["todo", "in_progress", "review", "done"]) {
      const b = addBtn(container, s)!;
      expect(b).toBeTruthy();
      expect(b.textContent).toBe(dict("boards.add_task"));
      expect(b.getAttribute("type")).toBe("button");
      expect(createForm(container, s)).toBeNull();
    }
  });

  it("t91_no_add_buttons_without_create_task_permission", async () => {
    const { container } = await open({
      [ONE]: () => j(200, detail({ permissions: { ...PERM_READ, create_task: false } })),
    });
    expect(container.querySelector('[data-action="add-task"]')).toBeNull();
    expect(container.querySelector("[data-form]")).toBeNull();
  });

  it("t91_click_opens_accessible_inline_form_in_same_column_with_focus_on_input", async () => {
    const { container } = await open();
    const form = openCreate(container, "review");
    expect(form.getAttribute("aria-label")).toBe(dict("boards.create_form_label").replace("{status}", t("tasks.status.review")));
    const input = within(form).getByLabelText(dict("boards.create_title_label"));
    expect(input).toBe(titleInput(form));
    expect(document.activeElement).toBe(input);
    expect(within(form).getByRole("button", { name: dict("boards.create_submit") }).getAttribute("type")).toBe("submit");
    expect(within(form).getByRole("button", { name: dict("boards.create_cancel") }).getAttribute("type")).toBe("button");
    expect(addBtn(container, "review")).toBeNull();
    expect(createForm(container, "todo")).toBeNull();
  });
});

describe("T91 create from column: cancel and validation", () => {
  it("t91_escape_cancels_returns_focus_to_add_button_no_requests", async () => {
    const { container, f } = await open();
    const form = openCreate(container, "done");
    type(form, "черновик");
    fireEvent.keyDown(titleInput(form), { key: "Escape", code: "Escape" });
    await waitFor(() => expect(createForm(container, "done")).toBeNull());
    expect(document.activeElement).toBe(addBtn(container, "done"));
    expect(f.count(PROJ_CREATE)).toBe(0);
  });

  it("t91_cancel_button_closes_form_and_restores_focus", async () => {
    const { container, f } = await open();
    const form = openCreate(container, "todo");
    fireEvent.click(within(form).getByRole("button", { name: dict("boards.create_cancel") }));
    await waitFor(() => expect(createForm(container, "todo")).toBeNull());
    expect(document.activeElement).toBe(addBtn(container, "todo"));
    expect(f.count(PROJ_CREATE)).toBe(0);
  });

  it.each(["", "   "])("t91_blank_title_%j_not_sent_single_validation_alert", async (v) => {
    const { container, f } = await open();
    const form = openCreate(container, "todo");
    type(form, v);
    submit(form);
    const a = await screen.findByRole("alert");
    expect(a.textContent).toBe(errorMessage("validation_error"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(f.count(PROJ_CREATE)).toBe(0);
    expect(createForm(container, "todo")).toBeTruthy();
  });
});

describe("T91 create from column: requests", () => {
  it("t91_todo_column_posts_trimmed_title_only_and_no_move", async () => {
    const { container, f } = await open();
    const form = openCreate(container, "todo");
    type(form, `  ${NEW_TITLE}  `);
    submit(form);
    await waitFor(() => expect(idsIn(container, "todo")).toEqual([...idsIn(container, "todo").slice(0, 3), TN]));
    expect(idsIn(container, "todo")).toHaveLength(4);
    expect(await body(f.last(PROJ_CREATE))).toEqual({ title: NEW_TITLE });
    expect(f.count(MOVE(TN))).toBe(0);
    expect(createForm(container, "todo")).toBeNull();
    expect(document.activeElement).toBe(addBtn(container, "todo"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    ["in_progress", ["b4b4b4b4-0000-4000-8000-000000000004", TN]],
    ["review", [TN]],
    ["done", ["b5b5b5b5-0000-4000-8000-000000000005", TN]],
  ])("t91_column_%s_creates_then_moves_to_end_without_neighbors", async (status, expected) => {
    const { container, f } = await open();
    const reads = f.count(BOARD);
    const form = openCreate(container, status);
    type(form, NEW_TITLE);
    submit(form);
    await waitFor(() => expect(idsIn(container, status)).toEqual(expected));
    expect(await body(f.last(PROJ_CREATE))).toEqual({ title: NEW_TITLE });
    expect(f.count(MOVE(TN))).toBe(1);
    const m = await body(f.last(MOVE(TN)));
    expect(m.status).toBe(status);
    expect(m.after_task_id ?? null).toBeNull();
    expect(m.before_task_id ?? null).toBeNull();
    // карточка исчезла из «К выполнению», доска перечитана
    expect(idsIn(container, "todo")).not.toContain(TN);
    expect(f.count(BOARD)).toBeGreaterThan(reads);
    expect(createForm(container, status)).toBeNull();
    expect(document.activeElement).toBe(addBtn(container, status));
  });

  it("t91_double_submit_sends_one_create", async () => {
    const d = deferred<Response>();
    const { container, f } = await open({ [PROJ_CREATE]: () => d.promise });
    const form = openCreate(container, "review");
    type(form, NEW_TITLE);
    submit(form);
    submit(form);
    fireEvent.click(within(form).getByRole("button", { name: dict("boards.create_submit") }));
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(f.count(PROJ_CREATE)).toBe(1);
    d.resolve(j(201, taskDetail({ id: TN, title: NEW_TITLE })));
    await waitFor(() => expect(f.count(MOVE(TN))).toBe(1));
  });

  it.each([
    ["user", USER_CAPS],
    ["mixed", BUSINESS],
    ["business_admin", BUSINESS],
  ])("t91_role_%s_never_sends_assignee", async (role, caps) => {
    const { container, f } = await open({ [ME]: () => j(200, meWith(caps, role)) });
    const form = openCreate(container, "todo");
    type(form, NEW_TITLE);
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = await body(f.last(PROJ_CREATE));
    expect(b).toEqual({ title: NEW_TITLE });
    expect("assignee_id" in b).toBe(false);
    expect(form.querySelector('[role="combobox"], select, input[type="date"], textarea')).toBeNull();
    void M_ME;
  });
});

describe("T91 create from column: errors", () => {
  it.each([
    [403, "forbidden"],
    [422, "validation_error"],
    [503, "service_busy"],
  ])("t91_create_error_%i_single_alert_form_kept_no_move", async (status, code) => {
    const { container, f } = await open({ [PROJ_CREATE]: () => err(status, code) });
    const form = openCreate(container, "review");
    type(form, NEW_TITLE);
    submit(form);
    const a = await screen.findByRole("alert");
    expect(a.textContent).toBe(errorMessage(code));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(createForm(container, "review")).toBeTruthy();
    expect(titleInput(createForm(container, "review")!).value).toBe(NEW_TITLE);
    expect(f.count(MOVE(TN))).toBe(0);
    // после ошибки повторная отправка снова возможна
    submit(createForm(container, "review")!);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(2));
  });

  it("t91_move_failure_single_alert_task_stays_in_todo_board_reread", async () => {
    const { container, f } = await open({ [MOVE(TN)]: () => err(403, "forbidden") });
    const form = openCreate(container, "done");
    type(form, NEW_TITLE);
    const reads = f.count(BOARD);
    submit(form);
    const a = await screen.findByRole("alert");
    expect(a.textContent).toBe(
      dict("boards.create_move_failed").replace("{status}", "К выполнению").replace("{reason}", errorMessage("forbidden")),
    );
    await waitFor(() => expect(idsIn(container, "todo")).toContain(TN));
    expect(f.count(BOARD)).toBeGreaterThan(reads);
    expect(idsIn(container, "done")).not.toContain(TN);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });
});

describe("T91-R create form review fixes", () => {
  it.each(["escape", "cancel"])("t91r_%s_during_request_then_reopen_keeps_new_form_after_old_response", async (how) => {
    const live = liveBoard();
    const d = deferred<Response>();
    const { container, f } = await openBoard({
      ...live.routes,
      [PROJ_CREATE]: async () => {
        const r = await d.promise;
        live.cols.todo.push({ ...(INITIAL.todo[0] as object), id: TN, title: NEW_TITLE, assignee: null });
        return r;
      },
    });
    const form = openCreate(container, "todo");
    type(form, NEW_TITLE);
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    if (how === "escape") fireEvent.keyDown(titleInput(form), { key: "Escape", code: "Escape" });
    else fireEvent.click(within(form).getByRole("button", { name: dict("boards.create_cancel") }));
    await waitFor(() => expect(createForm(container, "todo")).toBeNull());
    const second = openCreate(container, "todo");
    type(second, "Другое название");
    const reads = f.count(BOARD);
    d.resolve(j(201, taskDetail({ id: TN, title: NEW_TITLE })));
    await waitFor(() => expect(f.count(BOARD)).toBeGreaterThan(reads));
    await new Promise((r) => setTimeout(r, 30));
    const now = createForm(container, "todo");
    expect(now).toBeTruthy();
    expect(titleInput(now!).value).toBe("Другое название");
  });

  it("t91r_submit_button_is_aria_busy_not_disabled_while_request_in_flight", async () => {
    const live = liveBoard();
    const d = deferred<Response>();
    const { container, f } = await openBoard({ ...live.routes, [PROJ_CREATE]: () => d.promise });
    const form = openCreate(container, "review");
    type(form, NEW_TITLE);
    const btn = within(form).getByRole("button", { name: dict("boards.create_submit") }) as HTMLButtonElement;
    expect(btn.getAttribute("aria-busy")).not.toBe("true");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    await waitFor(() => expect(btn.getAttribute("aria-busy")).toBe("true"));
    expect(btn.disabled).toBe(false);
    d.resolve(j(201, taskDetail({ id: TN, title: NEW_TITLE })));
    await waitFor(() => expect(f.count(MOVE(TN))).toBe(1));
  });

  it("t91r_move_failure_after_create_has_dedicated_message_with_reason_and_column", async () => {
    const live = liveBoard();
    const { container } = await openBoard({ ...live.routes, [MOVE(TN)]: () => err(403, "forbidden") });
    const form = openCreate(container, "done");
    type(form, NEW_TITLE);
    submit(form);
    const a = await screen.findByRole("alert");
    const expected = dict("boards.create_move_failed")
      .replace("{status}", "К выполнению")
      .replace("{reason}", errorMessage("forbidden"));
    expect(a.textContent).toBe(expected);
    expect(expected).toBe(`Задача создана в колонке «К выполнению», но не перенесена: ${errorMessage("forbidden")}`);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    await waitFor(() => expect(idsIn(container, "todo")).toContain(TN));
  });
});
