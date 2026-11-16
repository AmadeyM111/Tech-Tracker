// «Блокер» на карточке доски (spec 033): метка из поля `blocked`, отдельно от «Горит».
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { TA, TB, card, cardEl, openBoard } from "./helpers";

const CARDS = {
  todo: [
    card(TA, "Инцидент", "todo", 0, { blocked: true }),
    card(TB, "Обычная", "todo", 1, { blocked: false }),
  ],
  in_progress: [],
  review: [],
  done: [],
};

describe("«Блокер» на карточке доски", () => {
  it("blocked_card_shows_the_text_mark_inside_the_card", async () => {
    const { container } = await openBoard({}, CARDS as never);
    const mark = cardEl(container, TA)!.querySelectorAll('[data-role="blocker-mark"]');
    expect(mark).toHaveLength(1);
    expect(mark[0]!.textContent).toBe(ru["summary.blocker"]);
  });

  it("card_without_blocker_has_no_mark", async () => {
    const { container } = await openBoard({}, CARDS as never);
    expect(cardEl(container, TB)!.querySelector('[data-role="blocker-mark"]')).toBeNull();
    expect(screen.getAllByText(ru["summary.blocker"])).toHaveLength(1);
  });
});
