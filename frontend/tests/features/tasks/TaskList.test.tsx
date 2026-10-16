// T83: списки задач - вкладка проекта и /my-tasks.
// AC: UF-3, UF-6 (список и фильтр), FR-26, FR-27 (фильтры исполнитель/статус, SC-10),
//     FR-29 (опрос), AC-6 (личный список), NFR-5 (срок без пересчёта пояса), NFR-6, NFR-7.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  ID_KUZNETSOV,
  MEMBERS,
  MY_TASKS,
  PID,
  PROJ_TASKS,
  T1,
  T3,
  TID1,
  TID2,
  TID3,
  err,
  f_,
  installFetch,
  j,
  meWith,
  ME,
  openTasksTab,
  page,
  renderApp,
  taskItem,
  taskRoutes,
  taskRow,
  USER_CAPS,
} from "./helpers";

import {
  ALL_PERMS,
  NO_PERMS,
  card,
  assigneePicker,
  deleteBtn,
  editForm,
  openCard,
  titleInput,
  R_IVANOV,
} from "./taskpage-helpers";

const DICT = Object.values(ru) as string[];

afterEach(() => {
  vi.useRealTimers();
});

async function openProject(role: "business_admin" | "user" = "business_admin", over = {}, opts = {}) {
  const f = installFetch(taskRoutes(role, over, opts));
  const view = renderApp(`/projects/${PID}`);
  await screen.findByRole("heading", { level: 1, name: "Альфа" });
  await openTasksTab();
  return { f, ...view };
}

describe("002_fr21_task_controls_follow_server_permissions (FR-21, AC-27 auto part)", () => {
  // БА (me), не автор и не владелец: видимость задаёт только permissions.* сервера.
  it("002_fr21_ba_with_edit_change_assignee_delete_sees_full_edit_assignee_and_delete", async () => {
    const { container } = await openCard(() => card({ author: R_IVANOV, permissions: ALL_PERMS }));
    expect(editForm(container)).toBeTruthy();
    expect(titleInput()).toBeTruthy();
    expect(assigneePicker()).toBeTruthy();
    expect(deleteBtn(container)).toBeTruthy();
  });

  it("002_fr21_ba_without_task_permissions_sees_no_edit_assignee_or_delete", async () => {
    const { container } = await openCard(() => card({ author: R_IVANOV, permissions: NO_PERMS }));
    expect(editForm(container)).toBeNull();
    expect(titleInput()).toBeNull();
    expect(screen.queryByRole("combobox", { name: ru["tasks.col_assignee"] })).toBeNull();
    expect(deleteBtn(container)).toBeNull();
  });
});

describe("project tasks tab", () => {
  it("uf3_lists_rows_with_title_link_status_priority_assignee", async () => {
    const { container } = await openProject();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    const r1 = taskRow(container, TID1)!;
    const link = f_(r1, "title")!.querySelector("a")!;
    expect(link.getAttribute("href")).toBe(`/tasks/${TID1}`);
    expect(link.textContent).toBe("Подготовить отчёт");
    expect(f_(r1, "assignee")!.textContent).toBe("kuznetsov");
    const r2 = taskRow(container, TID2)!;
    expect(f_(r1, "status")!.textContent).not.toBe(f_(r2, "status")!.textContent);
    expect(DICT).toContain(f_(r1, "status")!.textContent);
    expect(DICT).toContain(f_(r1, "priority")!.textContent);
    expect(f_(r1, "priority")!.textContent).not.toBe(f_(r2, "priority")!.textContent);
    // без исполнителя - текст из словаря, не пустая ячейка и не "null"
    expect(DICT).toContain(f_(r2, "assignee")!.textContent);
    // подзадачи включены в список как обычные строки
    expect(taskRow(container, TID3)).toBeTruthy();
  });

  it("uf3_first_request_has_no_filters_and_page_1", async () => {
    const { f, container } = await openProject();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    const q = f.query(f.last(PROJ_TASKS));
    expect(q.get("page")).toBe("1");
    expect(q.has("assignee_id")).toBe(false);
    expect(q.has("status")).toBe(false);
  });

  it("nfr5_due_date_shown_without_timezone_shift", async () => {
    const { container } = await openProject();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    const t1 = f_(taskRow(container, TID1)!, "due_date")!.querySelector("time")!;
    expect(t1.getAttribute("datetime")).toBe("2026-12-31");
    expect(t1.textContent).toBe("31.12.2026");
    const t3 = f_(taskRow(container, TID3)!, "due_date")!.querySelector("time")!;
    expect(t3.getAttribute("datetime")).toBe("2026-01-01");
    expect(t3.textContent).toBe("01.01.2026");
    const none = f_(taskRow(container, TID2)!, "due_date")!;
    expect(none.querySelector("time")).toBeNull();
    expect(DICT).toContain(none.textContent);
  });

  it("fr27_assignee_filter_options_are_members_and_sends_assignee_id", async () => {
    const { f, container } = await openProject();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    const sel = container.querySelector<HTMLSelectElement>('select[name="assignee_id"]')!;
    const values = Array.from(sel.options).map((o) => o.value);
    expect(values[0]).toBe("");
    expect(values).toContain(ID_KUZNETSOV);
    expect(Array.from(sel.options).find((o) => o.value === ID_KUZNETSOV)!.textContent).toBe("kuznetsov");
    expect(f.query(f.last(MEMBERS)).get("page_size")).toBe("100");
    fireEvent.change(sel, { target: { value: ID_KUZNETSOV } });
    await waitFor(() => expect(f.query(f.last(PROJ_TASKS)).get("assignee_id")).toBe(ID_KUZNETSOV));
    expect(f.query(f.last(PROJ_TASKS)).get("page")).toBe("1");
  });

  it("fr27_assignee_filter_change_from_page_2_resets_page_to_1", async () => {
    const { f, container } = await openProject("business_admin", {
      [PROJ_TASKS]: (r: Request) =>
        j(200, page([T1], Number(new URL(r.url).searchParams.get("page")), true)),
    });
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    fireEvent.click(container.querySelector('button[data-action="next-page"]')!);
    await waitFor(() => expect(f.query(f.last(PROJ_TASKS)).get("page")).toBe("2"));
    fireEvent.change(container.querySelector('select[name="assignee_id"]')!, {
      target: { value: ID_KUZNETSOV },
    });
    await waitFor(() => {
      const q = f.query(f.last(PROJ_TASKS));
      expect(q.get("assignee_id")).toBe(ID_KUZNETSOV);
      expect(q.get("page")).toBe("1");
    });
  });

  it("fr27_status_filter_sends_status_and_combines_with_assignee", async () => {
    const { f, container } = await openProject();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    const st = container.querySelector<HTMLSelectElement>('select[name="status"]')!;
    expect(Array.from(st.options).map((o) => o.value)).toEqual(["", "todo", "in_progress", "review", "done"]);
    for (const o of Array.from(st.options)) expect(DICT).toContain(o.textContent);
    fireEvent.change(st, { target: { value: "done" } });
    await waitFor(() => expect(f.query(f.last(PROJ_TASKS)).get("status")).toBe("done"));
    fireEvent.change(container.querySelector('select[name="assignee_id"]')!, {
      target: { value: ID_KUZNETSOV },
    });
    await waitFor(() => {
      const q = f.query(f.last(PROJ_TASKS));
      expect(q.get("status")).toBe("done");
      expect(q.get("assignee_id")).toBe(ID_KUZNETSOV);
    });
    // сброс фильтра убирает параметр
    fireEvent.change(st, { target: { value: "" } });
    await waitFor(() => expect(f.query(f.last(PROJ_TASKS)).has("status")).toBe(false));
  });

  it("fr27_filter_change_resets_page_to_1", async () => {
    const { f, container } = await openProject("business_admin", {
      [PROJ_TASKS]: (r: Request) =>
        j(200, page([T1], Number(new URL(r.url).searchParams.get("page")), true)),
    });
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    fireEvent.click(container.querySelector('button[data-action="next-page"]')!);
    await waitFor(() => expect(f.query(f.last(PROJ_TASKS)).get("page")).toBe("2"));
    fireEvent.change(container.querySelector('select[name="status"]')!, { target: { value: "todo" } });
    await waitFor(() => expect(f.query(f.last(PROJ_TASKS)).get("page")).toBe("1"));
  });

  it("uf3_pagination_prev_disabled_on_first_next_disabled_without_has_next", async () => {
    const { container } = await openProject();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    expect(container.querySelector<HTMLButtonElement>('button[data-action="prev-page"]')!.disabled).toBe(true);
    expect(container.querySelector<HTMLButtonElement>('button[data-action="next-page"]')!.disabled).toBe(true);
  });

  it("uf3_empty_list_shows_dictionary_text", async () => {
    const { container } = await openProject("business_admin", {}, { items: [] });
    await waitFor(() => expect(container.querySelector('[data-role="empty"]')).toBeTruthy());
    expect(DICT).toContain(container.querySelector('[data-role="empty"]')!.textContent);
    expect(container.querySelector("tr[data-task-id]")).toBeNull();
  });

  it("nfr6_load_error_shows_single_alert_with_dictionary_message", async () => {
    await openProject("business_admin", { [PROJ_TASKS]: () => j(500, { detail: "x", code: "internal_error" }) });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("internal_error"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("fr29_polling_refetches_with_background_header_and_updates_rows", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    const { f, container } = await openProject("business_admin", {
      [PROJ_TASKS]: () => j(200, page(n++ === 0 ? [T1] : [T1, taskItem("b4b4b4b4-0000-4000-8000-000000000004", "Свежая")])),
    });
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    expect(f.last(PROJ_TASKS).headers.get("X-GT-Background")).toBeNull();
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(container.textContent).toContain("Свежая"));
    expect(f.last(PROJ_TASKS).headers.get("X-GT-Background")).toBe("1");
  });
});

describe("my tasks page", () => {
  const open = async (items: unknown[] = [T1, T3], over = {}) => {
    const f = installFetch({
      [ME]: () => j(200, meWith(USER_CAPS, "user")),
      [MY_TASKS]: () => j(200, page(items)),
      ...over,
    });
    const view = renderApp("/my-tasks");
    await screen.findByRole("heading", { level: 1, name: ru["tasks.my_title"] });
    return { f, ...view };
  };

  it("ac6_lists_personal_tasks_with_project_link_and_due_date", async () => {
    const { container } = await open();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    const proj = f_(taskRow(container, TID1)!, "project")!.querySelector("a")!;
    expect(proj.getAttribute("href")).toBe(`/projects/${PID}`);
    expect(proj.textContent).toBe("Альфа");
    expect(f_(taskRow(container, TID1)!, "title")!.querySelector("a")!.getAttribute("href")).toBe(`/tasks/${TID1}`);
    expect(f_(taskRow(container, TID3)!, "due_date")!.textContent).toBe("01.01.2026");
    expect(taskRow(container, TID3)).toBeTruthy();
  });

  it("ac6_has_no_filters_and_no_create_form", async () => {
    const { container } = await open();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    expect(container.querySelector('select[name="status"]')).toBeNull();
    expect(container.querySelector('select[name="assignee_id"]')).toBeNull();
    expect(container.querySelector('form[data-form="create-task"]')).toBeNull();
  });

  it("ac6_pagination_requests_next_page", async () => {
    const { f, container } = await open([T1], {
      [MY_TASKS]: (r: Request) => j(200, page([T1], Number(new URL(r.url).searchParams.get("page")), true)),
    });
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    expect(f.query(f.last(MY_TASKS)).get("page")).toBe("1");
    fireEvent.click(container.querySelector('button[data-action="next-page"]')!);
    await waitFor(() => expect(f.query(f.last(MY_TASKS)).get("page")).toBe("2"));
  });

  it("ac6_empty_list_shows_dictionary_text", async () => {
    const { container } = await open([]);
    await waitFor(() => expect(container.querySelector('[data-role="empty"]')).toBeTruthy());
    expect(DICT).toContain(container.querySelector('[data-role="empty"]')!.textContent);
  });

  it("fr29_polling_uses_background_header", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { f, container } = await open();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    expect(f.last(MY_TASKS).headers.get("X-GT-Background")).toBeNull();
    const before = f.count(MY_TASKS);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(MY_TASKS)).toBeGreaterThan(before));
    expect(f.last(MY_TASKS).headers.get("X-GT-Background")).toBe("1");
  });

  it("nfr6_error_alert_is_dictionary_text", async () => {
    await open([], { [MY_TASKS]: () => err(500, "internal_error") });
    expect((await screen.findByRole("alert")).textContent).toBe(errorMessage("internal_error"));
  });
});

