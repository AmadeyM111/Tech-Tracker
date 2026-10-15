// T84: карточка задачи.
// AC: UF-4, UF-6, FR-18..FR-22 (интерфейс), FR-29 (опрос), AC-7 (предупреждение при закрытии родителя),
//     AC-46, AC-47 (элементы по permissions), NFR-6, NFR-7.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  ALL_PERMS,
  DELETE,
  EXECUTOR_PERMS,
  ID_KUZNETSOV,
  NO_PERMS,
  PATCH,
  PID,
  SUB1,
  SUB2,
  TASK,
  USERS,
  bodyOf,
  card,
  d,
  deleteBtn,
  editForm,
  err,
  f_,
  j,
  openCard,
  page,
  setValue,
  statusSelect,
  sub,
  subForm,
  waitCount,
  where,
  expectAt,
  NO_CONTENT,
  deferred,
  renderApp,
  installFetch,
  cardRoutes,
  TID1,
  M_KUZNETSOV,
  M_OWNER,
  M_PETROV,
  M_SIDOROV,
  MEMBERS,
  ID_KUZNETSOV as KUZ,
} from "./taskpage-helpers";

afterEach(() => vi.useRealTimers());

const title = (f: HTMLFormElement) => f.querySelector<HTMLInputElement>('input[name="title"]')!;
const picker = () => screen.getByRole("combobox", { name: ru["tasks.assignee_label"] });

describe("card read view (UF-6, FR-18)", () => {
  it("uf6_card_shows_fields_project_link_and_comments_slot", async () => {
    const { container } = await openCard();
    expect(f_(container, "status")!.textContent).toBe(ru["tasks.status.in_progress"]);
    expect(f_(container, "priority")!.textContent).toBe(ru["tasks.priority.high"]);
    expect(f_(container, "assignee")!.textContent).toBe("kuznetsov");
    expect(f_(container, "description")!.textContent).toBe("Квартальный отчёт");
    const due = f_(container, "due_date")!.querySelector("time")!;
    expect(due.getAttribute("datetime")).toBe("2026-12-31");
    expect(due.textContent).toBe("31.12.2026");
    expect(f_(container, "project")!.querySelector("a")!.getAttribute("href")).toBe(`/projects/${PID}`);
    expect(container.querySelector('[data-slot="comments"]')).toBeTruthy();
  });

  it("fr18_empty_assignee_and_due_show_dictionary_placeholders", async () => {
    const { container } = await openCard(() => card({ assignee: null, due_date: null }));
    expect(f_(container, "assignee")!.textContent).toBe(ru["tasks.assignee_none"]);
    expect(f_(container, "due_date")!.textContent).toBe(ru["tasks.due_none"]);
  });

  it("nfr6_load_error_shows_single_alert_without_title_or_forms", async () => {
    installFetchError();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("not_found"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByRole("heading", { level: 1, name: "Подготовить отчёт" })).toBeNull();
    expect(document.querySelector("form")).toBeNull();
  });
});

function installFetchError() {
  installFetch({ ...cardRoutes(() => card()), [TASK]: () => err(404, "not_found") });
  renderApp(`/tasks/${TID1}`);
}

describe("elements by permissions (AC-46, AC-47, NFR-7)", () => {
  it("ac46_all_permissions_show_all_controls", async () => {
    const { container } = await openCard();
    expect(editForm(container)).toBeTruthy();
    expect(statusSelect()).toBeTruthy();
    expect(picker()).toBeTruthy();
    expect(deleteBtn(container)).toBeTruthy();
    expect(subForm(container)).toBeTruthy();
  });

  it("ac46_no_permissions_hide_every_control", async () => {
    const { container } = await openCard(() => card({ permissions: NO_PERMS }));
    expect(editForm(container)).toBeNull();
    expect(statusSelect()).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(deleteBtn(container)).toBeNull();
    expect(subForm(container)).toBeNull();
    expect(container.querySelector('button[data-action="clear-assignee"]')).toBeNull();
    // чтение остаётся
    expect(f_(container, "status")!.textContent).toBe(ru["tasks.status.in_progress"]);
  });

  it("ac47_executor_of_foreign_task_changes_status_and_adds_subtask_only", async () => {
    const { container } = await openCard(() => card({ permissions: EXECUTOR_PERMS }), {}, "user");
    expect(statusSelect()).toBeTruthy();
    expect(subForm(container)).toBeTruthy();
    expect(editForm(container)).toBeNull();
    expect(deleteBtn(container)).toBeNull();
    expect(screen.queryByRole("combobox", { name: ru["tasks.assignee_label"] })).toBeNull();
  });

  it("ac46_user_own_task_edits_fields_but_has_no_assignee_picker", async () => {
    const { container } = await openCard(
      () => card({ permissions: { ...ALL_PERMS, change_assignee: false } }),
      {},
      "user",
    );
    expect(editForm(container)).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: ru["tasks.assignee_label"] })).toBeNull();
    expect(container.querySelector('button[data-action="clear-assignee"]')).toBeNull();
  });
});

describe("edit form sends only changed fields (FR-18, AC-46)", () => {
  it("fr18_form_is_prefilled_and_labelled", async () => {
    const { container } = await openCard();
    const form = editForm(container)!;
    expect(title(form).value).toBe("Подготовить отчёт");
    expect(form.querySelector<HTMLTextAreaElement>('textarea[name="description"]')!.value).toBe("Квартальный отчёт");
    expect(form.querySelector<HTMLInputElement>('input[name="due_date"]')!.value).toBe("2026-12-31");
    expect(form.querySelector<HTMLSelectElement>('select[name="priority"]')!.value).toBe("high");
    for (const el of Array.from(form.querySelectorAll("input,select,textarea"))) {
      expect((el as HTMLInputElement).labels?.length, el.outerHTML).toBeTruthy();
    }
  });

  it("ac46_patch_contains_only_changed_title_trimmed", async () => {
    const { container, f } = await openCard(() => card(), {
      [PATCH]: () => j(200, card({ title: "Новое имя" })),
    });
    const form = editForm(container)!;
    setValue(title(form), "  Новое имя  ");
    fireEvent.submit(form);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ title: "Новое имя" });
    await screen.findByRole("heading", { level: 1, name: "Новое имя" });
  });

  it("ac46_patch_changes_several_fields_without_assignee_or_status_keys", async () => {
    const { container, f } = await openCard(() => card(), { [PATCH]: () => j(200, card()) });
    const form = editForm(container)!;
    setValue(form.querySelector('textarea[name="description"]'), "Другое");
    setValue(form.querySelector('input[name="due_date"]'), "2027-01-15");
    setValue(form.querySelector('select[name="priority"]'), "base");
    fireEvent.submit(form);
    await waitCount(f, PATCH, 1);
    const b = await bodyOf(f.last(PATCH));
    expect(b).toEqual({ description: "Другое", due_date: "2027-01-15", priority: "base" });
    expect("assignee_id" in b).toBe(false);
    expect("status" in b).toBe(false);
  });

  it("fr18_cleared_due_date_is_sent_as_null", async () => {
    const { container, f } = await openCard(() => card(), { [PATCH]: () => j(200, card({ due_date: null })) });
    const form = editForm(container)!;
    setValue(form.querySelector('input[name="due_date"]'), "");
    fireEvent.submit(form);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ due_date: null });
  });

  it("fr18_no_changes_means_no_request", async () => {
    const { container, f } = await openCard();
    fireEvent.submit(editForm(container)!);
    await new Promise((r) => setTimeout(r, 30));
    expect(f.count(PATCH)).toBe(0);
  });

  it("fr18_empty_title_blocks_request_and_shows_validation_alert", async () => {
    const { container, f } = await openCard();
    const form = editForm(container)!;
    setValue(title(form), "   ");
    fireEvent.submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(f.count(PATCH)).toBe(0);
  });

  it("nfr6_patch_403_shows_alert_and_keeps_input", async () => {
    const { container } = await openCard(() => card(), { [PATCH]: () => err(403, "forbidden") });
    const form = editForm(container)!;
    setValue(title(form), "Черновик");
    fireEvent.submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(title(editForm(container)!).value).toBe("Черновик");
  });

  it("nfr6_double_submit_sends_one_patch", async () => {
    const gate = deferred<Response>();
    const { container, f } = await openCard(() => card(), { [PATCH]: () => gate.promise });
    const form = editForm(container)!;
    setValue(title(form), "Один раз");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitCount(f, PATCH, 1);
    gate.resolve(j(200, card({ title: "Один раз" })));
    await screen.findByRole("heading", { level: 1, name: "Один раз" });
    expect(f.count(PATCH)).toBe(1);
  });
});

describe("status change and close warning (FR-22, AC-7)", () => {
  it("ac46_status_change_sends_only_status", async () => {
    const { f } = await openCard(() => card(), { [PATCH]: () => j(200, card({ status: "review" })) });
    setValue(statusSelect(), "review");
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ status: "review" });
    await waitFor(() => expect(statusSelect()!.value).toBe("review"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("ac7_closing_parent_with_open_subtasks_warns_then_cancel_sends_nothing", async () => {
    const subs = [sub(SUB1, "Первая", "done"), sub(SUB2, "Вторая", "review")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 50 }), {
      [PATCH]: () => j(200, card({ status: "done" })),
    });
    setValue(statusSelect(), "done");
    const dlg = await screen.findByRole("alertdialog");
    expect(dlg.textContent).toContain(d("tasks.close_open_subtasks"));
    expect(f.count(PATCH)).toBe(0);
    fireEvent.click(dlg.querySelector('button[data-action="cancel"]')!);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(PATCH)).toBe(0);
    expect(statusSelect()!.value).toBe("in_progress");
  });

  it("ac7_closing_parent_with_open_subtasks_confirm_saves_status", async () => {
    const subs = [sub(SUB1, "Первая", "done"), sub(SUB2, "Вторая", "todo")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 50 }), {
      [PATCH]: () => j(200, card({ status: "done", subtasks: subs, progress: 50 })),
    });
    setValue(statusSelect(), "done");
    const dlg = await screen.findByRole("alertdialog");
    fireEvent.click(dlg.querySelector('button[data-action="confirm"]')!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ status: "done" });
  });

  it("ac7_all_subtasks_done_or_none_closes_without_warning", async () => {
    const subs = [sub(SUB1, "Первая", "done"), sub(SUB2, "Вторая", "done")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 100 }), {
      [PATCH]: () => j(200, card({ status: "done", subtasks: subs, progress: 100 })),
    });
    setValue(statusSelect(), "done");
    await waitCount(f, PATCH, 1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("ac7_opening_status_other_than_done_never_warns", async () => {
    const subs = [sub(SUB1, "Первая", "todo")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 0 }), {
      [PATCH]: () => j(200, card({ status: "todo", subtasks: subs, progress: 0 })),
    });
    setValue(statusSelect(), "todo");
    await waitCount(f, PATCH, 1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("assignee: UNSET vs null (FR-19a, AC-46)", () => {
  it("ac46_ba_picks_member_assignee_id_only", async () => {
    const { f } = await openCard(() => card(), {
      [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])),
      [PATCH]: () => j(200, card()),
    });
    fireEvent.change(picker(), { target: { value: "kuz" } });
    const list = await screen.findByRole("listbox", { name: ru["tasks.assignee_label"] });
    fireEvent.click((await within(list).findAllByRole("option"))[0]!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ assignee_id: ID_KUZNETSOV });
  });

  it("ac46_clear_assignee_sends_explicit_null", async () => {
    const { container, f } = await openCard(() => card(), { [PATCH]: () => j(200, card({ assignee: null })) });
    fireEvent.click(container.querySelector('button[data-action="clear-assignee"]')!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ assignee_id: null });
    await waitFor(() => expect(f_(container, "assignee")!.textContent).toBe(ru["tasks.assignee_none"]));
  });

  it("ac46_clear_button_absent_when_no_assignee", async () => {
    const { container } = await openCard(() => card({ assignee: null }));
    expect(container.querySelector('button[data-action="clear-assignee"]')).toBeNull();
  });

  it("fr20_assignee_candidates_are_project_members_with_page_size_100", async () => {
    const { f } = await openCard();
    await waitFor(() => expect(f.calls.some((c) => c.url.includes(`/projects/${PID}/members`))).toBe(true));
    const m = f.calls.find((c) => c.url.includes(`/projects/${PID}/members`))!;
    expect(new URL(m.url).searchParams.get("page_size")).toBe("100");
  });
});

describe("polling (FR-29, NFR-6)", () => {
  it("fr29_poll_does_not_overwrite_unsaved_input_but_refreshes_view", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    const { container, f } = await openCard(() =>
      n++ === 0 ? card() : card({ title: "Серверное имя", description: "Серверное описание" }),
    );
    const form = editForm(container)!;
    setValue(title(form), "Мой черновик");
    expect(f.last(TASK).headers.get("X-GT-Background")).toBeNull();
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.last(TASK).headers.get("X-GT-Background")).toBe("1"));
    await screen.findByRole("heading", { level: 1, name: "Серверное имя" });
    expect(title(editForm(container)!).value).toBe("Мой черновик");
    expect(f_(container, "description")!.textContent).toBe("Серверное описание");
  });

  it("fr29_save_after_poll_still_sends_only_edited_field", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    const { container, f } = await openCard(
      () => (n++ === 0 ? card() : card({ description: "Чужая правка" })),
      { [PATCH]: () => j(200, card({ title: "Мой" })) },
    );
    const form = editForm(container)!;
    setValue(title(form), "Мой");
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(TASK)).toBeGreaterThan(1));
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ title: "Мой" });
  });
});

describe("delete with confirmation (NFR-7)", () => {
  it("nfr7_delete_requires_confirmation_then_goes_to_project", async () => {
    const { container, f } = await openCard(() => card(), { [DELETE]: () => NO_CONTENT() });
    fireEvent.click(deleteBtn(container)!);
    const dlg = await screen.findByRole("alertdialog");
    expect(f.count(DELETE)).toBe(0);
    fireEvent.click(dlg.querySelector('button[data-action="confirm"]')!);
    await waitCount(f, DELETE, 1);
    await expectAt(`/projects/${PID}`);
  });

  it("nfr7_cancel_keeps_task_and_sends_no_request", async () => {
    const { container, f } = await openCard();
    fireEvent.click(deleteBtn(container)!);
    const dlg = await screen.findByRole("alertdialog");
    fireEvent.click(dlg.querySelector('button[data-action="cancel"]')!);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(DELETE)).toBe(0);
    expect(where()).toBe(`/tasks/${TID1}`);
  });

  it("nfr6_delete_403_shows_alert_and_stays", async () => {
    const { container } = await openCard(() => card(), { [DELETE]: () => err(403, "forbidden") });
    fireEvent.click(deleteBtn(container)!);
    const dlg = await screen.findByRole("alertdialog");
    fireEvent.click(dlg.querySelector('button[data-action="confirm"]')!);
    await waitFor(() => expect(screen.getAllByRole("alert").some((a) => a.textContent === errorMessage("forbidden"))).toBe(true));
    expect(where()).toBe(`/tasks/${TID1}`);
  });
});

const USER_REC = (id: string, login: string) => ({ id, login, role: "user" });

describe("T84 review gaps", () => {
  it("a11y_status_select_keeps_focus_and_is_not_disabled_while_pending", async () => {
    const gate = deferred<Response>();
    const { f } = await openCard(() => card(), { [PATCH]: () => gate.promise });
    const sel = statusSelect()!;
    sel.focus();
    setValue(sel, "review");
    await waitCount(f, PATCH, 1);
    expect(statusSelect()!.disabled).toBe(false);
    gate.resolve(j(200, card({ status: "review" })));
    await waitFor(() => expect(statusSelect()!.value).toBe("review"));
    expect(document.activeElement).toBe(statusSelect());
  });

  it("a11y_clear_assignee_moves_focus_to_assignee_picker", async () => {
    const { container, f } = await openCard(() => card(), {
      [PATCH]: () => j(200, card({ assignee: null })),
    });
    const btn = container.querySelector<HTMLButtonElement>('button[data-action="clear-assignee"]')!;
    btn.focus();
    fireEvent.click(btn);
    await waitCount(f, PATCH, 1);
    await waitFor(() => expect(f_(container, "assignee")!.textContent).toBe(ru["tasks.assignee_none"]));
    await waitFor(() => expect(document.activeElement).toBe(picker()));
  });

  it("fr29_poll_started_before_patch_does_not_roll_back_new_status", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const gate = deferred<Response>();
    let n = 0;
    const { container, f } = await openCard(
      () => card(),
      {
        [TASK]: () => {
          n += 1;
          if (n === 1) return j(200, card());
          if (n === 2) return gate.promise;
          return j(200, card({ status: "review" }));
        },
        [PATCH]: () => j(200, card({ status: "review" })),
      },
    );
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(TASK)).toBe(2));
    setValue(statusSelect(), "review");
    await waitCount(f, PATCH, 1);
    await waitFor(() => expect(f_(container, "status")!.textContent).toBe(ru["tasks.status.review"]));
    gate.resolve(j(200, card({ status: "in_progress" })));
    await new Promise((r) => setTimeout(r, 50));
    await vi.advanceTimersByTimeAsync(0);
    expect(f_(container, "status")!.textContent).toBe(ru["tasks.status.review"]);
    expect(statusSelect()!.value).toBe("review");
  });

  it("m06_status_change_keeps_unsaved_title_input", async () => {
    const { container, f } = await openCard(() => card(), {
      [PATCH]: () => j(200, card({ status: "review" })),
    });
    setValue(title(editForm(container)!), "Мой черновик");
    setValue(statusSelect(), "review");
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ status: "review" });
    await waitFor(() => expect(f_(container, "status")!.textContent).toBe(ru["tasks.status.review"]));
    expect(title(editForm(container)!).value).toBe("Мой черновик");
  });

  it("m08_no_change_assignee_permission_means_no_members_request", async () => {
    const { f } = await openCard(() => card({ permissions: { ...ALL_PERMS, change_assignee: false } }));
    await new Promise((r) => setTimeout(r, 50));
    expect(f.calls.some((c) => c.url.includes("/members"))).toBe(false);
  });

  it("m09_blocked_and_roleless_members_are_not_offered_as_assignees", async () => {
    const PET = M_PETROV.user.id as string;
    const SID = M_SIDOROV.user.id as string;
    await openCard(() => card(), {
      [MEMBERS]: () => j(200, page([M_OWNER, M_KUZNETSOV, M_PETROV, M_SIDOROV])),
      [USERS]: () =>
        j(200, page([USER_REC(PET, "petrov"), USER_REC(SID, "sidorov"), USER_REC(KUZ, "kuznetsov")])),
    });
    fireEvent.change(picker(), { target: { value: "ov" } });
    const list = await screen.findByRole("listbox", { name: ru["tasks.assignee_label"] });
    await waitFor(() => expect(within(list).queryAllByRole("option").length).toBeGreaterThan(0));
    const texts = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
    expect(texts.some((x) => x.includes("kuznetsov"))).toBe(true);
    expect(texts.some((x) => x.includes("petrov"))).toBe(false);
    expect(texts.some((x) => x.includes("sidorov"))).toBe(false);
  });

  it("m01_patch_omits_title_when_only_whitespace_differs", async () => {
    const { container, f } = await openCard(() => card(), { [PATCH]: () => j(200, card({ description: "Другое" })) });
    const form = editForm(container)!;
    setValue(title(form), "  Подготовить отчёт  ");
    setValue(form.querySelector('textarea[name="description"]'), "Другое");
    fireEvent.submit(form);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ description: "Другое" });
  });

  it("m01_patch_omits_title_when_edited_back_to_original", async () => {
    const { container, f } = await openCard(() => card(), { [PATCH]: () => j(200, card({ priority: "base" })) });
    const form = editForm(container)!;
    setValue(title(form), "Черновик");
    setValue(title(form), "Подготовить отчёт");
    setValue(form.querySelector('select[name="priority"]'), "base");
    fireEvent.submit(form);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ priority: "base" });
  });

  it("m12_load_422_is_shown_as_not_found_single_alert_without_forms", async () => {
    installFetch({ ...cardRoutes(() => card()), [TASK]: () => err(422, "validation_error") });
    renderApp(`/tasks/${TID1}`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("not_found"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(document.querySelector("form")).toBeNull();
    expect(screen.queryByRole("heading", { level: 1, name: "Подготовить отчёт" })).toBeNull();
  });
});
