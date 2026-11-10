// 024 «Сводка»: диапазон срока «с / по» (FR-5…FR-8; AC-7, AC-8, AC-9) и хранение (FR-8).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { installFetch, j, meWith, page, renderApp } from "../admin/helpers";

const ME = "GET /api/v1/me";
const COUNTS = "GET /api/v1/me/overview";
const TASKS = "GET /api/v1/me/overview/tasks";
const PROJECTS = "GET /api/v1/me/overview/projects";
const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const P1 = "33333333-3333-4333-8333-333333333333";
const ITEM = "aaaaaaaa-0000-4000-8000-000000000001";
const ERROR = "Дата «с» не может быть позже даты «по»";
const COUNTS_24 = { total: 24, todo: 6, in_progress: 9, review: 4, done: 5, needs_review: 2 };

function item(id: string) {
  return {
    id,
    title: "Задача",
    project: { id: P1, name: "Клиника" },
    parent_id: null,
    status: "todo",
    priority: "medium",
    due_date: null,
    assignee: null,
    hot: false,
  };
}

function tasksPage(items: unknown[], total: number, hasNext = false, p = 1) {
  return { items, page: p, page_size: 50, has_next: hasNext, total };
}

function setup(hasNext = false) {
  return installFetch({
    [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
    [COUNTS]: () => j(200, COUNTS_24),
    [TASKS]: (req) => {
      const p = Number(new URL(req.url).searchParams.get("page") ?? "1");
      return j(200, tasksPage([item(ITEM)], 1, hasNext, p));
    },
    [PROJECTS]: () => j(200, page([])),
  });
}

async function openSummary() {
  const f = setup();
  const view = renderApp("/summary");
  await screen.findByRole("form", { name: "Фильтры" });
  return { f, ...view };
}

/** Поля диапазона по их видимым подписям «с» и «по» (NFR-3). */
const from = (c: HTMLElement) => within(c).getByLabelText("с") as HTMLInputElement;
const to = (c: HTMLElement) => within(c).getByLabelText("по") as HTMLInputElement;

function preset(c: HTMLElement, due: string): HTMLButtonElement {
  const el = c.querySelector<HTMLButtonElement>(`button[data-due="${due}"]`);
  if (el === null) throw new Error(`no preset ${due}`);
  return el;
}

afterEach(() => vi.unstubAllGlobals());

describe("диапазон срока «с / по»", () => {
  it("block_has_two_date_fields_and_moscow_caption", async () => {
    const { container } = await openSummary();
    const block = container.querySelector<HTMLElement>(".sum-range");
    expect(block).not.toBeNull();
    const b = within(block!);
    expect(b.getByText("даты по Москве")).toBeTruthy();
    expect(b.getByLabelText("с").getAttribute("type")).toBe("date");
    expect(b.getByLabelText("по").getAttribute("type")).toBe("date");
    expect(from(container).value).toBe("");
    expect(to(container).value).toBe("");
  });

  it("ac7_date_field_releases_preset_and_request_has_no_due", async () => {
    const { container, f } = await openSummary();
    fireEvent.click(preset(container, "tomorrow"));
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due")).toBe("tomorrow"));
    fireEvent.change(from(container), { target: { value: "2026-11-16" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_from")).toBe("2026-11-16"));
    expect(f.query(f.last(TASKS)).get("due")).toBeNull();
    for (const d of ["overdue", "today", "tomorrow", "week", "none"]) {
      expect(preset(container, d).getAttribute("aria-pressed")).toBe("false");
    }
  });

  it("ac7_preset_clears_both_date_fields", async () => {
    const { container, f } = await openSummary();
    fireEvent.change(from(container), { target: { value: "2026-11-09" } });
    fireEvent.change(to(container), { target: { value: "2026-11-13" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_to")).toBe("2026-11-13"));
    fireEvent.click(preset(container, "week"));
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due")).toBe("week"));
    expect(from(container).value).toBe("");
    expect(to(container).value).toBe("");
    const q = f.query(f.last(TASKS));
    expect(q.get("due_from")).toBeNull();
    expect(q.get("due_to")).toBeNull();
  });

  it("second_field_also_releases_preset", async () => {
    const { container, f } = await openSummary();
    fireEvent.click(preset(container, "today"));
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due")).toBe("today"));
    fireEvent.change(to(container), { target: { value: "2026-11-20" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_to")).toBe("2026-11-20"));
    expect(preset(container, "today").getAttribute("aria-pressed")).toBe("false");
  });

  it("only_from_or_only_to_sends_one_bound", async () => {
    const { container, f } = await openSummary();
    fireEvent.change(from(container), { target: { value: "2026-11-16" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_from")).toBe("2026-11-16"));
    expect(f.query(f.last(TASKS)).get("due_to")).toBeNull();
    fireEvent.change(from(container), { target: { value: "" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_from")).toBeNull());
  });

  it("valid_range_sends_both_bounds_inclusive", async () => {
    const { container, f } = await openSummary();
    fireEvent.change(from(container), { target: { value: "2026-11-16" } });
    fireEvent.change(to(container), { target: { value: "2026-11-20" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_to")).toBe("2026-11-20"));
    const q = f.query(f.last(TASKS));
    expect(q.get("due_from")).toBe("2026-11-16");
    expect(q.get("due")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ac8_from_after_to_shows_error_and_sends_no_request", async () => {
    const { container, f } = await openSummary();
    fireEvent.change(to(container), { target: { value: "2026-11-09" } });
    await waitFor(() => expect(f.count(TASKS)).toBeGreaterThan(0));
    const before = f.count(TASKS);
    fireEvent.change(from(container), { target: { value: "2026-11-13" } });
    const alert = await screen.findByText(ERROR);
    expect(alert.closest('[role="alert"]')).not.toBeNull();
    const start = from(container);
    expect(start.getAttribute("aria-invalid")).toBe("true");
    expect(to(container).getAttribute("aria-invalid")).toBeNull();
    const alertEl = alert.closest<HTMLElement>('[role="alert"]')!;
    expect(alertEl.id).not.toBe("");
    expect(start.getAttribute("aria-describedby")).toContain(alertEl.id);
    expect(f.count(TASKS)).toBe(before);
  });

  it("ac8_equal_dates_are_valid", async () => {
    const { container } = await openSummary();
    fireEvent.change(from(container), { target: { value: "2026-11-13" } });
    fireEvent.change(to(container), { target: { value: "2026-11-13" } });
    expect(screen.queryByText(ERROR)).toBeNull();
    expect(from(container).getAttribute("aria-invalid")).toBeNull();
  });

  it("ac8_error_clears_when_range_fixed", async () => {
    const { container, f } = await openSummary();
    fireEvent.change(to(container), { target: { value: "2026-11-09" } });
    fireEvent.change(from(container), { target: { value: "2026-11-13" } });
    await screen.findByText(ERROR);
    fireEvent.change(from(container), { target: { value: "2026-11-05" } });
    await waitFor(() => expect(screen.queryByText(ERROR)).toBeNull());
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due_from")).toBe("2026-11-05"));
  });

  it("ac9_range_change_returns_to_first_page", async () => {
    const f = setup(true);
    const { container } = renderApp("/summary");
    await screen.findByRole("form", { name: "Фильтры" });
    await waitFor(() => expect(container.querySelector('[data-action="next-page"]')).not.toBeNull());
    const next = container.querySelector<HTMLButtonElement>('[data-action="next-page"]')!;
    await waitFor(() => expect(next.disabled).toBe(false));
    fireEvent.click(next);
    await waitFor(() => expect(f.query(f.last(TASKS)).get("page")).toBe("2"));
    fireEvent.change(to(container), { target: { value: "2026-11-20" } });
    await waitFor(() => expect(f.query(f.last(TASKS)).get("page")).toBe("1"));
    expect(f.query(f.last(TASKS)).get("due_to")).toBe("2026-11-20");
  });

  it("range_is_not_restored_between_sessions", async () => {
    const first = await openSummary();
    fireEvent.change(from(first.container), { target: { value: "2026-11-16" } });
    await waitFor(() => expect(first.f.query(first.f.last(TASKS)).get("due_from")).toBe("2026-11-16"));
    first.unmount();
    const second = await openSummary();
    expect(from(second.container).value).toBe("");
    expect(second.f.query(second.f.last(TASKS)).get("due_from")).toBeNull();
  });

  it("count_line_and_polling_keep_working_with_range", async () => {
    const { container, f } = await openSummary();
    fireEvent.change(from(container), { target: { value: "2026-11-16" } });
    await waitFor(() => expect(f.count(TASKS)).toBeGreaterThan(1));
    expect(container.querySelector(".sum-count-note")?.textContent).toBe("Показано 1 из 1");
  });
});
