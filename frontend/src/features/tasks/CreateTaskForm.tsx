// Create-task form of the project's "Tasks" tab (T83; UF-3, FR-20, FR-26, NFR-5..7).
import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { UserPicker } from "../../shared/ui/UserPicker";
import type { CreatableProject } from "../projects/api";
import { createTask, type TaskCreate, type TaskPriority } from "./api";

const PRIORITIES: readonly TaskPriority[] = ["base", "high"];

/**
 * 004/FR-12: проект страницы, если он доступен; иначе единственный доступный; иначе null.
 */
export function preselectProject(
  projects: readonly CreatableProject[],
  currentProjectId: string | null,
): string | null {
  if (currentProjectId !== null && projects.some((p) => p.id === currentProjectId)) return currentProjectId;
  const [only] = projects;
  return projects.length === 1 && only !== undefined ? only.id : null;
}

export interface CreateTaskFormProps {
  projectId: string;
  /** Only a business admin may choose an assignee (FR-9). */
  canPickAssignee: boolean;
  /** Ids the assignee may be chosen from (project members). */
  assigneeIds: readonly string[];
}

export function CreateTaskForm({ projectId, canPickAssignee, assigneeIds }: CreateTaskFormProps) {
  const baseId = useId();
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("base");
  const [assignee, setAssignee] = useState<{ id: string; login: string } | null>(null);
  // A new key empties the picker's own text field.
  const [pickerKey, setPickerKey] = useState(0);
  const [pending, setPending] = useState(false);

  function clearAssignee(): void {
    setAssignee(null);
    setPickerKey((k) => k + 1);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    const name = title.trim();
    if (name === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    const body: TaskCreate = { title: name, priority };
    if (description !== "") body.description = description;
    // The date is sent exactly as the field holds it: YYYY-MM-DD, no time zone (NFR-5).
    if (dueDate !== "") body.due_date = dueDate;
    if (canPickAssignee && assignee !== null) body.assignee_id = assignee.id;

    busy.current = true;
    setPending(true);
    alert.clear();
    void (async () => {
      try {
        await createTask(projectId, body);
        setTitle("");
        setDescription("");
        setDueDate("");
        setPriority("base");
        clearAssignee();
        titleRef.current?.focus();
        await queryClient.invalidateQueries({ queryKey: ["tasks", "project", projectId] });
      } catch (e) {
        alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
      }
      busy.current = false;
      setPending(false);
    })();
  }

  return (
    <section aria-labelledby={`${baseId}-title`}>
      <h3 id={`${baseId}-title`}>{t("tasks.create_title")}</h3>
      <ErrorAlert message={alert.message} seq={alert.seq} />
      <form data-form="create-task" onSubmit={onSubmit} noValidate aria-busy={pending ? "true" : undefined}>
        <div className="ui-field">
          <label htmlFor={`${baseId}-name`}>{t("tasks.title_label")}</label>
          <input
            id={`${baseId}-name`}
            ref={titleRef}
            type="text"
            name="title"
            autoComplete="off"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="ui-field">
          <label htmlFor={`${baseId}-description`}>{t("tasks.description_label")}</label>
          <textarea
            id={`${baseId}-description`}
            name="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="ui-field">
          <label htmlFor={`${baseId}-due`}>{t("tasks.due_label")}</label>
          <input
            id={`${baseId}-due`}
            type="date"
            name="due_date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </div>
        {canPickAssignee ? (
          <>
            <UserPicker
              key={pickerKey}
              label={t("tasks.assignee_label")}
              allowedIds={assigneeIds}
              quietError
              onSelect={(user) => setAssignee({ id: user.id, login: user.login })}
            />
            {assignee === null ? null : (
              <p>
                {t("tasks.assignee_selected")}: <strong data-field="selected-assignee">{assignee.login}</strong>{" "}
                <button type="button" data-action="clear-assignee" onClick={clearAssignee}>
                  {t("tasks.assignee_clear")}
                </button>
              </p>
            )}
          </>
        ) : null}
        <div className="ui-field">
          <label htmlFor={`${baseId}-priority`}>{t("tasks.priority_label")}</label>
          <select
            id={`${baseId}-priority`}
            name="priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as TaskPriority)}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {t(`tasks.priority.${p}`)}
              </option>
            ))}
          </select>
        </div>
        <button type="submit">{t("tasks.create_submit")}</button>
      </form>
    </section>
  );
}
