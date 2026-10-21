// Task card (T84): /tasks/:taskId. UF-4, UF-6, FR-18..FR-22, FR-29 (polling), AC-7,
// AC-46, AC-47 (controls by `permissions`), NFR-6, NFR-7.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { usePolledQuery } from "../../shared/api/polling";
import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, FieldError, useAlertState } from "../../shared/ui/ErrorAlert";
import { UserPicker } from "../../shared/ui/UserPicker";
import { Comments } from "../comments/Comments";
import { listAllMembers } from "../projects/api";
import { deleteTask, getTask, updateTask, type TaskDetail, type TaskPriority, type TaskStatus, type TaskUpdate } from "./api";
import { DRAFT_FIELDS, taskDraftErrors, todayMsk, type DraftErrors, type DraftField } from "./CreateTaskForm";
import { SubtaskList } from "./SubtaskList";

const STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "review", "done"];
const PRIORITIES: readonly TaskPriority[] = ["low", "medium", "high"];
const YMD = /^(\d{4})-(\d{2})-(\d{2})/;

/** A calendar date is re-ordered as text: no Date object, so no time zone (NFR-5). */
function formatDate(value: string): string {
  const m = YMD.exec(value);
  return m === null ? value : `${m[3]}.${m[2]}.${m[1]}`;
}

const codeOf = (e: unknown): string => (e instanceof ApiError ? e.code : "unknown");

/** An id that is not a uuid is answered with 422: for the user it is "no such task". */
const loadCodeOf = (e: unknown): string => (e instanceof ApiError && e.status === 422 ? "not_found" : codeOf(e));

/** Fields of the edit form the user has changed and not saved yet (due_date: "" = cleared). */
interface Edits {
  title?: string;
  description?: string;
  due_date?: string;
  priority?: TaskPriority;
}

type Confirmation = "delete" | "close";

export function TaskPage() {
  const { taskId = "" } = useParams();
  const query = usePolledQuery({
    queryKey: ["tasks", "card", taskId],
    queryFn: ({ headers, signal }) => getTask(taskId, { headers, signal }),
  });
  if (query.data !== undefined) {
    const pollError = query.isError ? errorMessage(loadCodeOf(query.error)) : null;
    return <TaskCard key={query.data.id} task={query.data} pollError={pollError} />;
  }
  if (query.isError) {
    return (
      <section className="ui-wide">
        <ErrorAlert message={errorMessage(loadCodeOf(query.error))} />
      </section>
    );
  }
  return <p role="status">{t("admin.loading")}</p>;
}

function TaskCard({ task, pollError }: { task: TaskDetail; pollError: string | null }) {
  const baseId = useId();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const alert = useAlertState();
  const busy = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [edits, setEdits] = useState<Edits>({});
  // A new key empties the assignee picker's own text field.
  const [pickerKey, setPickerKey] = useState(0);
  // Bumped after the assignee was cleared: the effect then moves the focus to the picker (NFR-7).
  const [pickerFocus, setPickerFocus] = useState(0);
  const pickerRef = useRef<HTMLDivElement>(null);
  // 006/FR-23: messages at the fields of a top-level task; they live until the next save.
  const [fieldErrors, setFieldErrors] = useState<DraftErrors>({});
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const dueRef = useRef<HTMLInputElement>(null);

  const { permissions } = task;
  const cardKey = ["tasks", "card", task.id] as const;
  const topLevel = task.parent_id === null;

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    if (pickerFocus === 0) return;
    // The button that had the focus is gone with the assignee: the focus must not fall to <body>.
    const field = pickerRef.current?.querySelector<HTMLInputElement>("input");
    (field ?? headingRef.current)?.focus();
  }, [pickerFocus]);

  // PD-1: the parent's title only; an error here never reaches the card's alert region.
  const parentId = task.parent_id;
  const parent = useQuery({
    queryKey: ["tasks", "parent", parentId],
    queryFn: () => getTask(parentId as string),
    enabled: parentId !== null,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const members = useQuery({
    queryKey: ["tasks", "assignee-candidates", task.project.id],
    queryFn: () => listAllMembers(task.project.id),
    enabled: permissions.change_assignee,
    retry: false,
  });
  const candidateIds = (members.data ?? []).filter((m) => !m.is_blocked && m.role !== null).map((m) => m.user.id);

  /** One action at a time; the error (if any) goes to the single alert region. */
  async function run(action: () => Promise<void>): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await action();
    } catch (e) {
      const code = codeOf(e);
      // 006/FR-23: the past due date of a top-level task is shown at the due date field.
      if (code === "due_date_in_past" && topLevel) setFieldErrors({ due_date: "tasks.error_due_past" });
      else alert.show(errorMessage(code));
    }
    setConfirmation(null);
    busy.current = false;
    setPending(false);
  }

  /** Sends only the given keys; the answer becomes the card and the sent fields leave the form edits. */
  function patch(body: TaskUpdate, onDone?: () => void): Promise<void> {
    return run(async () => {
      // FR-29: a poll answer that was requested before the change must not overwrite its result.
      await queryClient.cancelQueries({ queryKey: cardKey });
      const updated = await updateTask(task.id, body);
      await queryClient.cancelQueries({ queryKey: cardKey });
      queryClient.setQueryData(cardKey, updated);
      setEdits((prev) => {
        const { title, description, due_date: due, priority, ...kept } = prev;
        return {
          ...kept,
          ...("title" in body || title === undefined ? {} : { title }),
          ...("description" in body || description === undefined ? {} : { description }),
          ...("due_date" in body || due === undefined ? {} : { due_date: due }),
          ...("priority" in body || priority === undefined ? {} : { priority }),
        };
      });
      onDone?.();
    });
  }

  const errorId = (name: DraftField): string => `${baseId}-${name}-error`;
  const invalidProps = (name: DraftField) =>
    fieldErrors[name] === undefined ? {} : { "aria-invalid": true as const, "aria-describedby": errorId(name) };
  const errorText = (name: DraftField): string | null => {
    const key = fieldErrors[name];
    return key === undefined ? null : t(key);
  };

  function onSave(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    setFieldErrors({});
    const body: TaskUpdate = {};
    if (edits.title !== undefined) {
      const name = edits.title.trim();
      if (name === "") {
        alert.show(errorMessage("validation_error"));
        return;
      }
      if (name !== task.title) body.title = name;
    }
    if (topLevel) {
      // 006/FR-23: only the changed fields are checked, so an old task without them still saves.
      const found = taskDraftErrors(
        {
          ...(edits.description !== undefined && edits.description !== task.description
            ? { description: edits.description }
            : {}),
          ...(edits.due_date !== undefined && edits.due_date !== (task.due_date ?? "")
            ? { dueDate: edits.due_date }
            : {}),
        },
        todayMsk(),
      );
      setFieldErrors(found);
      const first = DRAFT_FIELDS.find((name) => found[name] !== undefined);
      if (first === "description") descriptionRef.current?.focus();
      else if (first === "due_date") dueRef.current?.focus();
      if (first !== undefined) return;
    }
    if (edits.description !== undefined && edits.description !== task.description) {
      body.description = edits.description;
    }
    if (edits.due_date !== undefined && edits.due_date !== (task.due_date ?? "")) {
      body.due_date = edits.due_date === "" ? null : edits.due_date;
    }
    if (edits.priority !== undefined && edits.priority !== task.priority) body.priority = edits.priority;
    if (Object.keys(body).length === 0) {
      setEdits({});
      return;
    }
    void patch(body);
  }

  function onStatus(next: TaskStatus): void {
    if (next === task.status || busy.current) return;
    // FR-22 / AC-7: closing a parent with open subtasks is allowed, but only after a warning.
    if (next === "done" && task.subtasks.some((s) => s.status !== "done")) {
      setConfirmation("close");
      return;
    }
    void patch({ status: next });
  }

  function onClearAssignee(): void {
    if (busy.current) return;
    void patch({ assignee_id: null }, () => {
      setPickerKey((k) => k + 1);
      setPickerFocus((n) => n + 1);
    });
  }

  function onConfirm(): void {
    if (confirmation === "close") {
      void patch({ status: "done" });
    } else if (confirmation === "delete") {
      void run(async () => {
        await deleteTask(task.id);
        queryClient.removeQueries({ queryKey: cardKey });
        void queryClient.invalidateQueries({ queryKey: ["tasks", "project", task.project.id] });
        navigate(`/projects/${task.project.id}`);
      });
    }
  }

  const membersError = members.isError ? errorMessage(codeOf(members.error)) : null;

  const field = (name: string) => `${baseId}-${name}`;
  const label = (name: string, key: "tasks.col_status" | "tasks.col_priority" | "tasks.col_due" | "tasks.field_description") =>
    permissions.edit || (name === "status" && permissions.change_status) ? (
      <label htmlFor={field(name)}>{t(key)}</label>
    ) : (
      t(key)
    );

  const head = (
    <>
      <h1 ref={headingRef} tabIndex={-1}>
        {permissions.edit ? (
          <input
            type="text"
            name="title"
            autoComplete="off"
            aria-label={t("tasks.field_title")}
            value={edits.title ?? task.title}
            onChange={(e) => setEdits((p) => ({ ...p, title: e.target.value }))}
          />
        ) : (
          task.title
        )}
      </h1>
      <ErrorAlert message={alert.message ?? pollError ?? membersError} seq={alert.seq} />

      <dl className="ui-props">
        <dt>{label("status", "tasks.col_status")}</dt>
        <dd data-field="status">
          {permissions.change_status ? (
            <select
              id={field("status")}
              name="status"
              value={task.status}
              aria-busy={pending ? "true" : undefined}
              onChange={(e) => onStatus(e.target.value as TaskStatus)}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`tasks.status.${s}`)}
                </option>
              ))}
            </select>
          ) : (
            t(`tasks.status.${task.status}`)
          )}
        </dd>

        <dt>{label("priority", "tasks.col_priority")}</dt>
        <dd data-field="priority">
          {permissions.edit ? (
            <select
              id={field("priority")}
              name="priority"
              value={edits.priority ?? task.priority}
              onChange={(e) => setEdits((p) => ({ ...p, priority: e.target.value as TaskPriority }))}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {t(`tasks.priority.${p}`)}
                </option>
              ))}
            </select>
          ) : (
            t(`tasks.priority.${task.priority}`)
          )}
        </dd>

        <dt id={field("assignee-caption")}>{t("tasks.col_assignee")}</dt>
        <dd data-field="assignee">
          {permissions.change_assignee ? (
            <div
              ref={pickerRef}
              // Enter in the search field must not submit the edit form (the picker handles its own Enter).
              onKeyDown={(e) => {
                if (e.key === "Enter") e.preventDefault();
              }}
            >
              <span className="ui-current">{task.assignee === null ? t("tasks.assignee_none") : task.assignee.login}</span>
              <UserPicker
                key={pickerKey}
                label={t("tasks.col_assignee")}
                labelledBy={field("assignee-caption")}
                allowedIds={candidateIds}
                busy={pending}
                quietError
                onSelect={(user) => void patch({ assignee_id: user.id })}
              />
              {task.assignee === null || topLevel ? null : (
                <button type="button" data-action="clear-assignee" aria-busy={pending ? "true" : undefined} onClick={onClearAssignee}>
                  {t("tasks.assignee_clear")}
                </button>
              )}
            </div>
          ) : task.assignee === null ? (
            t("tasks.assignee_none")
          ) : (
            task.assignee.login
          )}
        </dd>

        <dt>{label("due_date", "tasks.col_due")}</dt>
        <dd data-field="due_date">
          {permissions.edit ? (
            <input
              id={field("due_date")}
              type="date"
              name="due_date"
              ref={dueRef}
              {...invalidProps("due_date")}
              value={edits.due_date ?? task.due_date ?? ""}
              onChange={(e) => setEdits((p) => ({ ...p, due_date: e.target.value }))}
            />
          ) : task.due_date === null ? (
            t("tasks.due_none")
          ) : (
            <time dateTime={task.due_date}>{formatDate(task.due_date)}</time>
          )}
          <FieldError id={errorId("due_date")} message={errorText("due_date")} />
        </dd>

        <dt>{t("tasks.col_project")}</dt>
        <dd data-field="project">
          <Link to={`/projects/${task.project.id}`}>{task.project.name}</Link>
        </dd>

        {parentId !== null && (
          <>
            <dt>{t("tasks.parent_label")}</dt>
            <dd data-field="parent">
              <Link to={`/tasks/${parentId}`}>{parent.data?.title ?? t("tasks.parent_open")}</Link>
            </dd>
          </>
        )}

        <dt>{label("description", "tasks.field_description")}</dt>
        <dd data-field="description" className="ui-pre">
          {permissions.edit ? (
            <textarea
              id={field("description")}
              name="description"
              ref={descriptionRef}
              {...invalidProps("description")}
              value={edits.description ?? task.description}
              onChange={(e) => setEdits((p) => ({ ...p, description: e.target.value }))}
            />
          ) : task.description === "" ? (
            t("tasks.description_none")
          ) : (
            task.description
          )}
          <FieldError id={errorId("description")} message={errorText("description")} />
        </dd>
      </dl>
    </>
  );

  return (
    <section className="ui-wide">
      {permissions.edit ? (
        <form data-form="edit-task" onSubmit={onSave} noValidate aria-busy={pending ? "true" : undefined}>
          {head}
          <button type="submit">{t("tasks.save")}</button>
        </form>
      ) : (
        <div>{head}</div>
      )}

      <SubtaskList
        task={task}
        onCreated={() => queryClient.invalidateQueries({ queryKey: cardKey })}
      />

      <div data-slot="comments">
        <Comments taskId={task.id} alert={alert} suppressLoadError={pollError !== null} />
      </div>

      {permissions.delete ? (
        <p>
          <button type="button" data-action="delete-task" disabled={pending} onClick={() => setConfirmation("delete")}>
            {t("tasks.delete")}
          </button>
        </p>
      ) : null}

      {confirmation === null ? null : (
        <ConfirmDialog
          title={t(confirmation === "delete" ? "tasks.delete_title" : "tasks.close_title")}
          message={
            confirmation === "delete"
              ? t("tasks.delete_message", { name: task.title })
              : t("tasks.close_open_subtasks")
          }
          pending={pending}
          onConfirm={onConfirm}
          onCancel={() => setConfirmation(null)}
        />
      )}
    </section>
  );
}
