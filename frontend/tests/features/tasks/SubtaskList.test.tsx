// T84: подзадачи в карточке задачи.
// AC: UF-4, FR-21 (один уровень), FR-22 (прогресс; null = «нет подзадач»), AC-7, AC-47, NFR-6, NFR-7.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage } from "../../../src/shared/i18n";
import {
  SUB1,
  SUB2,
  SUB3,
  SUB_POST,
  TASK,
  TID3,
  bodyOf,
  card,
  d,
  deferred,
  err,
  f_,
  j,
  openCard,
  setValue,
  sub,
  subForm,
  subSection,
  waitCount,
  EXECUTOR_PERMS,
  ALL_PERMS,
} from "./taskpage-helpers";

const SUBS = [sub(SUB1, "Собрать данные", "done"), sub(SUB2, "Написать текст", "review"), sub(SUB3, "Согласовать", "todo")];
const titleInput = (c: ParentNode) => subForm(c)!.querySelector<HTMLInputElement>('input[name="title"]')!;
const TITLE_REQUIRED = "Введите название подзадачи";
const TITLE_TOO_LONG = "Название подзадачи — не более 255 символов";
/** role=alert вне раздела «Подзадачи» (общая область сообщений карточки). */
const outsideSection = (c: ParentNode) =>
  Array.from(c.querySelectorAll('[role="alert"]')).filter((e) => e.closest('[data-section="subtasks"]') === null);
const sectionAlerts = (c: ParentNode) => within(subSection(c)!).queryAllByRole("alert");
const row = (c: ParentNode, id: string) => c.querySelector<HTMLElement>(`[data-subtask-id="${id}"]`)!;

describe("subtask list and progress (UF-4, FR-22, AC-7)", () => {
  it("uf4_rows_show_title_link_status_and_assignee", async () => {
    const subs = [{ ...sub(SUB1, "Собрать данные", "done"), assignee: { id: "x", login: "petrov" } }, ...SUBS.slice(1)];
    const { container } = await openCard(() => card({ subtasks: subs, progress: 33 }));
    const r = row(container, SUB1);
    expect(f_(r, "title")!.querySelector("a")!.getAttribute("href")).toBe(`/tasks/${SUB1}`);
    expect(f_(r, "title")!.textContent).toBe("Собрать данные");
    expect(f_(r, "status")!.textContent).toBe(d("tasks.status.done"));
    expect(f_(r, "assignee")!.textContent).toBe("petrov");
    expect(f_(row(container, SUB3), "assignee")!.textContent).toBe(d("tasks.assignee_none"));
    expect(subSection(container)!.querySelector("h2")!.textContent).toBe(d("tasks.subtasks_title"));
  });

  it("ac7_progress_number_is_shown_as_percent", async () => {
    const { container } = await openCard(() => card({ subtasks: SUBS, progress: 33 }));
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("33%");
  });

  it("ac7_progress_100_is_shown", async () => {
    const all = SUBS.map((s) => ({ ...s, status: "done" }));
    const { container } = await openCard(() => card({ subtasks: all, progress: 100 }));
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("100%");
  });

  it("fr22_null_progress_is_no_subtasks_text_not_zero_percent", async () => {
    const { container } = await openCard(() => card({ subtasks: [], progress: null }));
    const p = f_(subSection(container)!, "progress")!;
    expect(p.textContent).toBe(d("tasks.progress_none"));
    expect(p.textContent).not.toContain("0%");
    expect(container.querySelector('[data-role="empty"]')!.textContent).toBe(d("tasks.subtasks_empty"));
  });

  it("fr22_zero_progress_is_zero_percent_when_subtasks_exist", async () => {
    const { container } = await openCard(() => card({ subtasks: [sub(SUB1, "A", "todo")], progress: 0 }));
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("0%");
  });
});

describe("create subtask (FR-19b, FR-20, FR-21, AC-47)", () => {
  it("fr21_subtask_has_no_create_form_even_with_permission", async () => {
    const { container } = await openCard(() => card({ parent_id: TID3, permissions: ALL_PERMS }));
    expect(subForm(container)).toBeNull();
  });

  it("ac47_no_create_subtask_permission_hides_form", async () => {
    const { container } = await openCard(() => card({ permissions: { ...ALL_PERMS, create_subtask: false } }));
    expect(subForm(container)).toBeNull();
  });

  it("ac47_post_has_trimmed_title_and_no_assignee_key_then_card_is_refetched", async () => {
    let created = false;
    const { container, f } = await openCard(
      () => (created ? card({ subtasks: [sub(SUB1, "Новая подзадача")], progress: 0 }) : card({ permissions: EXECUTOR_PERMS })),
      {
        [SUB_POST]: () => {
          created = true;
          return j(201, card());
        },
      },
      "user",
    );
    const form = subForm(container)!;
    expect(titleInput(container).labels?.length).toBeTruthy();
    setValue(titleInput(container), "  Новая подзадача  ");
    fireEvent.submit(form);
    await waitCount(f, SUB_POST, 1);
    const b = await bodyOf(f.last(SUB_POST));
    expect(b).toEqual({ title: "Новая подзадача" });
    expect("assignee_id" in b).toBe(false);
    await waitFor(() => expect(row(container, SUB1)).toBeTruthy());
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("0%");
    expect(titleInput(container).value).toBe("");
  });

  // R6-T05: было validation_error в общей области карточки; теперь AC-38 (FR-27, FR-28, D-8):
  // причина названа, сообщение в секции «Подзадачи», общая область пуста.
  it("ac47_ac38_empty_title_blocks_request_and_shows_reason_in_subtasks_section", async () => {
    const { container, f } = await openCard();
    setValue(titleInput(container), "  ");
    fireEvent.submit(subForm(container)!);
    const alert = await within(subSection(container)!).findByRole("alert");
    expect(alert.textContent).toBe(TITLE_REQUIRED);
    expect(f.count(SUB_POST)).toBe(0);
  });

  // R6-T05: было forbidden в «единственном» alert страницы; теперь AC-40 (D-8): в секции.
  it("ac47_ac40_403_other_assignee_shows_alert_in_section_and_keeps_input", async () => {
    const { container } = await openCard(() => card(), { [SUB_POST]: () => err(403, "forbidden") });
    setValue(titleInput(container), "Чужая");
    fireEvent.submit(subForm(container)!);
    const alert = await within(subSection(container)!).findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(outsideSection(container)).toHaveLength(0);
    expect(titleInput(container).value).toBe("Чужая");
  });

  it("nfr6_double_submit_sends_one_post", async () => {
    const gate = deferred<Response>();
    const { container, f } = await openCard(() => card(), { [SUB_POST]: () => gate.promise });
    setValue(titleInput(container), "Однократно");
    const form = subForm(container)!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitCount(f, SUB_POST, 1);
    gate.resolve(j(201, card()));
    await waitFor(() => expect(titleInput(container).value).toBe(""));
    expect(f.count(SUB_POST)).toBe(1);
  });
});

describe("subtask form messages (006: AC-38, AC-39, AC-40; FR-27, FR-28, FR-29, D-8)", () => {
  it.each([["empty", ""], ["spaces", "   "]])("ac38_%s_title_message_in_section_with_field_link", async (_n, value) => {
    const { container, f } = await openCard(() => card(), {
      [SUB_POST]: () => j(201, card()),
    });
    setValue(titleInput(container), value);
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(1));
    const alert = sectionAlerts(container)[0]!;
    expect(alert.textContent).toBe(TITLE_REQUIRED);
    expect(f.count(SUB_POST)).toBe(0);
    const input = titleInput(container);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const ref = input.getAttribute("aria-describedby");
    expect(ref).toBeTruthy();
    expect(ref!.split(/\s+/)).toContain(alert.id);
    expect(alert.id).not.toBe("");
    expect(outsideSection(container)).toHaveLength(0);
    expect(document.body.textContent).not.toContain(errorMessage("validation_error"));
  });

  it("ac38_then_valid_title_clears_message_and_creates_subtask", async () => {
    let created = false;
    const { container, f } = await openCard(
      () => (created ? card({ subtasks: [sub(SUB1, "Шаг")], progress: 0 }) : card()),
      {
        [SUB_POST]: () => {
          created = true;
          return j(201, card());
        },
      },
    );
    setValue(titleInput(container), " ");
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(1));
    setValue(titleInput(container), "Шаг");
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 1);
    expect((await bodyOf(f.last(SUB_POST))).title).toBe("Шаг");
    await waitFor(() => expect(row(container, SUB1)).toBeTruthy());
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    const input = titleInput(container);
    expect(input.getAttribute("aria-invalid")).not.toBe("true");
    expect(input.getAttribute("aria-describedby") ?? "").toBe("");
    expect(input.value).toBe("");
  });

  it("ac38_new_submit_clears_previous_message_while_request_pending", async () => {
    const gate = deferred<Response>();
    const { container } = await openCard(() => card(), { [SUB_POST]: () => gate.promise });
    setValue(titleInput(container), "");
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(1));
    setValue(titleInput(container), "Шаг");
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(0));
    gate.resolve(j(201, card()));
    await waitFor(() => expect(titleInput(container).value).toBe(""));
  });

  it("ac39_256_chars_blocked_with_reason_255_sent", async () => {
    const { container, f } = await openCard(() => card(), { [SUB_POST]: () => j(201, card()) });
    setValue(titleInput(container), "а".repeat(256));
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(1));
    expect(sectionAlerts(container)[0]!.textContent).toBe(TITLE_TOO_LONG);
    expect(f.count(SUB_POST)).toBe(0);
    expect(titleInput(container).value).toBe("а".repeat(256));
    expect(outsideSection(container)).toHaveLength(0);
    setValue(titleInput(container), "а".repeat(255));
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 1);
    expect((await bodyOf(f.last(SUB_POST))).title).toBe("а".repeat(255));
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(0));
  });

  it("ac39_length_is_counted_after_trim", async () => {
    const { container, f } = await openCard(() => card(), { [SUB_POST]: () => j(201, card()) });
    setValue(titleInput(container), "  " + "б".repeat(255) + "  ");
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 1);
    expect((await bodyOf(f.last(SUB_POST))).title).toBe("б".repeat(255));
  });

  const FAILS: [string, () => Promise<Response> | Response, string][] = [
    ["403", () => err(403, "forbidden"), errorMessage("forbidden")],
    ["422_depth", () => err(422, "subtask_depth_exceeded"), errorMessage("subtask_depth_exceeded")],
    ["503", () => err(503, "service_busy"), errorMessage("service_busy")],
    ["network", () => Promise.reject(new TypeError("Failed to fetch")), errorMessage("network_error")],
  ];
  it.each(FAILS)("ac40_%s_one_message_in_section_input_kept_retry_sends_new_request", async (_n, handler, text) => {
    let fail = true;
    const { container, f } = await openCard(() => card(), {
      [SUB_POST]: () => (fail ? handler() : j(201, card())),
    });
    setValue(titleInput(container), "Шаг");
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(1));
    expect(sectionAlerts(container)[0]!.textContent).toBe(text);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(outsideSection(container)).toHaveLength(0);
    expect(titleInput(container).value).toBe("Шаг");
    expect(titleInput(container).getAttribute("aria-invalid")).toBe("true");
    expect(f.count(SUB_POST)).toBe(1);
    fail = false;
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 2);
    await waitFor(() => expect(titleInput(container).value).toBe(""));
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("ac40_delayed_response_three_submits_send_one_request", async () => {
    const gate = deferred<Response>();
    const { container, f } = await openCard(() => card(), { [SUB_POST]: () => gate.promise });
    setValue(titleInput(container), "Шаг");
    const form = subForm(container)!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitCount(f, SUB_POST, 1);
    gate.resolve(j(201, card()));
    await waitFor(() => expect(titleInput(container).value).toBe(""));
    expect(f.count(SUB_POST)).toBe(1);
  });

  it("fr29_busy_only_covers_post_not_reread_after_201", async () => {
    // FR-29/PD-16: после ответа 201 следующая отправка разрешена, даже если перечитывание не ответило.
    const gate = deferred<Response>();
    let reads = 0;
    const { container, f } = await openCard(
      () => card(),
      {
        [TASK]: async () => {
          reads += 1;
          if (reads > 1) await gate.promise;
          return j(200, card());
        },
        [SUB_POST]: () => j(201, card()),
      },
    );
    setValue(titleInput(container), "Шаг 1");
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 1);
    await waitFor(() => expect(titleInput(container).value).toBe(""));
    await waitFor(() => expect(document.activeElement).toBe(titleInput(container)));
    setValue(titleInput(container), "Шаг 2");
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 2);
    gate.resolve(j(200, card()));
  });

  it("fr26_message_cleared_and_focus_in_field_after_success", async () => {
    let ok = false;
    const { container, f } = await openCard(() => card(), {
      [SUB_POST]: () => (ok ? j(201, card()) : err(403, "forbidden")),
    });
    setValue(titleInput(container), "Шаг");
    fireEvent.submit(subForm(container)!);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(1));
    ok = true;
    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.submit(subForm(container)!);
    await waitCount(f, SUB_POST, 2);
    await waitFor(() => expect(sectionAlerts(container)).toHaveLength(0));
    await waitFor(() => expect(document.activeElement).toBe(titleInput(container)));
  });
});
