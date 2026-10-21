// R6-T12: правила изменения задачи верхнего уровня в карточке. spec 006 AC-56 (FR-23), NFR-2 (строки из словаря);
// plan §4.8. Время фиксировано: 2026-10-20T09:00:00Z (в Москве 12:00, «сегодня» = 2026-10-20).
// Тексты сообщений заданы литералами из spec (а не из словаря), чтобы тест не проходил при любых значениях в ru.ts.
import { fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { errorMessage } from "../../../src/shared/i18n";
import {
  PATCH,
  bodyOf,
  card,
  clearAssigneeBtn,
  describedMessage,
  descArea,
  dueInput,
  editForm,
  err,
  f_,
  j,
  openCard,
  openSubCardPage,
  setValue,
  subCard,
  titleInput,
  waitCount,
} from "./taskpage-helpers";

const NOW = new Date("2026-10-20T09:00:00Z");
const MSG_DUE_REQUIRED = "Укажите срок";
const MSG_DUE_PAST = "Срок не может быть раньше сегодняшнего дня";
const MSG_DESC_REQUIRED = "Введите описание задачи";

beforeEach(() => {
  vi.stubEnv("TZ", "UTC");
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

/** Задача верхнего уровня T: исполнитель, срок 2026-10-25, описание (AC-56, Given). */
const top = (over: Record<string, unknown> = {}) =>
  card({ due_date: "2026-10-25", description: "Квартальный отчёт", parent_id: null, ...over });

const alerts = () => Array.from(document.querySelectorAll('[role="alert"]')).map((e) => e.textContent);
const noRequest = async (f: { count: (k: string) => number }) => {
  await new Promise((r) => setTimeout(r, 40));
  expect(f.count(PATCH)).toBe(0);
};

describe("006 AC-56: карточка задачи верхнего уровня (FR-23)", () => {
  it("006_ac56_no_clear_assignee_button", async () => {
    const { container } = await openCard(() => top());
    expect(f_(container, "assignee")!.textContent).toContain("kuznetsov");
    expect(clearAssigneeBtn(container)).toBeNull();
  });

  it("006_ac56_cleared_due_blocks_request_message_linked_values_kept", async () => {
    const { container, f } = await openCard(() => top());
    setValue(dueInput(), "");
    setValue(descArea(), "Новое описание");
    fireEvent.submit(editForm(container)!);
    await waitFor(() => expect(dueInput()!.getAttribute("aria-invalid")).toBe("true"));
    const msg = describedMessage(dueInput());
    expect(msg?.textContent).toBe(MSG_DUE_REQUIRED);
    expect(dueInput()!.value).toBe("");
    expect(descArea()!.value).toBe("Новое описание");
    expect(descArea()!.getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(dueInput());
    expect(alerts()).toEqual([MSG_DUE_REQUIRED]);
    await noRequest(f);
  });

  it("006_ac56_past_due_blocks_request_with_past_message", async () => {
    const { container, f } = await openCard(() => top());
    setValue(dueInput(), "2026-10-19");
    fireEvent.submit(editForm(container)!);
    await waitFor(() => expect(dueInput()!.getAttribute("aria-invalid")).toBe("true"));
    expect(describedMessage(dueInput())?.textContent).toBe(MSG_DUE_PAST);
    expect(dueInput()!.value).toBe("2026-10-19");
    expect(document.activeElement).toBe(dueInput());
    await noRequest(f);
  });

  it("006_ac56_blank_description_blocks_request_with_required_message", async () => {
    const { container, f } = await openCard(() => top());
    setValue(descArea(), "   ");
    fireEvent.submit(editForm(container)!);
    await waitFor(() => expect(descArea()!.getAttribute("aria-invalid")).toBe("true"));
    expect(describedMessage(descArea())?.textContent).toBe(MSG_DESC_REQUIRED);
    expect(descArea()!.value).toBe("   ");
    expect(document.activeElement).toBe(descArea());
    expect(dueInput()!.getAttribute("aria-invalid")).toBeNull();
    await noRequest(f);
  });

  it("006_ac56_two_errors_two_messages_focus_on_first_invalid_field", async () => {
    const { container, f } = await openCard(() => top());
    setValue(descArea(), "");
    setValue(dueInput(), "");
    fireEvent.submit(editForm(container)!);
    await waitFor(() => expect(descArea()!.getAttribute("aria-invalid")).toBe("true"));
    expect(dueInput()!.getAttribute("aria-invalid")).toBe("true");
    expect(describedMessage(descArea())?.textContent).toBe(MSG_DESC_REQUIRED);
    expect(describedMessage(dueInput())?.textContent).toBe(MSG_DUE_REQUIRED);
    expect(document.activeElement).toBe(descArea());
    await noRequest(f);
  });

  it("006_ac56_today_in_moscow_is_allowed_and_zone_independent", async () => {
    // 21:30Z 19.10 = 00:30 MSK 20.10: «сегодня» = 2026-10-20, 2026-10-19 уже прошёл.
    vi.setSystemTime(new Date("2026-10-19T21:30:00Z"));
    const { container, f } = await openCard(() => top(), { [PATCH]: () => j(200, top({ due_date: "2026-10-20" })) });
    setValue(dueInput(), "2026-10-19");
    fireEvent.submit(editForm(container)!);
    await waitFor(() => expect(dueInput()!.getAttribute("aria-invalid")).toBe("true"));
    expect(describedMessage(dueInput())?.textContent).toBe(MSG_DUE_PAST);
    expect(f.count(PATCH)).toBe(0);
    setValue(dueInput(), "2026-10-20");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ due_date: "2026-10-20" });
  });

  it("006_ac56_server_422_due_date_in_past_shown_at_due_field_values_kept", async () => {
    const { container, f } = await openCard(() => top(), { [PATCH]: () => err(422, "due_date_in_past") });
    setValue(dueInput(), "2026-10-21");
    setValue(descArea(), "Новое описание");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    await waitFor(() => expect(dueInput()!.getAttribute("aria-invalid")).toBe("true"));
    expect(describedMessage(dueInput())?.textContent).toBe(errorMessage("due_date_in_past"));
    expect(errorMessage("due_date_in_past")).toBe(MSG_DUE_PAST);
    expect(dueInput()!.value).toBe("2026-10-21");
    expect(descArea()!.value).toBe("Новое описание");
    // общий alert пуст: единственное сообщение - у поля срока
    expect(alerts()).toEqual([MSG_DUE_PAST]);
  });

  it("006_ac56_field_messages_are_cleared_on_next_save", async () => {
    const { container, f } = await openCard(() => top(), { [PATCH]: () => j(200, top({ due_date: "2026-10-26" })) });
    setValue(dueInput(), "");
    fireEvent.submit(editForm(container)!);
    await waitFor(() => expect(dueInput()!.getAttribute("aria-invalid")).toBe("true"));
    setValue(dueInput(), "2026-10-26");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ due_date: "2026-10-26" });
    await waitFor(() => expect(dueInput()!.getAttribute("aria-invalid")).toBeNull());
    expect(describedMessage(dueInput())).toBeNull();
    expect(alerts()).toEqual([]);
  });

  it("006_ac56_old_task_without_due_and_description_saves_title_only_single_patch", async () => {
    const { container, f } = await openCard(() => top({ due_date: null, description: "" }), {
      [PATCH]: () => j(200, top({ due_date: null, description: "", title: "Новое имя" })),
    });
    setValue(titleInput(), "Новое имя");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ title: "Новое имя" });
    expect(alerts()).toEqual([]);
    expect(dueInput()!.getAttribute("aria-invalid")).toBeNull();
    expect(descArea()!.getAttribute("aria-invalid")).toBeNull();
  });

  it("006_ac56_only_changed_fields_are_checked_stale_past_due_does_not_block_title", async () => {
    const { container, f } = await openCard(() => top({ due_date: "2026-10-01" }), {
      [PATCH]: () => j(200, top({ due_date: "2026-10-01", title: "Новое имя" })),
    });
    setValue(titleInput(), "Новое имя");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ title: "Новое имя" });
    expect(alerts()).toEqual([]);
  });
});

describe("006 AC-56: карточка подзадачи - как раньше (FR-23 не касается подзадач)", () => {
  it("006_ac56_subtask_has_clear_assignee_button", async () => {
    const { container } = await openSubCardPage(() => subCard({ due_date: "2026-10-25" }));
    expect(clearAssigneeBtn(container)).not.toBeNull();
  });

  it("006_ac56_subtask_cleared_due_sends_null_without_messages", async () => {
    const { container, f } = await openSubCardPage(() => subCard({ due_date: "2026-10-25" }), {
      [PATCH]: () => j(200, subCard({ due_date: null })),
    });
    setValue(dueInput(), "");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ due_date: null });
    expect(alerts()).toEqual([]);
    expect(dueInput()!.getAttribute("aria-invalid")).toBeNull();
  });

  it("006_ac56_subtask_blank_description_and_past_due_are_sent_without_checks", async () => {
    const { container, f } = await openSubCardPage(() => subCard({ due_date: "2026-10-25" }), {
      [PATCH]: () => j(200, subCard({ due_date: "2026-10-01", description: "" })),
    });
    setValue(descArea(), "");
    setValue(dueInput(), "2026-10-01");
    fireEvent.submit(editForm(container)!);
    await waitCount(f, PATCH, 1);
    expect(await bodyOf(f.last(PATCH))).toEqual({ description: "", due_date: "2026-10-01" });
    expect(alerts()).toEqual([]);
  });
});
