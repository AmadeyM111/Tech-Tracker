// 008 «Сводка»: AC-12 (пустое состояние, пункт меню), AC-13 (клик по плитке), FR-6...FR-9 (UI).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CAPS_ALL, deferred, installFetch, j, meWith, page, renderApp, type Handler } from "../admin/helpers";

const ME = "GET /api/v1/me";
const COUNTS = "GET /api/v1/me/overview";
const TASKS = "GET /api/v1/me/overview/tasks";
const PROJECTS = "GET /api/v1/me/overview/projects";
const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const P1 = "33333333-3333-4333-8333-333333333333";

const COUNTS_24 = { total: 24, todo: 6, in_progress: 9, review: 4, done: 5, needs_review: 2 };
const ZERO = { total: 0, todo: 0, in_progress: 0, review: 0, done: 0, needs_review: 0 };

function item(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    title: `Задача ${id.slice(0, 4)}`,
    project: { id: P1, name: "Клиника" },
    parent_id: null,
    status: "todo",
    priority: "medium",
    due_date: null,
    assignee: null,
    hot: false,
    ...over,
  };
}

function tasksPage(items: unknown[], total: number) {
  return { items, page: 1, page_size: 50, has_next: false, total };
}

function setup(counts = COUNTS_24, items: unknown[] = [], total = items.length) {
  return installFetch({
    [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
    [COUNTS]: () => j(200, counts),
    [TASKS]: () => j(200, tasksPage(items, total)),
    [PROJECTS]: () => j(200, page([])),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("SummaryPage", () => {
  it("ac12_empty_state_keeps_zero_tiles_and_shows_approved_text", async () => {
    setup(ZERO);
    renderApp("/summary");
    expect(
      await screen.findByText(
        "Задач пока нет. Они появятся, когда вас добавят в проект или вы создадите задачу.",
      ),
    ).toBeTruthy();
    const tiles = screen.getByRole("list", { name: "Счётчики задач" });
    expect(within(tiles).getAllByText("0")).toHaveLength(6);
    expect(screen.queryByRole("form", { name: "Фильтры" })).toBeNull();
  });

  it("tiles_order_counts_and_accent_on_needs_review", async () => {
    setup(COUNTS_24, [item("aaaaaaaa-0000-4000-8000-000000000001")], 1);
    const { container } = renderApp("/summary");
    await screen.findByText("24");
    const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>("button[data-tile]"));
    expect(buttons.map((b) => b.dataset.tile)).toEqual([
      "needs_review", "total", "todo", "in_progress", "review", "done",
    ]);
    expect(buttons[0]?.className).toContain("sum-tile--review");
    expect(buttons[0]?.textContent).toBe("Нужно проверить2");
    expect(buttons[1]?.getAttribute("aria-pressed")).toBe("true");
  });

  it("ac13_tile_click_sets_status_filter", async () => {
    const f = setup(COUNTS_24, [], 0);
    const { container } = renderApp("/summary");
    await screen.findByText("24");
    fireEvent.click(container.querySelector<HTMLButtonElement>('button[data-tile="in_progress"]')!);
    await waitFor(() => expect(f.query(f.last(TASKS)).get("status")).toBe("in_progress"));
    expect(container.querySelector('button[data-tile="in_progress"]')?.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(container.querySelector<HTMLButtonElement>('button[data-tile="needs_review"]')!);
    await waitFor(() => expect(f.query(f.last(TASKS)).get("needs_review")).toBe("true"));
    expect(f.query(f.last(TASKS)).get("status")).toBeNull();
  });

  it("priority_is_multiselect_and_due_preset_single_choice", async () => {
    const f = setup(COUNTS_24, [], 0);
    const { container } = renderApp("/summary");
    await screen.findByRole("form", { name: "Фильтры" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Низкий" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Высокий" }));
    await waitFor(() => expect(f.query(f.last(TASKS)).getAll("priority")).toEqual(["low", "high"]));
    const today = container.querySelector<HTMLButtonElement>('button[data-due="today"]')!;
    const week = container.querySelector<HTMLButtonElement>('button[data-due="week"]')!;
    fireEvent.click(today);
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due")).toBe("today"));
    fireEvent.click(week);
    await waitFor(() => expect(f.query(f.last(TASKS)).getAll("due")).toEqual(["week"]));
    expect(today.getAttribute("aria-pressed")).toBe("false");
    expect(week.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(week);
    await waitFor(() => expect(f.query(f.last(TASKS)).get("due")).toBeNull());
  });

  it("shows_count_hot_mark_and_overdue_text", async () => {
    setup(
      COUNTS_24,
      [
        item("aaaaaaaa-0000-4000-8000-000000000001", { priority: "high", due_date: "2020-01-01", hot: true }),
        item("aaaaaaaa-0000-4000-8000-000000000002"),
      ],
      7,
    );
    const { container } = renderApp("/summary");
    expect(await screen.findByText("Показано 2 из 7")).toBeTruthy();
    const hotRow = container.querySelector('tr[data-task-id="aaaaaaaa-0000-4000-8000-000000000001"]')!;
    expect(within(hotRow as HTMLElement).getByText("Горит")).toBeTruthy();
    expect(hotRow.querySelector('[data-field="due_date"]')?.textContent).toBe("01.01.2020 · просрочено");
    const plain = container.querySelector('tr[data-task-id="aaaaaaaa-0000-4000-8000-000000000002"]')!;
    expect(within(plain as HTMLElement).queryByText("Горит")).toBeNull();
  });

  it("tech_admin_has_no_summary_menu_item", async () => {
    installFetch({
      [ME]: () => j(200, meWith(CAPS_ALL)),
      "GET /api/v1/admin/users": () => j(200, page([])),
    });
    const { container } = renderApp("/admin/users");
    await waitFor(() => expect(container.querySelector('nav a[href="/admin/users"]')).not.toBeNull());
    expect(container.querySelector('a[href="/summary"]')).toBeNull();
  });
});


describe("025 CSV export button", () => {
  const CSV = "GET /api/v1/me/overview/tasks.csv";
  const EXPORT_CAPS = [...BA_CAPS, "export_overview"];
  const rows = [item("aaaa1111-1111-4111-8111-111111111111")];
  const file = () =>
    new Response("\ufeff\"Проект\"\r\n", {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="gtrack-summary-20261110-1200.csv"',
      },
    });

  function setupExport(caps: string[], csv: Handler = file) {
    return installFetch({
      [ME]: () => j(200, meWith(caps, "business_admin")),
      [COUNTS]: () => j(200, COUNTS_24),
      [TASKS]: () => j(200, tasksPage(rows, 1)),
      [PROJECTS]: () => j(200, page([])),
      [CSV]: csv,
    });
  }

  function stubDownload() {
    const saved: string[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    return saved;
  }

  afterEach(() => vi.restoreAllMocks());

  it("button_and_caption_only_with_export_overview", async () => {
    setupExport(BA_CAPS);
    const first = renderApp("/summary");
    await screen.findByText("Показано 1 из 1");
    expect(screen.queryByRole("button", { name: "Скачать CSV" })).toBeNull();
    first.unmount();
    setupExport(EXPORT_CAPS);
    renderApp("/summary");
    expect(await screen.findByRole("button", { name: "Скачать CSV" })).toBeTruthy();
    expect(
      screen.getByText("В файл попадают все задачи текущей выборки с фильтрами, а не только текущая страница"),
    ).toBeTruthy();
  });

  it("click_sends_current_filters_and_saves_file_under_server_name", async () => {
    const f = setupExport(EXPORT_CAPS);
    const saved = stubDownload();
    renderApp("/summary");
    fireEvent.click(await screen.findByLabelText("Высокий"));
    fireEvent.click(await screen.findByRole("button", { name: "Скачать CSV" }));
    await waitFor(() => expect(saved).toEqual(["gtrack-summary-20261110-1200.csv"]));
    const q = f.query(f.last(CSV));
    expect(q.getAll("priority")).toEqual(["high"]);
    expect(q.has("page")).toBe(false);
  });

  it("export_sends_the_date_range_and_the_applied_filters_only", async () => {
    const f = setupExport(EXPORT_CAPS);
    const saved = stubDownload();
    renderApp("/summary");
    const from = (await screen.findByLabelText("с")) as HTMLInputElement;
    const to = screen.getByLabelText("по") as HTMLInputElement;
    fireEvent.change(from, { target: { value: "2026-11-16" } });
    fireEvent.change(to, { target: { value: "2026-11-20" } });
    fireEvent.click(await screen.findByRole("button", { name: "Скачать CSV" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    const q = f.query(f.last(CSV));
    expect(q.get("due_from")).toBe("2026-11-16");
    expect(q.get("due_to")).toBe("2026-11-20");
    expect(q.has("due")).toBe(false);
    // «с» позже «по»: запрос списка не уходит, выгрузка идёт по последней действующей выборке
    fireEvent.change(from, { target: { value: "2026-12-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await waitFor(() => expect(saved).toHaveLength(2));
    const again = f.query(f.last(CSV));
    expect(again.get("due_from")).toBe("2026-11-16");
    expect(again.get("due_to")).toBe("2026-11-20");
  });

  it("button_is_disabled_with_status_text_while_preparing", async () => {
    const gate = deferred<Response>();
    setupExport(EXPORT_CAPS, () => gate.promise);
    stubDownload();
    renderApp("/summary");
    fireEvent.click(await screen.findByRole("button", { name: "Скачать CSV" }));
    const busy = (await screen.findByRole("button", { name: "Готовим файл…" })) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    expect(screen.getAllByRole("status").some((el) => el.textContent === "Готовим файл…")).toBe(true);
    gate.resolve(file());
    expect(((await screen.findByRole("button", { name: "Скачать CSV" })) as HTMLButtonElement).disabled).toBe(false);
  });

  it("too_large_shows_message_and_button_is_enabled_again", async () => {
    setupExport(EXPORT_CAPS, () =>
      j(422, { detail: "В выборке 12000 задач, максимум 10000. Сузьте фильтры", code: "export_too_large" }),
    );
    renderApp("/summary");
    fireEvent.click(await screen.findByRole("button", { name: "Скачать CSV" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Выборка слишком велика для выгрузки. Сузьте фильтры");
    expect(((await screen.findByRole("button", { name: "Скачать CSV" })) as HTMLButtonElement).disabled).toBe(false);
  });
});

// Аудит #9: отфильтрованный пустой список на первой странице - без пагинации; непустой - с пагинацией.
describe("пагинация сводки при пустом списке (аудит #9)", () => {
  function withTasks(items: unknown[], hasNext: boolean) {
    installFetch({
      [ME]: () => j(200, meWith(BA_CAPS, "business_admin")),
      [COUNTS]: () => j(200, COUNTS_24),
      [TASKS]: () => j(200, { ...tasksPage(items, items.length), has_next: hasNext }),
      [PROJECTS]: () => j(200, page([])),
    });
  }

  it("empty_list_has_no_pagination_even_when_next_flag_is_set", async () => {
    withTasks([], true);
    const { container } = renderApp("/summary");
    await waitFor(() => expect(container.querySelector(".sum-count-note")).toBeTruthy());
    expect(container.querySelector(".ui-pagination")).toBeNull();
    expect(container.querySelector('[data-action="next-page"]')).toBeNull();
    expect(container.querySelector('[data-action="prev-page"]')).toBeNull();
  });

  it("non_empty_list_with_next_page_keeps_pagination", async () => {
    withTasks([item("aaaaaaaa-0000-4000-8000-000000000001")], true);
    const { container } = renderApp("/summary");
    await waitFor(() => expect(container.querySelector(".ui-pagination")).not.toBeNull());
  });
});
