// «Горит» на карточке доски (spec 008 FR-8): метка берётся из поля `hot` (тот же критерий, что на «Сводке»).
// Текст виден без цвета; метка не появляется, если сервер не отметил задачу.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { TA, TB, cardEl, card, openBoard } from "./helpers";

const HOT_CARDS = {
  todo: [card(TA, "Горящая", "todo", 0, { priority: "high", due_date: "2026-11-13", hot: true }), card(TB, "Обычная", "todo", 1, { hot: false })],
  in_progress: [],
  review: [],
  done: [],
};

describe("«Горит» на карточке доски", () => {
  it("hot_card_shows_the_text_mark_inside_the_card", async () => {
    const { container } = await openBoard({}, HOT_CARDS as never);
    const hot = cardEl(container, TA)!.querySelectorAll('[data-role="hot-mark"]');
    expect(hot).toHaveLength(1);
    expect(hot[0]!.textContent).toBe(ru["summary.hot"]);
  });

  it("card_without_hot_has_no_mark", async () => {
    const { container } = await openBoard({}, HOT_CARDS as never);
    expect(cardEl(container, TB)!.querySelector('[data-role="hot-mark"]')).toBeNull();
    expect(screen.getAllByText(ru["summary.hot"])).toHaveLength(1);
  });
});
