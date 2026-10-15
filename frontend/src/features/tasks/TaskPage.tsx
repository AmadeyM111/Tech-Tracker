// Task card (T84): /tasks/:taskId. UF-4, UF-6, FR-18..FR-22, FR-29 (polling), AC-7,
// AC-46, AC-47 (controls by `permissions`), NFR-6, NFR-7.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { usePolledQuery } from "../../shared/api/polling";
import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { UserPicker } from "../../shared/ui/UserPicker";
import { listMembers, type ProjectMember } from "../projects/api";
import { deleteTask, getTask, updateTask, type TaskDetail, type TaskPriority, type TaskStatus, type TaskUpdate } from "./api";
import { SubtaskList } from "./SubtaskList";

const STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "review", "done"];
const PRIORITIES: readonly TaskPriority[] = ["base", "high"];
const MEMBERS_PAGE_SIZE = 100;
const YMD = /^(\d{4})-(\d{2})-(\d{2})/;

/** A calendar date is re-ordered as text: no Date object, so no time zone (NFR-5). */
function formatDate(value: string): string {
  const m = YMD.exec(value);
  return m === null ? value : `${m[3]}.${m[2]}.${m[1]}`;
}

const codeOf = (e: unknown): string => (e instanceof ApiError ? e.code : "unknown");

/** An id that is not a uuid is answered with 422: for the user it is "no such task". */
const loadCodeOf = (e: unknown): string => (e instanceof ApiError && e.status === 422 ? "not_found" : codeOf(e));

/** All members of the project (the assignee candidates): pages are read by `has_next`. */
async function listAllMembers(projectId: string): Promise<ProjectMember[]> {
  const all: ProjectMember[] = [];
  for (let page = 1; ; page += 1) {
    const chunk = await listMembers(projectId, { page, pageSize: MEMBERS_PAGE_SIZE });
    all.push(...chunk.items);
    if (!chunk.has_next) return all;
  }
}

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

  const { permissions } = task;
  const cardKey = ["tasks", "card", task.id] as const;

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    if (pickerFocus === 0) return;
    // The button that had the focus is gone with the assignee: the focus must not fall to <body>.
    const field = pickerRef.current?.querySelector<HTMLInputElement>("input");
    (field ?? headingRef.current)?.focus();
  }, [pickerFocus]);

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
      alert.show(errorMessage(codeOf(e)));
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

  function onSave(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    const body: TaskUpdate = {};
    if (edits.title !== undefined) {
      const name = edits.title.trim();
      if (name === "") {
        alert.show(errorMessage("validation_error"));
        return;
      }
      if (name !== task.title) body.title = name;
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

  return (
    <section className="ui-wide">
      <h1 ref={headingRef} tabIndex={-1}>{task.title}</h1>
      <ErrorAlert message={alert.message ?? pollError ?? membersError} seq={alert.seq} />

      <dl>
        <dt>{t("tasks.col_status")}</dt>
        <dd data-field="status">{t(`tasks.status.${task.status}`)}</dd>
        <dt>{t("tasks.col_priority")}</dt>
        <dd data-field="priority">{t(`tasks.priority.${task.priority}`)}</dd>
        <dt>{t("tasks.col_assignee")}</dt>
        <dd data-field="assignee">{task.assignee === null ? t("tasks.assignee_none") : task.assignee.login}</dd>
        <dt>{t("tasks.col_due")}</dt>
        <dd data-field="due_date">
          {task.due_date === null ? (
            t("tasks.due_none")
          ) : (
            <time dateTime={task.due_date}>{formatDate(task.due_date)}</time>
          )}
        </dd>
        <dt>{t("tasks.col_project")}</dt>
        <dd data-field="project">
          <Link to={`/projects/${task.project.id}`}>{task.project.name}</Link>
        </dd>
        <dt>{t("tasks.description_label")}</dt>
        <dd data-field="description" className="ui-pre">
          {task.description === "" ? t("tasks.description_none") : task.description}
        </dd>
      </dl>

      {permissions.change_status ? (
        <div className="ui-field">
          <label htmlFor={`${baseId}-status`}>{t("tasks.status_label")}</label>
          <select
            id={`${baseId}-status`}
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
        </div>
      ) : null}

      {permissions.change_assignee ? (
        <div ref={pickerRef}>
          <UserPicker
            key={pickerKey}
            label={t("tasks.assignee_label")}
            allowedIds={candidateIds}
            busy={pending}
            quietError
            onSelect={(user) => void patch({ assignee_id: user.id })}
          />
          {task.assignee === null ? null : (
            <button type="button" data-action="clear-assignee" aria-busy={pending ? "true" : undefined} onClick={onClearAssignee}>
              {t("tasks.assignee_clear")}
            </button>
          )}
        </div>
      ) : null}

      {permissions.edit ? (
        <section aria-labelledby={`${baseId}-edit`}>
          <h2 id={`${baseId}-edit`}>{t("tasks.edit_title")}</h2>
          <form data-form="edit-task" onSubmit={onSave} noValidate aria-busy={pending ? "true" : undefined}>
            <div className="ui-field">
              <label htmlFor={`${baseId}-title`}>{t("tasks.title_label")}</label>
              <input
                id={`${baseId}-title`}
                type="text"
                name="title"
                autoComplete="off"
                value={edits.title ?? task.title}
                onChange={(e) => setEdits((p) => ({ ...p, title: e.target.value }))}
              />
            </div>
            <div className="ui-field">
              <label htmlFor={`${baseId}-description`}>{t("tasks.description_label")}</label>
              <textarea
                id={`${baseId}-description`}
                name="description"
                value={edits.description ?? task.description}
                onChange={(e) => setEdits((p) => ({ ...p, description: e.target.value }))}
              />
            </div>
            <div className="ui-field">
              <label htmlFor={`${baseId}-due`}>{t("tasks.due_label")}</label>
              <input
                id={`${baseId}-due`}
                type="date"
                name="due_date"
                value={edits.due_date ?? task.due_date ?? ""}
                onChange={(e) => setEdits((p) => ({ ...p, due_date: e.target.value }))}
              />
            </div>
            <div className="ui-field">
              <label htmlFor={`${baseId}-priority`}>{t("tasks.priority_label")}</label>
              <select
                id={`${baseId}-priority`}
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
            </div>
            <button type="submit">{t("tasks.save")}</button>
          </form>
        </section>
      ) : null}

      <SubtaskList
        task={task}
        alert={alert}
        onCreated={() => queryClient.invalidateQueries({ queryKey: cardKey })}
      />

      {/* Comments (T85) are mounted here. */}
      <div data-slot="comments" />

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
