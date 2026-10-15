// Subtasks of the task card (T84; UF-4, FR-19b, FR-20, FR-21, FR-22, AC-7, AC-47, NFR-6, NFR-7).
import { useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import type { AlertState } from "../../shared/ui/ErrorAlert";
import { createSubtask, type TaskDetail } from "./api";

export interface SubtaskListProps {
  task: TaskDetail;
  /** The card's single alert region: this list shows no alert of its own. */
  alert: AlertState;
  /** Called after a subtask was created: the card is re-read (subtask and progress). */
  onCreated: () => Promise<unknown>;
}

export function SubtaskList({ task, alert, onCreated }: SubtaskListProps) {
  const baseId = useId();
  const busy = useRef(false);
  const [title, setTitle] = useState("");
  const [pending, setPending] = useState(false);

  // One level only (FR-21): a subtask has no create form even with the right.
  const canCreate = task.permissions.create_subtask && task.parent_id === null;

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    const name = title.trim();
    if (name === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    busy.current = true;
    setPending(true);
    alert.clear();
    void (async () => {
      try {
        // No assignee key: the server assigns it itself (FR-20, FR-19b).
        await createSubtask(task.id, { title: name });
        setTitle("");
        await onCreated();
      } catch (e) {
        alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
      }
      busy.current = false;
      setPending(false);
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
              type="text"
              name="title"
              autoComplete="off"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <button type="submit">{t("tasks.subtask_create_submit")}</button>
        </form>
      ) : null}
    </section>
  );
}
