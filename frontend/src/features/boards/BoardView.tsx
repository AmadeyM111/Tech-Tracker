// Kanban board: content of the project's "Board" tab (T86).
// UF-5, FR-18a, FR-28, FR-28a (the client sends the neighbours), FR-29 (polling),
// FR-19b (a refused move is rolled back with a message), AC-97 (keyboard), NFR-5..7, D-61.
// T91: create a task from a column, optimistic move, client-side assignee filter.
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  pointerWithin,
  useDroppable,
  useSensor,
  useSensors,
  type Announcements,
  type ClientRect,
  type CollisionDetection,
  type DragEndEvent,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS, type Coordinates } from "@dnd-kit/utilities";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import type { TaskStatus } from "../tasks/api";
import { createTask, getBoard, moveTask, type Board, type BoardCard, type BoardColumn } from "./api";
import { dropIndexInColumn, insertIndexFor, nearestCardIndex, neighborsInFullOrder, pickDropColumn } from "./dnd";

const YMD = /^(\d{4})-(\d{2})-(\d{2})/;

/** A calendar date is re-ordered as text: no Date object, so no time zone (NFR-5). */
function formatDate(value: string): string {
  const m = YMD.exec(value);
  return m === null ? value : `${m[3]}.${m[2]}.${m[1]}`;
}

function codeOf(e: unknown): string {
  const code = (e as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : "unknown";
}

/** Data attached to the draggable cards and to the column drop areas. */
interface DropData {
  kind: "card" | "column";
  status: TaskStatus;
}

const columnDropId = (status: TaskStatus) => `column:${status}`;

function dropDataOf(value: unknown): DropData | null {
  const d = value as Partial<DropData> | null | undefined;
  if (d === null || d === undefined) return null;
  if ((d.kind !== "card" && d.kind !== "column") || d.status === undefined) return null;
  return { kind: d.kind, status: d.status };
}

const statusTitle = (status: TaskStatus) => t(`tasks.status.${status}`);

/** What the last collision pass saw: the pointer and the rectangles measured for the drag. */
interface DragGeometry {
  pointer: Coordinates | null;
  rects: ReadonlyMap<UniqueIdentifier, ClientRect>;
}

/**
 * Pointer: the card under it, else the column under it (the whole section, B2); keyboard (no
 * pointer) and a pointer outside every column: the closest corners. The geometry is remembered
 * for the drop (the place inside a column is decided from the pointer and the card rectangles).
 */
function makeCollisionDetection(): {
  detect: CollisionDetection;
  geometry: () => DragGeometry;
} {
  let last: DragGeometry = { pointer: null, rects: new Map() };
  const detect: CollisionDetection = (args) => {
    const { pointerCoordinates, droppableContainers, droppableRects } = args;
    last = { pointer: pointerCoordinates, rects: droppableRects };
    if (pointerCoordinates !== null) {
      const cards = droppableContainers.filter((c) => dropDataOf(c.data.current)?.kind === "card");
      const onCard = pointerWithin({ ...args, droppableContainers: cards });
      if (onCard.length > 0) return onCard;
      const rects: {
        status: TaskStatus;
        left: number;
        top: number;
        right: number;
        bottom: number;
      }[] = [];
      for (const c of droppableContainers) {
        const data = dropDataOf(c.data.current);
        const r = droppableRects.get(c.id);
        if (data?.kind === "column" && r !== undefined) {
          rects.push({
            status: data.status,
            left: r.left,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
          });
        }
      }
      const status = pickDropColumn(rects, pointerCoordinates);
      if (status !== null) return [{ id: columnDropId(status) }];
    }
    return closestCorners(args);
  };
  return { detect, geometry: () => last };
}

function Card({ card }: { card: BoardCard }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: card.id,
    data: { kind: "card", status: card.status } satisfies DropData,
    attributes: { roleDescription: t("boards.card_roledescription") },
  });
  // The card is a list item with a link inside: a "button" role would nest interactive content.
  const { role: _role, "aria-pressed": _pressed, "aria-disabled": _disabled, ...a11y } = attributes;
  void _role;
  void _pressed;
  void _disabled;
  return (
    <li
      ref={(el) => {
        setNodeRef(el);
        // The card itself is the activator: Enter/Space on the link inside does not pick it up (B1).
        setActivatorNodeRef(el);
      }}
      data-task-id={card.id}
      {...a11y}
      {...listeners}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
      }}
    >
      <div data-field="title">
        {/* No pointer events while dragging: the click after pointerup must not navigate. */}
        <Link to={`/tasks/${card.id}`} style={isDragging ? { pointerEvents: "none" } : undefined}>
          {card.title}
        </Link>
      </div>
      <div data-field="priority">{t(`tasks.priority.${card.priority}`)}</div>
      <div data-field="due_date">
        {card.due_date === null ? (
          t("tasks.due_none")
        ) : (
          <time dateTime={card.due_date}>{formatDate(card.due_date)}</time>
        )}
      </div>
      <div data-field="assignee">{card.assignee === null ? t("tasks.assignee_none") : card.assignee.login}</div>
      <div data-field="progress">
        {card.progress === null ? t("tasks.progress_none") : t("tasks.progress_value", { percent: card.progress })}
      </div>
    </li>
  );
}

/** What happened to a create request: nothing created / created but not moved / all done. */
type CreateResult = "failed" | "created" | "ok";

function CreateTask({
  status,
  onCreate,
  onInvalid,
}: {
  status: TaskStatus;
  onCreate: (status: TaskStatus, title: string) => Promise<CreateResult>;
  onInvalid: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const sending = useRef(false);
  const restoreFocus = useRef(false);
  const inputId = useId();

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    } else if (restoreFocus.current) {
      restoreFocus.current = false;
      addRef.current?.focus();
    }
  }, [open]);

  function close(focusButton: boolean): void {
    restoreFocus.current = focusButton;
    setOpen(false);
    setTitle("");
  }

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (sending.current) return;
    const trimmed = title.trim();
    if (trimmed === "") {
      onInvalid();
      return;
    }
    sending.current = true;
    try {
      const result = await onCreate(status, trimmed);
      if (result !== "failed") close(result === "ok");
    } finally {
      sending.current = false;
    }
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    }
  }

  if (!open) {
    return (
      <button type="button" data-action="add-task" className="ui-add-task" ref={addRef} onClick={() => setOpen(true)}>
        {t("boards.add_task")}
      </button>
    );
  }
  return (
    <form
      data-form="board-create-task"
      className="ui-create-form"
      aria-label={t("boards.create_form_label", {
        status: statusTitle(status),
      })}
      onSubmit={(e) => void submit(e)}
      onKeyDown={onKeyDown}
      noValidate
    >
      <label htmlFor={inputId}>{t("boards.create_title_label")}</label>
      <input
        id={inputId}
        name="title"
        type="text"
        ref={inputRef}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <div className="ui-create-form-actions">
        <button type="submit">{t("boards.create_submit")}</button>
        <button type="button" data-action="cancel-create" onClick={() => close(true)}>
          {t("boards.create_cancel")}
        </button>
      </div>
    </form>
  );
}

function Column({
  status,
  cards,
  canCreate,
  onCreate,
  onInvalid,
}: {
  status: TaskStatus;
  cards: readonly BoardCard[];
  canCreate: boolean;
  onCreate: (status: TaskStatus, title: string) => Promise<CreateResult>;
  onInvalid: () => void;
}) {
  const headingId = useId();
  // The drop zone is the whole section, not only the list of cards (B2).
  const { setNodeRef } = useDroppable({
    id: columnDropId(status),
    data: { kind: "column", status } satisfies DropData,
  });
  return (
    <section ref={setNodeRef} data-column={status} aria-labelledby={headingId}>
      <h3 id={headingId}>{statusTitle(status)}</h3>
      <SortableContext id={status} items={cards.map((c) => c.id)} strategy={verticalListSortingStrategy}>
        <ul
          data-role="column-cards"
          aria-label={t("boards.column_label", { status: statusTitle(status) })}
          className="ui-column-cards"
        >
          {cards.length === 0 ? <li data-role="empty">{t("boards.empty_column")}</li> : null}
          {cards.map((card) => (
            <Card key={card.id} card={card} />
          ))}
        </ul>
      </SortableContext>
      {canCreate ? <CreateTask status={status} onCreate={onCreate} onInvalid={onInvalid} /> : null}
    </section>
  );
}

/** The columns after the card is moved to `status` before `neighbors.before_task_id` (else to the end). */
function applyMove(
  columns: readonly BoardColumn[],
  card: BoardCard,
  status: TaskStatus,
  neighbors: { after_task_id: string | null; before_task_id: string | null },
): BoardColumn[] {
  return columns.map((column) => {
    const rest = column.tasks.filter((x) => x.id !== card.id);
    if (column.status !== status) return { ...column, tasks: rest };
    const at = insertIndexFor(
      rest.map((x) => x.id),
      neighbors,
    );
    return {
      ...column,
      tasks: [...rest.slice(0, at), { ...card, status }, ...rest.slice(at)],
    };
  });
}

export function BoardView({ projectId, canCreate = false }: { projectId: string; canCreate?: boolean }) {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const rootRef = useRef<HTMLDivElement>(null);
  const focusId = useRef<string | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  // Columns as they were when the card was picked up: a poll answer does not shuffle the board
  // under the dragged card.
  const [frozen, setFrozen] = useState<BoardColumn[] | null>(null);
  // The board as the user expects it while a move request is in flight (T91): a poll answer
  // does not overwrite it; it is dropped when the request is answered and the board re-read.
  const [optimistic, setOptimistic] = useState<BoardColumn[] | null>(null);
  // Assignee filter: "" = all, "none" = unassigned, otherwise a user id. Component state only.
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const filterId = useId();
  // A move request is in flight: a second drop is ignored until it is answered.
  const moving = useRef(false);
  const [{ detect: collisionDetection, geometry }] = useState(makeCollisionDetection);
  const queryKey = ["board", projectId] as const;

  const board = usePolledQuery({
    queryKey,
    queryFn: ({ headers, signal }) => getBoard(projectId, { headers, signal }),
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const columns = frozen ?? optimistic ?? board.data?.columns;
  const assignees = useMemo(() => {
    const byId = new Map<string, string>();
    for (const column of columns ?? []) {
      for (const card of column.tasks) if (card.assignee !== null) byId.set(card.assignee.id, card.assignee.login);
    }
    return Array.from(byId, ([id, login]) => ({ id, login })).sort((a, b) =>
      a.login < b.login ? -1 : a.login > b.login ? 1 : 0,
    );
  }, [columns]);
  // A filtered-for user who has no cards any more is not an option: the filter acts as "all".
  const filter =
    assigneeFilter === "" || assigneeFilter === "none" || assignees.some((a) => a.id === assigneeFilter)
      ? assigneeFilter
      : "";
  const shown = useMemo(() => {
    if (columns === undefined || filter === "") return columns;
    const keep = (card: BoardCard) => (filter === "none" ? card.assignee === null : card.assignee?.id === filter);
    return columns.map((c) => ({ ...c, tasks: c.tasks.filter(keep) }));
  }, [columns, filter]);
  const cardsById = useMemo(() => {
    const map = new Map<string, BoardCard>();
    for (const column of columns ?? []) for (const card of column.tasks) map.set(card.id, card);
    return map;
  }, [columns]);

  // The focus stays on the card that was moved, also when it was re-created in another column.
  useEffect(() => {
    const id = focusId.current;
    if (id === null) return;
    focusId.current = null;
    const root = rootRef.current;
    if (root === null) return;
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("[data-task-id]"))) {
      if (el.dataset.taskId === id) {
        el.focus();
        return;
      }
    }
  }, [focusTick]);

  const titleOf = (id: unknown) => cardsById.get(String(id))?.title ?? "";

  const announcements: Announcements = {
    onDragStart: ({ active }) => t("boards.announce_pickup", { title: titleOf(active.id) }),
    onDragOver: ({ active, over }) => {
      // Over itself (the pickup, the same place): only the title was announced at the pickup.
      if (over === null || over.id === active.id) return undefined;
      const data = dropDataOf(over.data.current);
      return data?.kind === "column"
        ? t("boards.announce_over_column", {
            title: titleOf(active.id),
            status: statusTitle(data.status),
          })
        : t("boards.announce_over_card", {
            title: titleOf(active.id),
            over: titleOf(over.id),
          });
    },
    onDragEnd: ({ active, over }) => {
      if (over === null) return t("boards.announce_cancel", { title: titleOf(active.id) });
      if (over.id === active.id) return t("boards.announce_drop_same", { title: titleOf(active.id) });
      const data = dropDataOf(over.data.current);
      return data?.kind === "column"
        ? t("boards.announce_drop_column", {
            title: titleOf(active.id),
            status: statusTitle(data.status),
          })
        : t("boards.announce_drop_card", {
            title: titleOf(active.id),
            over: titleOf(over.id),
          });
    },
    onDragCancel: ({ active }) => t("boards.announce_cancel", { title: titleOf(active.id) }),
  };

  /** Target column and the final index of the card in it (list without the card itself). */
  function dropPlace(event: DragEndEvent): { status: TaskStatus; index: number } | null {
    const { active, over } = event;
    if (over === null) return null;
    const movedId = String(active.id);
    const source = cardsById.get(movedId);
    const data = dropDataOf(over.data.current);
    if (source === undefined || data === null) return null;
    const ids = (shown ?? []).filter((c) => c.status === data.status).flatMap((c) => c.tasks.map((x) => x.id));
    const others = ids.filter((id) => id !== movedId);
    const moved = active.rect.current.translated;
    const activeCenter = moved === null ? Number.NEGATIVE_INFINITY : moved.top + moved.height / 2;
    if (data.kind === "column") {
      // Inside a column, not on a card (gap, heading, below the last card): by the nearest card.
      const { pointer, rects: all } = geometry();
      const rects = others.map((id) => all.get(id));
      const known = rects.filter((r): r is ClientRect => r !== undefined);
      const first = known[0];
      const last = known[known.length - 1];
      if (first === undefined || last === undefined || known.length !== others.length) {
        return { status: data.status, index: others.length };
      }
      const pointerY = pointer?.y ?? activeCenter;
      if (pointerY < first.top) return { status: data.status, index: 0 };
      if (pointerY >= last.bottom) return { status: data.status, index: others.length };
      const nearest = nearestCardIndex(known, pointerY);
      const near = known[nearest];
      if (near === undefined) return { status: data.status, index: others.length };
      const nearCenter = near.top + near.height / 2;
      // `others` has no moved card: the "other column" rule puts it before / after the nearest, by the
      // pointer against its centre (the keyboard has no pointer: `pointerY` is `activeCenter`).
      return {
        status: data.status,
        index: dropIndexInColumn(nearest, pointerY, nearCenter, false),
      };
    }
    const overIndex = ids.indexOf(String(over.id));
    if (overIndex < 0) return null;
    if (data.status === source.status) return { status: data.status, index: overIndex };
    const overCenter = over.rect.top + over.rect.height / 2;
    return {
      status: data.status,
      index: dropIndexInColumn(overIndex, activeCenter, overCenter, false),
    };
  }

  async function onDragEnd(event: DragEndEvent): Promise<void> {
    setFrozen(null);
    const place = dropPlace(event);
    if (place === null) return;
    const movedId = String(event.active.id);
    const source = cardsById.get(movedId);
    if (source === undefined) return;
    const visibleIds = (shown ?? []).filter((c) => c.status === place.status).flatMap((c) => c.tasks.map((x) => x.id));
    const fullIds = (columns ?? []).filter((c) => c.status === place.status).flatMap((c) => c.tasks.map((x) => x.id));
    const others = visibleIds.filter((id) => id !== movedId);
    const index = Math.min(Math.max(place.index, 0), others.length);
    // Same column, same place: nothing to send.
    if (place.status === source.status && index === visibleIds.indexOf(movedId)) return;
    // The previous move is not answered yet: no second request, the user is told so.
    if (moving.current) {
      alert.show(t("boards.move_busy"));
      return;
    }
    // The neighbours come from the FULL order of the column, not from the filtered one.
    const neighbors = neighborsInFullOrder(fullIds, visibleIds, movedId, index);
    alert.clear();
    focusId.current = movedId;
    moving.current = true;
    // The card is already where the user dropped it; a stale read in flight must not land over it.
    void queryClient.cancelQueries({ queryKey });
    const previous = queryClient.getQueryData<Board>(queryKey);
    const moved = applyMove(columns ?? [], source, place.status, neighbors);
    // The cache holds the new order too: when the override is dropped the screen does not flash the old one.
    if (previous !== undefined) queryClient.setQueryData<Board>(queryKey, { ...previous, columns: moved });
    setOptimistic(moved);
    setFocusTick((n) => n + 1);
    try {
      try {
        await moveTask(movedId, { status: place.status, ...neighbors });
        // A "busy" notice shown meanwhile is stale now.
        alert.clear();
      } catch (e) {
        alert.show(errorMessage(codeOf(e)));
        // Rolled back at once, the re-read below brings the server's own order.
        if (previous !== undefined) queryClient.setQueryData<Board>(queryKey, previous);
      }
      // Success or not, the screen shows what the server has (FR-19b).
      await queryClient.invalidateQueries({ queryKey });
    } finally {
      moving.current = false;
      setOptimistic(null);
      // The first restore (right after the optimistic render) may have been taken over by an alert.
      focusId.current = movedId;
      setFocusTick((n) => n + 1);
    }
  }

  /** Creates a task in the column; for a column other than "todo" moves it there (no neighbours: the end). */
  async function onCreate(status: TaskStatus, title: string): Promise<CreateResult> {
    alert.clear();
    let id: string;
    try {
      id = (await createTask(projectId, title)).id;
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
      return "failed";
    }
    let result: CreateResult = "ok";
    if (status !== "todo") {
      try {
        await moveTask(id, { status });
      } catch (e) {
        alert.show(errorMessage(codeOf(e)));
        result = "created";
      }
    }
    await queryClient.invalidateQueries({ queryKey });
    return result;
  }

  const loadError = board.isError ? errorMessage(codeOf(board.error)) : null;

  return (
    <div data-role="board" ref={rootRef}>
      <ErrorAlert message={alert.message ?? loadError} seq={alert.seq} />
      {columns === undefined ? (
        board.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : (
        <>
          <div className="ui-board-filter">
            <label htmlFor={filterId}>{t("boards.filter_label")}</label>
            <select
              id={filterId}
              name="board-assignee"
              value={filter}
              onChange={(e) => setAssigneeFilter(e.target.value)}
            >
              <option value="">{t("boards.filter_all")}</option>
              <option value="none">{t("boards.filter_none")}</option>
              {assignees.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.login}
                </option>
              ))}
            </select>
          </div>
          <DndContext
            sensors={sensors}
            collisionDetection={collisionDetection}
            accessibility={{
              announcements,
              screenReaderInstructions: {
                draggable: t("boards.dnd_instructions"),
              },
            }}
            onDragStart={() => setFrozen(columns ?? null)}
            onDragCancel={() => setFrozen(null)}
            onDragEnd={(event) => void onDragEnd(event)}
          >
            <div className="ui-board-grid">
              {(shown ?? columns).map((column) => (
                <Column
                  key={column.status}
                  status={column.status}
                  cards={column.tasks}
                  canCreate={canCreate}
                  onCreate={onCreate}
                  onInvalid={() => alert.show(errorMessage("validation_error"))}
                />
              ))}
            </div>
          </DndContext>
        </>
      )}
    </div>
  );
}
