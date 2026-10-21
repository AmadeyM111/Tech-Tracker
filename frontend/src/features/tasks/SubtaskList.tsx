// Subtasks of the task card (T84; UF-4, FR-19b, FR-20, FR-21, FR-22, AC-7, AC-47, NFR-6, NFR-7).
import { useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { FieldError } from "../../shared/ui/ErrorAlert";
import { createSubtask, type TaskDetail } from "./api";

const MAX_TITLE = 255;

export interface SubtaskListProps {
  task: TaskDetail;
  /** Called after a subtask was created: the card is re-read (subtask and progress). */
  onCreated: () => Promise<unknown>;
}

export function SubtaskList({ task, onCreated }: SubtaskListProps) {
  const baseId = useId();
  const busy = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [pending, setPending] = useState(false);
  // The form's own message, inside the "Subtasks" section (006/FR-28, D-8).
  const [message, setMessage] = useState<string | null>(null);
  const errorId = `${baseId}-error`;

  // One level only (FR-21): a subtask has no create form even with the right.
  const canCreate = task.permissions.create_subtask && task.parent_id === null;

  function fail(text: string): void {
    setMessage(text);
    inputRef.current?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    setMessage(null);
    const name = title.trim();
    if (name === "") {
      fail(t("tasks.subtask_error_title_required"));
      return;
    }
    if (name.length > MAX_TITLE) {
      fail(t("tasks.subtask_error_title_too_long"));
      return;
    }
    // busy covers the POST only: re-reading the card never blocks the next submit (FR-29).
    busy.current = true;
    setPending(true);
    void (async () => {
      let created = false;
      try {
        // No assignee key: the server assigns it itself (FR-20, FR-19b).
        await createSubtask(task.id, { title: name });
        created = true;
      } catch (e) {
        fail(errorMessage(e instanceof ApiError ? e.code : "unknown"));
      }
      busy.current = false;
      setPending(false);
      if (created) {
        setTitle("");
        setMessage(null);
        inputRef.current?.focus();
        // A re-read failure is not a creation failure: it is not shown here.
        onCreated().catch(() => undefined);
      }
    })();
  }

  return (
    <section data-section="subtasks" aria-labelledby={`${baseId}-title`}>
      <h2 id={`${baseId}-title`}>{t("tasks.subtasks_title")}</h2>
      <p>
        {t("tasks.progress_label")}{" "}
        <span data-field="progress">
          {task.progress === null ? t("tasks.progress_none") : t("tasks.progress_value", { percent: task.progress })}
        </span>
      </p>
      {task.subtasks.length === 0 ? (
        <p data-role="empty">{t("tasks.subtasks_empty")}</p>
      ) : (
        <ul>
          {task.subtasks.map((s) => (
            <li key={s.id} data-subtask-id={s.id}>
              <span data-field="title">
                <Link to={`/tasks/${s.id}`}>{s.title}</Link>
              </span>
              {" "}
              <span data-field="status">{t(`tasks.status.${s.status}`)}</span>
              {" "}
              <span data-field="assignee">{s.assignee === null ? t("tasks.assignee_none") : s.assignee.login}</span>
            </li>
          ))}
        </ul>
      )}
      {canCreate ? (
        <form data-form="create-subtask" onSubmit={onSubmit} noValidate aria-busy={pending ? "true" : undefined}>
          <div className="ui-field">
            <label htmlFor={`${baseId}-name`}>{t("tasks.subtask_title_label")}</label>
            <input
              id={`${baseId}-name`}
              ref={inputRef}
              type="text"
              name="title"
              autoComplete="off"
              aria-invalid={message !== null ? "true" : undefined}
              aria-describedby={message !== null ? errorId : undefined}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <FieldError id={errorId} message={message} />
          </div>
          <button type="submit">{t("tasks.subtask_create_submit")}</button>
        </form>
      ) : null}
    </section>
  );
}
