// R6-T09: чистые правила черновика задачи (006 FR-19, D-11; plan 4.5).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DRAFT_FIELDS, taskDraftErrors, todayMsk } from "../../../src/features/tasks/CreateTaskForm";
import { ru } from "../../../src/shared/i18n";

const ORIGINAL_TZ = process.env.TZ;
const ZONES = ["UTC", "Europe/Moscow", "America/Los_Angeles", "Pacific/Kiritimati"];

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  if (ORIGINAL_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIGINAL_TZ;
});

describe("todayMsk (D-11)", () => {
  const CASES: [string, string][] = [
    ["2026-10-19T21:30:00Z", "2026-10-20"],
    ["2026-10-20T20:59:59Z", "2026-10-20"],
    ["2026-10-20T21:00:00Z", "2026-10-21"],
    ["2026-10-20T00:00:00Z", "2026-10-20"],
  ];

  for (const zone of ZONES) {
    it(`d11_today_msk_boundaries_do_not_depend_on_TZ_${zone}`, () => {
      process.env.TZ = zone;
      for (const [iso, expected] of CASES) {
        vi.setSystemTime(new Date(iso));
        expect(todayMsk(), `${iso} in ${zone}`).toBe(expected);
        expect(todayMsk(new Date(iso))).toBe(expected);
      }
    });
  }

  it("d11_today_msk_explicit_now_wins_over_system_clock", () => {
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    expect(todayMsk(new Date("2026-10-20T21:00:00Z"))).toBe("2026-10-21");
  });

  it("d11_today_msk_format_is_iso_date", () => {
    vi.setSystemTime(new Date("2026-03-05T10:00:00Z"));
    expect(todayMsk()).toBe("2026-03-05");
  });
});

describe("DRAFT_FIELDS (FR-19)", () => {
  it("fr19_field_order_is_title_description_due_assignee", () => {
    expect([...DRAFT_FIELDS]).toEqual(["title", "description", "due_date", "assignee"]);
  });
});

describe("taskDraftErrors (FR-19)", () => {
  const TODAY = "2026-10-20";

  it("fr19_title_blank_is_required_error", () => {
    expect(taskDraftErrors({ title: "" }, TODAY)).toEqual({ title: "tasks.error_title_required" });
    expect(taskDraftErrors({ title: " \n\t " }, TODAY)).toEqual({ title: "tasks.error_title_required" });
  });

  it("fr19_title_non_blank_is_ok", () => {
    expect(taskDraftErrors({ title: " x " }, TODAY)).toEqual({});
  });

  it("fr19_description_blank_is_required_error", () => {
    expect(taskDraftErrors({ description: "" }, TODAY)).toEqual({ description: "tasks.error_description_required" });
    expect(taskDraftErrors({ description: " \n\t " }, TODAY)).toEqual({
      description: "tasks.error_description_required",
    });
    expect(taskDraftErrors({ description: "текст" }, TODAY)).toEqual({});
  });

  it("fr19_due_empty_is_required_error", () => {
    expect(taskDraftErrors({ dueDate: "" }, TODAY)).toEqual({ due_date: "tasks.error_due_required" });
  });

  it("fr19_due_yesterday_is_past_error", () => {
    expect(taskDraftErrors({ dueDate: "2026-10-19" }, TODAY)).toEqual({ due_date: "tasks.error_due_past" });
  });

  it("fr19_due_today_and_later_are_ok", () => {
    expect(taskDraftErrors({ dueDate: TODAY }, TODAY)).toEqual({});
    expect(taskDraftErrors({ dueDate: "2026-10-21" }, TODAY)).toEqual({});
    expect(taskDraftErrors({ dueDate: "2027-01-01" }, TODAY)).toEqual({});
  });

  it("fr19_assignee_null_is_error_undefined_is_not_checked", () => {
    expect(taskDraftErrors({ assigneeId: null }, TODAY)).toEqual({ assignee: "tasks.error_assignee_required" });
    expect(taskDraftErrors({ assigneeId: undefined }, TODAY)).toEqual({});
    expect(taskDraftErrors({ assigneeId: "u1" }, TODAY)).toEqual({});
  });

  it("fr19_absent_keys_are_not_checked", () => {
    expect(taskDraftErrors({}, TODAY)).toEqual({});
  });

  it("fr19_all_errors_together", () => {
    expect(
      taskDraftErrors({ title: "", description: " ", dueDate: "", assigneeId: null }, TODAY),
    ).toEqual({
      title: "tasks.error_title_required",
      description: "tasks.error_description_required",
      due_date: "tasks.error_due_required",
      assignee: "tasks.error_assignee_required",
    });
  });

  it("fr19_valid_draft_has_no_errors", () => {
    expect(
      taskDraftErrors({ title: "a", description: "b", dueDate: TODAY, assigneeId: "u" }, TODAY),
    ).toEqual({});
  });

  it("fr19_error_keys_exist_in_dictionary_with_expected_texts", () => {
    const d = ru as Record<string, string>;
    expect(d["tasks.error_title_required"]).toBe("Введите название задачи");
    expect(d["tasks.error_description_required"]).toBe("Введите описание задачи");
    expect(d["tasks.error_due_required"]).toBe("Укажите срок");
    expect(d["tasks.error_due_past"]).toBe("Срок не может быть раньше сегодняшнего дня");
    expect(d["tasks.error_assignee_required"]).toBe("Выберите исполнителя");
  });
});
