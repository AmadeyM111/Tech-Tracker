// Спека 022: метка «ИИ» на карточке и в списке.
import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { PID, T1, TID2, openTasksTab, taskItem, taskRoutes } from "./helpers";
import { card, openCard } from "./taskpage-helpers";
import { installFetch, renderApp } from "../projects/helpers";

describe("метка ИИ на карточке задачи", () => {
  it("shows_mark_next_to_title_for_last_client", async () => {
    await openCard(() => card({ last_client_name: "Claude Code" }));
    const mark = document.querySelector("[data-role=ai-mark]");
    expect(mark?.textContent).toContain(ru["tasks.ai_mark"]);
    expect(mark?.textContent).toContain("Claude Code");
    expect(document.querySelector("h1")?.contains(mark)).toBe(false);
  });

  it("shows_assignee_mark_and_hides_title_mark_after_human_edit", async () => {
    await openCard(() =>
      card({ last_client_name: null, assignee_client_name: "Claude Code" }),
    );
    const marks = document.querySelectorAll("[data-role=ai-mark]");
    expect(marks).toHaveLength(1);
    expect(document.querySelector('[data-field="assignee"] [data-role=ai-mark]')?.textContent).toContain(
      "Claude Code",
    );
  });
});

describe("метка ИИ в списке задач", () => {
  it("shows_mark_on_agent_row_only", async () => {
    const agent = taskItem(TID2, "Агент", { last_client_name: "Claude Code" });
    installFetch(taskRoutes("business_admin", {}, { items: [T1, agent] }));
    renderApp(`/projects/${PID}`);
    await openTasksTab();
    await waitFor(() => {
      const mark =
        document.querySelector(`[data-task-id="${TID2}"] [data-role=ai-mark]`) ??
        document.querySelector(`[data-card-id="${TID2}"] [data-role=ai-mark]`);
      expect(mark?.textContent).toContain("Claude Code");
    });
    expect(document.querySelector(`[data-task-id="${T1.id}"] [data-role=ai-mark]`)).toBeNull();
  });
});
