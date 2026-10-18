// T91-R (2): neighborsInFullOrder / insertIndexFor. Контракт - в шапке ./helpers.tsx.
// neighborsInFullOrder(fullIds, visibleIds, movedId, visibleIndex): visibleIndex - итоговый индекс
// в видимом списке без самой карточки; перед видимой X -> before=X, after=предшественник X в полном
// порядке (может быть скрытым); за последней видимой или видимых нет -> в конец полного порядка.
import { describe, expect, it } from "vitest";

import { insertIndexFor, neighborsInFullOrder } from "../../../src/features/boards/dnd";

const N = (after: string | null, before: string | null) => ({ after_task_id: after, before_task_id: before });

describe("neighborsInFullOrder", () => {
  const full = ["A", "B", "C", "D"];
  it("filter_none_equals_plain_neighbors", () => {
    expect(neighborsInFullOrder(full, full, "M", 2)).toEqual(N("B", "C"));
  });
  it("before_first_visible_uses_hidden_predecessor", () => {
    expect(neighborsInFullOrder(full, ["C", "D"], "M", 0)).toEqual(N("B", "C"));
  });
  it("before_first_visible_that_is_first_in_full_has_no_after", () => {
    expect(neighborsInFullOrder(full, ["A", "C"], "M", 0)).toEqual(N(null, "A"));
  });
  it("between_visible_cards_uses_hidden_predecessor_of_next", () => {
    expect(neighborsInFullOrder(full, ["A", "D"], "M", 1)).toEqual(N("C", "D"));
  });
  it("after_last_visible_goes_to_full_end_even_with_hidden_after_it", () => {
    expect(neighborsInFullOrder(full, ["A", "B"], "M", 2)).toEqual(N("D", null));
  });
  it("no_visible_cards_but_hidden_ones_goes_to_full_end", () => {
    expect(neighborsInFullOrder(full, [], "M", 0)).toEqual(N("D", null));
  });
  it("empty_column_has_no_neighbors", () => {
    expect(neighborsInFullOrder([], [], "M", 0)).toEqual(N(null, null));
  });
  it("single_card_before_and_after", () => {
    expect(neighborsInFullOrder(["A"], ["A"], "M", 0)).toEqual(N(null, "A"));
    expect(neighborsInFullOrder(["A"], ["A"], "M", 1)).toEqual(N("A", null));
  });
  it("moved_card_is_excluded_from_both_lists", () => {
    expect(neighborsInFullOrder(["A", "M", "B"], ["M", "B"], "M", 0)).toEqual(N("A", "B"));
  });
  it("index_is_clamped", () => {
    expect(neighborsInFullOrder(full, ["B"], "M", -5)).toEqual(N("A", "B"));
    expect(neighborsInFullOrder(full, ["B"], "M", 99)).toEqual(N("D", null));
  });
});

describe("insertIndexFor", () => {
  it("before_neighbor_gives_its_index", () => {
    expect(insertIndexFor(["A", "B", "C"], N("A", "B"))).toBe(1);
    expect(insertIndexFor(["A", "B", "C"], N(null, "A"))).toBe(0);
  });
  it("no_before_goes_to_end", () => {
    expect(insertIndexFor(["A", "B", "C"], N("C", null))).toBe(3);
  });
  it("empty_column_gives_zero", () => {
    expect(insertIndexFor([], N(null, null))).toBe(0);
  });
  it("single_card", () => {
    expect(insertIndexFor(["A"], N(null, "A"))).toBe(0);
    expect(insertIndexFor(["A"], N("A", null))).toBe(1);
  });
  it("unknown_before_falls_back_to_end", () => {
    expect(insertIndexFor(["A", "B"], N("A", "Z"))).toBe(2);
  });
});
