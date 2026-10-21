// R6-T06: прогресс 100/50/0 на фронтенде. spec 006 AC-45, AC-46, FR-30, FR-31. Код фронтенда не меняется:
// тесты фиксируют, что клиент показывает значение сервера как есть и предупреждает по статусу «не Выполнена».
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { t } from "../../../src/shared/i18n";
import { INITIAL, TA, card as boardCard, cardEl, openBoard } from "../boards/helpers";
import { PATCH, SUB1, SUB2, card, d, f_, j, openCard, setValue, statusSelect, sub, waitCount } from "./taskpage-helpers";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("AC-45: предупреждение при закрытии родителя (FR-31)", () => {
  it("ac45_done_plus_review_subtask_warns_on_closing_parent", async () => {
    const subs = [sub(SUB1, "Первая", "done"), sub(SUB2, "Вторая", "review")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 75 }), {
      [PATCH]: () => j(200, card({ status: "done", subtasks: subs, progress: 75 })),
    });
    setValue(statusSelect(), "done");
    const dlg = await screen.findByRole("alertdialog");
    expect(dlg.textContent).toContain(d("tasks.close_open_subtasks"));
    expect(f.count(PATCH)).toBe(0);
    fireEvent.click(dlg.querySelector('button[data-action="confirm"]')!);
    await waitCount(f, PATCH, 1);
  });

  it("ac45_review_only_subtask_still_warns_although_progress_is_50", async () => {
    const subs = [sub(SUB1, "Первая", "review")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 50 }), {
      [PATCH]: () => j(200, card({ status: "done", subtasks: subs, progress: 50 })),
    });
    setValue(statusSelect(), "done");
    await screen.findByRole("alertdialog");
    expect(f.count(PATCH)).toBe(0);
  });

  it("ac45_all_subtasks_done_closes_without_warning", async () => {
    const subs = [sub(SUB1, "Первая", "done"), sub(SUB2, "Вторая", "done")];
    const { f } = await openCard(() => card({ subtasks: subs, progress: 100 }), {
      [PATCH]: () => j(200, card({ status: "done", subtasks: subs, progress: 100 })),
    });
    setValue(statusSelect(), "done");
    await waitCount(f, PATCH, 1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("AC-46: показ прогресса", () => {
  it("ac46_task_card_shows_66_percent", async () => {
    const subs = [sub(SUB1, "А", "in_progress"), sub(SUB2, "Б", "review"), sub("c3c3c3c3-0000-4000-8000-000000000003", "В", "done")];
    const { container } = await openCard(() => card({ subtasks: subs, progress: 66 }));
    await waitFor(() => expect(f_(container, "progress")?.textContent).toBe("66%"));
    expect(f_(container, "progress")!.textContent).toBe(t("tasks.progress_value", { percent: 66 }));
  });

  it("ac46_task_card_without_subtasks_shows_no_subtasks_text", async () => {
    const { container } = await openCard(() => card({ subtasks: [], progress: null }));
    await waitFor(() => expect(f_(container, "progress")?.textContent).toBe("Нет подзадач"));
  });

  it("ac46_board_card_shows_66_percent_and_null_shows_no_subtasks", async () => {
    const withProgress = boardCard(TA, "Подготовить отчёт", "todo", 10, { progress: 66, subtask_count: 3 });
    const plain = boardCard("a2a2a2a2-0000-4000-8000-000000000002", "Без подзадач", "todo", 20);
    const { container } = await openBoard({}, { ...INITIAL, todo: [withProgress, plain] });
    expect(f_(cardEl(container, TA)!, "progress")!.textContent).toBe("66%");
    expect(f_(cardEl(container, plain.id)!, "progress")!.textContent).toBe("Нет подзадач");
  });
});
