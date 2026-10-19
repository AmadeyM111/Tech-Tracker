// T86: чистая функция соседей после сброса карточки.
// AC: FR-28a (клиент передаёт соседей), D-61.
// Контракт: columnTaskIds - id карточек ЦЕЛЕВОЙ колонки в показанном порядке (movedId может
// входить в список - перенос внутри колонки); targetIndex - итоговая позиция карточки в колонке
// после переноса (0..n), считается в списке БЕЗ самой карточки; вне диапазона - прижимается.
// Результат: after_task_id - сосед сверху, before_task_id - снизу; нет соседа - null.
import { describe, expect, it } from "vitest";

import { dropIndexInColumn, neighborsAfterDrop, nearestCardIndex, pickDropColumn } from "../../../src/features/boards/dnd";

describe("neighborsAfterDrop", () => {
  it("fr28a_empty_column_has_no_neighbors", () => {
    expect(neighborsAfterDrop([], "M", 0)).toEqual({ after_task_id: null, before_task_id: null });
  });

  it("fr28a_drop_at_start_has_only_lower_neighbor", () => {
    expect(neighborsAfterDrop(["A", "B", "C"], "M", 0)).toEqual({
      after_task_id: null,
      before_task_id: "A",
    });
  });

  it("fr28a_drop_in_middle_has_both_neighbors", () => {
    expect(neighborsAfterDrop(["A", "B", "C"], "M", 1)).toEqual({
      after_task_id: "A",
      before_task_id: "B",
    });
  });

  it("fr28a_drop_at_end_has_only_upper_neighbor", () => {
    expect(neighborsAfterDrop(["A", "B", "C"], "M", 3)).toEqual({
      after_task_id: "C",
      before_task_id: null,
    });
  });

  it("fr28a_move_within_column_down_excludes_card_itself", () => {
    // [A,B,C], B -> итоговый индекс 2: порядок A,C,B
    expect(neighborsAfterDrop(["A", "B", "C"], "B", 2)).toEqual({
      after_task_id: "C",
      before_task_id: null,
    });
  });

  it("fr28a_move_within_column_up_excludes_card_itself", () => {
    // [A,B,C], C -> индекс 0: порядок C,A,B
    expect(neighborsAfterDrop(["A", "B", "C"], "C", 0)).toEqual({
      after_task_id: null,
      before_task_id: "A",
    });
  });

  it("fr28a_move_within_column_to_same_place_skips_self_as_neighbor", () => {
    expect(neighborsAfterDrop(["A", "B", "C"], "B", 1)).toEqual({
      after_task_id: "A",
      before_task_id: "C",
    });
  });

  it("fr28a_single_card_column_moved_onto_itself_has_no_neighbors", () => {
    expect(neighborsAfterDrop(["M"], "M", 0)).toEqual({ after_task_id: null, before_task_id: null });
  });

  it("fr28a_single_other_card_before_and_after", () => {
    expect(neighborsAfterDrop(["A"], "M", 0)).toEqual({ after_task_id: null, before_task_id: "A" });
    expect(neighborsAfterDrop(["A"], "M", 1)).toEqual({ after_task_id: "A", before_task_id: null });
  });

  it("fr28a_target_index_out_of_range_is_clamped", () => {
    expect(neighborsAfterDrop(["A", "B"], "M", 99)).toEqual({ after_task_id: "B", before_task_id: null });
    expect(neighborsAfterDrop(["A", "B"], "M", -3)).toEqual({ after_task_id: null, before_task_id: "A" });
  });

  it("fr28a_does_not_mutate_input", () => {
    const col = ["A", "B", "C"];
    neighborsAfterDrop(col, "B", 0);
    expect(col).toEqual(["A", "B", "C"]);
  });
});

const RECTS = [
  { status: "todo", left: 0, top: 0, right: 280, bottom: 600 },
  { status: "in_progress", left: 300, top: 0, right: 580, bottom: 600 },
  { status: "review", left: 600, top: 0, right: 880, bottom: 600 },
  { status: "done", left: 900, top: 0, right: 1180, bottom: 600 },
];

describe("pickDropColumn (B2)", () => {
  it("b2_pointer_in_lower_part_of_empty_column_hits_that_column", () => {
    expect(pickDropColumn(RECTS, { x: 700, y: 450 })).toBe("review");
  });

  it("b2_pointer_hits_the_column_under_it_regardless_of_neighbours", () => {
    expect(pickDropColumn(RECTS, { x: 400, y: 450 })).toBe("in_progress");
    expect(pickDropColumn(RECTS, { x: 10, y: 5 })).toBe("todo");
    expect(pickDropColumn(RECTS, { x: 1000, y: 599 })).toBe("done");
  });

  it("b2_pointer_in_gap_or_outside_is_null", () => {
    expect(pickDropColumn(RECTS, { x: 290, y: 100 })).toBeNull();
    expect(pickDropColumn(RECTS, { x: 700, y: 700 })).toBeNull();
    expect(pickDropColumn([], { x: 1, y: 1 })).toBeNull();
  });
});

describe("dropIndexInColumn (B3)", () => {
  it("b3_same_column_keeps_over_index", () => {
    expect(dropIndexInColumn(2, 500, 10, true)).toBe(2);
    expect(dropIndexInColumn(0, 0, 500, true)).toBe(0);
  });

  it("b3_other_column_above_over_center_goes_before_over", () => {
    expect(dropIndexInColumn(1, 50, 100, false)).toBe(1);
  });

  it("b3_other_column_below_over_center_goes_after_over", () => {
    expect(dropIndexInColumn(1, 150, 100, false)).toBe(2);
  });

  it("b3_exactly_at_center_goes_before_over", () => {
    expect(dropIndexInColumn(1, 100, 100, false)).toBe(1);
  });

  it("b3_single_card_column", () => {
    expect(dropIndexInColumn(0, 10, 65, false)).toBe(0);
    expect(dropIndexInColumn(0, 90, 65, false)).toBe(1);
  });

  it("b3_empty_column_without_over_card_is_zero", () => {
    expect(dropIndexInColumn(-1, 300, 0, false)).toBe(0);
  });
});

describe("pickDropColumn boundaries (M1/M2)", () => {
  it("m1_right_edge_is_exclusive", () => {
    expect(pickDropColumn(RECTS, { x: 280, y: 100 })).toBeNull();
  });

  it("m1_top_left_corner_is_inclusive", () => {
    expect(pickDropColumn(RECTS, { x: 0, y: 0 })).toBe("todo");
  });

  it("m2_bottom_edge_is_exclusive_and_left_edge_of_next_column_is_gap", () => {
    expect(pickDropColumn(RECTS, { x: 300, y: 600 })).toBeNull();
    expect(pickDropColumn(RECTS, { x: 300, y: 599 })).toBe("in_progress");
  });
});

describe("nearestCardIndex (R2)", () => {
  const cards = [
    { top: 40, bottom: 90 },
    { top: 100, bottom: 150 },
    { top: 160, bottom: 210 },
  ];

  it("r2_inside_card_returns_it", () => {
    expect(nearestCardIndex(cards, 120)).toBe(1);
  });

  it("r2_gap_returns_nearer_card", () => {
    expect(nearestCardIndex(cards, 96)).toBe(1);
    expect(nearestCardIndex(cards, 94)).toBe(0);
  });

  it("r2_gap_tie_returns_earlier_card", () => {
    expect(nearestCardIndex(cards, 95)).toBe(0);
  });

  it("r2_heading_above_all_returns_first_and_below_all_returns_last", () => {
    expect(nearestCardIndex(cards, 10)).toBe(0);
    expect(nearestCardIndex(cards, 450)).toBe(2);
  });

  it("r2_empty_list_returns_minus_one", () => {
    expect(nearestCardIndex([], 100)).toBe(-1);
  });
});
