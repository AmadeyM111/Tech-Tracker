// Спека 022: метка «ИИ» на карточке доски по last_client_name.
import { describe, expect, it } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { TA, TB, card, cardEl, openBoard } from "./helpers";

const CARDS = {
  todo: [
    card(TA, "От агента", "todo", 0, { last_client_name: "Claude Code" }),
    card(TB, "От человека", "todo", 1),
  ],
  in_progress: [],
  review: [],
  done: [],
};

describe("метка ИИ на карточке доски", () => {
  it("shows_mark_and_client_name_for_agent_task", async () => {
    const { container } = await openBoard({}, CARDS as never);
    const mark = cardEl(container, TA)!.querySelector("[data-role=ai-mark]");
    expect(mark?.textContent).toContain(ru["tasks.ai_mark"]);
    expect(mark?.textContent).toContain("Claude Code");
  });

  it("web_task_has_no_ai_mark", async () => {
    const { container } = await openBoard({}, CARDS as never);
    expect(cardEl(container, TB)!.querySelector("[data-role=ai-mark]")).toBeNull();
  });
});
