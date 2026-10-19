// Pure helper of the kanban board (T86, FR-28a, D-61): which cards are the neighbours of a
// dropped card in the target column. No DOM, no clock, no randomness.

export interface DropNeighbors {
  /** The card above the drop place (null: first in the column). */
  after_task_id: string | null;
  /** The card below the drop place (null: last in the column). */
  before_task_id: string | null;
}

/**
 * `columnTaskIds` - cards of the target column in the shown order (the moved card may be in it);
 * `targetIndex` - final index of the card in the list WITHOUT the card itself, clamped to 0..n.
 */
export function neighborsAfterDrop(
  columnTaskIds: readonly string[],
  movedId: string,
  targetIndex: number,
): DropNeighbors {
  const others = columnTaskIds.filter((id) => id !== movedId);
  const index = Math.min(Math.max(targetIndex, 0), others.length);
  return {
    after_task_id: index > 0 ? (others[index - 1] ?? null) : null,
    before_task_id: others[index] ?? null,
  };
}

export interface ColumnRect<S extends string = string> {
  status: S;
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/**
 * The drop zone is the WHOLE column (its section, not just the list of cards): the status of the
 * column whose rectangle contains the pointer (left <= x < right, top <= y < bottom), else null.
 */
export function pickDropColumn<S extends string>(
  columnRects: readonly ColumnRect<S>[],
  pointer: { x: number; y: number },
): S | null {
  for (const r of columnRects) {
    if (pointer.x >= r.left && pointer.x < r.right && pointer.y >= r.top && pointer.y < r.bottom) {
      return r.status;
    }
  }
  return null;
}

/**
 * Final index in the target column (before `neighborsAfterDrop` clamps it): in the same column
 * the index of the card under the drop; in another one - after that card when the dragged card's
 * centre is strictly below its centre, else before it. No card under the pointer (`overIndex < 0`,
 * an empty column) -> 0.
 */
export function dropIndexInColumn(
  overIndex: number,
  activeCenterY: number,
  overCenterY: number,
  sameColumn: boolean,
): number {
  if (overIndex < 0) return 0;
  if (sameColumn) return overIndex;
  return overIndex + (activeCenterY > overCenterY ? 1 : 0);
}

/**
 * Index of the card whose vertical segment [top, bottom] is nearest to `pointerY` (inside a
 * segment the distance is 0; on a tie the smaller index); an empty list -> -1.
 */
export function nearestCardIndex(
  cardRects: readonly { top: number; bottom: number }[],
  pointerY: number,
): number {
  let best = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  cardRects.forEach((r, i) => {
    const distance = pointerY < r.top ? r.top - pointerY : pointerY > r.bottom ? pointerY - r.bottom : 0;
    if (distance < bestDistance) {
      best = i;
      bestDistance = distance;
    }
  });
  return best;
}

/**
 * Neighbours of a dropped card in the FULL order of the target column when only some of its cards
 * are shown (the assignee filter, T91). `visibleIndex` is the final index in the visible list
 * without the card itself. Before the visible card X -> before = X, after = X's predecessor in the
 * full order (a hidden card may sit between); past the last visible card (or no visible ones) ->
 * the end of the full order.
 */
export function neighborsInFullOrder(
  fullIds: readonly string[],
  visibleIds: readonly string[],
  movedId: string,
  visibleIndex: number,
): DropNeighbors {
  const full = fullIds.filter((id) => id !== movedId);
  const visible = visibleIds.filter((id) => id !== movedId);
  const index = Math.min(Math.max(visibleIndex, 0), visible.length);
  const next = visible[index];
  const at = next === undefined ? -1 : full.indexOf(next);
  if (next !== undefined && at >= 0) {
    return {
      after_task_id: at > 0 ? (full[at - 1] ?? null) : null,
      before_task_id: next,
    };
  }
  return { after_task_id: full[full.length - 1] ?? null, before_task_id: null };
}

/** Index in `othersIds` (the column without the moved card) where the card lands: before `before_task_id`, else the end. */
export function insertIndexFor(othersIds: readonly string[], neighbors: DropNeighbors): number {
  if (neighbors.before_task_id === null) return othersIds.length;
  const at = othersIds.indexOf(neighbors.before_task_id);
  return at < 0 ? othersIds.length : at;
}
