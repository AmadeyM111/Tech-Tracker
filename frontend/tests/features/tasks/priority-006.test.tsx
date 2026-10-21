// R6-T08: три приоритета во фронтенде. spec 006 AC-16 (FR-12, FR-9 форма), AC-52 (NFR-2, часть про приоритеты).
// Подписи берутся из требований (литералы «Низкий»/«Средний»/«Высокий»), а не из словаря: иначе тест
// проходил бы при любых значениях в ru.ts.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import {
  TA,
  TB,
  TC,
  card as boardCard,
  cardEl,
  openBoard,
} from "../boards/helpers";
import {
  createForm,
  f_,
  installFetch,
  openTasksTab,
  PERM_MANAGE,
  PID,
  PROJ_CREATE,
  renderApp,
  taskItem,
  taskRoutes,
  taskRow,
  TID1,
  TID2,
  TID3,
} from "./helpers";
import { card, openCard, prioritySelect, shown } from "./taskpage-helpers";

const LABELS = { low: "Низкий", medium: "Средний", high: "Высокий" } as const;
const ORDER = ["low", "medium", "high"] as const;
const FORBIDDEN = ["Обычный", "Базовый"];

afterEach(() => {
  vi.useRealTimers();
});

const optionLabels = (sel: HTMLSelectElement) =>
  Array.from(sel.options).map((o) => o.textContent);
const optionValues = (sel: HTMLSelectElement) =>
  Array.from(sel.options).map((o) => o.value);

function expectNoForbiddenTexts() {
  const text = document.body.textContent ?? "";
  for (const w of FORBIDDEN) expect(text).not.toContain(w);
}

describe("AC-16: подписи приоритетов на экранах (FR-12)", () => {
  it("ac16_project_task_list_shows_three_labels", async () => {
    const items = [
      taskItem(TID1, "Первая", { priority: "low" }),
      taskItem(TID2, "Вторая", { priority: "medium" }),
      taskItem(TID3, "Третья", { priority: "high" }),
    ];
    installFetch(taskRoutes("business_admin", {}, { items }));
    const { container } = renderApp(`/projects/${PID}`);
    await screen.findByRole("heading", { level: 1, name: "Альфа" });
    await openTasksTab();
    await waitFor(() => expect(taskRow(container, TID1)).toBeTruthy());
    expect(f_(taskRow(container, TID1)!, "priority")!.textContent).toBe(
      "Низкий",
    );
    expect(f_(taskRow(container, TID2)!, "priority")!.textContent).toBe(
      "Средний",
    );
    expect(f_(taskRow(container, TID3)!, "priority")!.textContent).toBe(
      "Высокий",
    );
    expectNoForbiddenTexts();
  });

  it("ac16_board_cards_show_three_labels", async () => {
    const columns = {
      todo: [
        boardCard(TA, "Низкая", "todo", 10, { priority: "low" }),
        boardCard(TB, "Средняя", "todo", 20, { priority: "medium" }),
        boardCard(TC, "Высокая", "todo", 30, { priority: "high" }),
      ],
      in_progress: [],
      review: [],
      done: [],
    };
    const { container } = await openBoard({}, columns);
    expect(f_(cardEl(container, TA)!, "priority")!.textContent).toBe("Низкий");
    expect(f_(cardEl(container, TB)!, "priority")!.textContent).toBe("Средний");
    expect(f_(cardEl(container, TC)!, "priority")!.textContent).toBe("Высокий");
    expectNoForbiddenTexts();
  });

  for (const p of ORDER) {
    it(`ac16_task_card_shows_label_for_${p}`, async () => {
      const { container } = await openCard(() => card({ priority: p }));
      await waitFor(() => expect(shown(container, "priority")).toBe(LABELS[p]));
      expectNoForbiddenTexts();
    });

    it(`ac16_task_card_without_edit_permission_shows_label_for_${p}`, async () => {
      const perms = {
        edit: false,
        change_status: false,
        change_assignee: false,
        delete: false,
        create_subtask: false,
      };
      const { container } = await openCard(() =>
        card({ priority: p, permissions: perms }),
      );
      await waitFor(() =>
        expect(f_(container, "priority")!.textContent).toBe(LABELS[p]),
      );
      expect(f_(container, "priority")!.querySelector("select")).toBeNull();
    });
  }
});

describe("AC-16: поля выбора приоритета (FR-12, FR-9)", () => {
  it("ac16_task_card_select_has_exactly_three_options_in_order", async () => {
    await openCard(() => card({ priority: "high" }));
    const sel = prioritySelect()!;
    expect(sel).toBeTruthy();
    expect(optionValues(sel)).toEqual([...ORDER]);
    expect(optionLabels(sel)).toEqual(["Низкий", "Средний", "Высокий"]);
    expect(sel.value).toBe("high");
  });

  it("ac16_create_form_has_three_options_in_order_and_medium_selected", async () => {
    const f = installFetch(
      taskRoutes("business_admin", {}, { perms: PERM_MANAGE }),
    );
    const { container } = renderApp(`/projects/${PID}`);
    await screen.findByRole("heading", { level: 1, name: "Альфа" });
    await openTasksTab();
    await waitFor(() => expect(createForm(container)).toBeTruthy());
    const sel = createForm(container)!.querySelector<HTMLSelectElement>(
      'select[name="priority"]',
    )!;
    expect(optionValues(sel)).toEqual([...ORDER]);
    expect(optionLabels(sel)).toEqual(["Низкий", "Средний", "Высокий"]);
    expect(sel.value).toBe("medium");
    expect(sel.selectedOptions[0]!.textContent).toBe("Средний");
    expect(f.count(PROJ_CREATE)).toBe(0);
    expectNoForbiddenTexts();
  });

  it("fr9_create_form_default_medium_is_sent_and_reset_to_medium_after_success", async () => {
    const created = taskItem(TID3, "Новая", { priority: "low" });
    const f = installFetch(
      taskRoutes(
        "business_admin",
        {
          [PROJ_CREATE]: () =>
            new Response(JSON.stringify(created), {
              status: 201,
              headers: { "Content-Type": "application/json" },
            }),
        },
        { perms: PERM_MANAGE },
      ),
    );
    const { container } = renderApp(`/projects/${PID}`);
    await screen.findByRole("heading", { level: 1, name: "Альфа" });
    await openTasksTab();
    await waitFor(() => expect(createForm(container)).toBeTruthy());
    const form = createForm(container)!;
    const sel = form.querySelector<HTMLSelectElement>(
      'select[name="priority"]',
    )!;
    fireEvent.change(form.querySelector('input[name="title"]')!, {
      target: { value: "Новая" },
    });
    fireEvent.change(sel, { target: { value: "low" } });
    expect(sel.value).toBe("low");
    fireEvent.submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = (await f.last(PROJ_CREATE).clone().json()) as Record<
      string,
      unknown
    >;
    expect(b.priority).toBe("low");
    await waitFor(() =>
      expect(
        createForm(container)!.querySelector<HTMLSelectElement>(
          'select[name="priority"]',
        )!.value,
      ).toBe("medium"),
    );
  });
});

describe("AC-52 / NFR-2: словарь приоритетов", () => {
  it("ac52_dictionary_has_three_priority_labels", () => {
    const dict = ru as Record<string, string>;
    expect(dict["tasks.priority.low"]).toBe("Низкий");
    expect(dict["tasks.priority.medium"]).toBe("Средний");
    expect(dict["tasks.priority.high"]).toBe("Высокий");
  });

  it("ac52_dictionary_has_no_base_key_and_no_obychnyy_value", () => {
    expect(Object.keys(ru)).not.toContain("tasks.priority.base");
    const values = Object.values(ru) as string[];
    for (const w of FORBIDDEN) expect(values).not.toContain(w);
  });
});
