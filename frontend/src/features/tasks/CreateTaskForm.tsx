// Create-task form of the project's "Tasks" tab (T83; UF-3, FR-20, FR-26, NFR-5..7).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ErrorAlert, FieldError, useAlertState } from "../../shared/ui/ErrorAlert";
import { UserPicker } from "../../shared/ui/UserPicker";
import { listAllMembers, listCreatableProjects, type CreatableProject } from "../projects/api";
import { createTask, type TaskCreate, type TaskCreateInput, type TaskDetail, type TaskPriority } from "./api";

const PRIORITIES: readonly TaskPriority[] = ["low", "medium", "high"];

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

/** 006/D-11: «сегодня» по Europe/Moscow, YYYY-MM-DD; не зависит от пояса браузера. */
export function todayMsk(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: string): string => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export type DraftField = "title" | "description" | "due_date" | "assignee";
/** Порядок полей в формах: первое неверное получает фокус (FR-19). */
export const DRAFT_FIELDS: readonly DraftField[] = ["title", "description", "due_date", "assignee"];
export type DraftErrors = Partial<Record<DraftField, MessageKey>>;

/**
 * 006/FR-19, FR-23. Проверяет только переданные ключи; срок сравнивается со строкой today
 * (YYYY-MM-DD); assigneeId undefined не проверяется, null — ошибка.
 */
export function taskDraftErrors(
  draft: { title?: string; description?: string; dueDate?: string; assigneeId?: string | null },
  today: string,
): DraftErrors {
  const errors: DraftErrors = {};
  if (draft.title !== undefined && draft.title.trim() === "") errors.title = "tasks.error_title_required";
  if (draft.description !== undefined && draft.description.trim() === "") {
    errors.description = "tasks.error_description_required";
  }
  if (draft.dueDate !== undefined) {
    if (draft.dueDate === "") errors.due_date = "tasks.error_due_required";
    else if (draft.dueDate < today) errors.due_date = "tasks.error_due_past";
  }
  if (draft.assigneeId === null) errors.assignee = "tasks.error_assignee_required";
  return errors;
}

export interface CreateTaskFormProps {
  projectId: string;
  /** Only a business admin may choose an assignee (FR-9). */
  canPickAssignee: boolean;
  /** Ids the assignee may be chosen from (project members). */
  assigneeIds: readonly string[];
  /** 006/FR-19: исполнитель по умолчанию; строка «Исполнитель: <логин>» у «Пользователя». */
  currentUser: { id: string; login: string };
}

function RequiredMark() {
  return (
    <span className="ui-required" aria-hidden="true">
      {t("tasks.required_mark")}
    </span>
  );
}

export function CreateTaskForm({ projectId, canPickAssignee, assigneeIds, currentUser }: CreateTaskFormProps) {
  const baseId = useId();
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const dueRef = useRef<HTMLInputElement>(null);
  const assigneeBoxRef = useRef<HTMLDivElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState(() => todayMsk());
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assignee, setAssignee] = useState<{ id: string; login: string } | null>(currentUser);
  const [errors, setErrors] = useState<DraftErrors>({});
  // A new key empties the picker's own text field.
  const [pickerKey, setPickerKey] = useState(0);
  const [pending, setPending] = useState(false);

  const errorId = (field: DraftField): string => `${baseId}-${field}-error`;
  const fieldProps = (field: DraftField) =>
    errors[field] === undefined
      ? { "aria-required": true as const }
      : { "aria-required": true as const, "aria-invalid": true as const, "aria-describedby": errorId(field) };
  const errorText = (field: DraftField): string | null => {
    const key = errors[field];
    return key === undefined ? null : t(key);
  };

  function clearAssignee(): void {
    setAssignee(null);
    setPickerKey((k) => k + 1);
  }

  function focusField(field: DraftField): void {
    if (field === "title") titleRef.current?.focus();
    else if (field === "description") descriptionRef.current?.focus();
    else if (field === "due_date") dueRef.current?.focus();
    else assigneeBoxRef.current?.querySelector("input")?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    alert.clear();
    const found = taskDraftErrors(
      { title, description, dueDate, assigneeId: canPickAssignee ? (assignee?.id ?? null) : undefined },
      todayMsk(),
    );
    setErrors(found);
    const first = DRAFT_FIELDS.find((field) => found[field] !== undefined);
    if (first !== undefined) {
      focusField(first);
      return;
    }
    // The date is sent exactly as the field holds it: YYYY-MM-DD, no time zone (NFR-5).
    const body: TaskCreate = { title: title.trim(), description, due_date: dueDate, priority };
    if (canPickAssignee && assignee !== null) body.assignee_id = assignee.id;

    busy.current = true;
    setPending(true);
    void (async () => {
      try {
        await createTask(projectId, body);
        setTitle("");
        setDescription("");
        setDueDate(todayMsk());
        setPriority("medium");
        setAssignee(currentUser);
        setPickerKey((k) => k + 1);
        titleRef.current?.focus();
        await queryClient.invalidateQueries({ queryKey: ["tasks", "project", projectId] });
      } catch (e) {
        const code = e instanceof ApiError ? e.code : "unknown";
        if (code === "due_date_in_past") setErrors({ due_date: "tasks.error_due_past" });
        else alert.show(errorMessage(code));
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
          <label htmlFor={`${baseId}-name`}>
            {t("tasks.title_label")}
            <RequiredMark />
          </label>
          <input
            id={`${baseId}-name`}
            ref={titleRef}
            type="text"
            name="title"
            autoComplete="off"
            {...fieldProps("title")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <FieldError id={errorId("title")} message={errorText("title")} />
        </div>
        <div className="ui-field">
          <label htmlFor={`${baseId}-description`}>
            {t("tasks.description_label")}
            <RequiredMark />
          </label>
          <textarea
            id={`${baseId}-description`}
            ref={descriptionRef}
            name="description"
            {...fieldProps("description")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <FieldError id={errorId("description")} message={errorText("description")} />
        </div>
        <div className="ui-field">
          <label htmlFor={`${baseId}-due`}>
            {t("tasks.due_label")}
            <RequiredMark />
          </label>
          <input
            id={`${baseId}-due`}
            ref={dueRef}
            type="date"
            name="due_date"
            {...fieldProps("due_date")}
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
          <FieldError id={errorId("due_date")} message={errorText("due_date")} />
        </div>
        {canPickAssignee ? (
          <div ref={assigneeBoxRef}>
            <UserPicker
              key={pickerKey}
              label={t("tasks.assignee_label")}
              labelMark={<RequiredMark />}
              allowedIds={assigneeIds}
              quietError
              required
              invalid={errors.assignee !== undefined}
              describedBy={errors.assignee === undefined ? undefined : errorId("assignee")}
              onSelect={(user) => setAssignee({ id: user.id, login: user.login })}
            />
            <FieldError id={errorId("assignee")} message={errorText("assignee")} />
            {assignee === null ? null : (
              <p>
                {t("tasks.assignee_selected")}: <strong data-field="selected-assignee">{assignee.login}</strong>{" "}
                <button type="button" data-action="clear-assignee" onClick={clearAssignee}>
                  {t("tasks.assignee_clear")}
                </button>
              </p>
            )}
          </div>
        ) : (
          <p data-field="fixed-assignee">{t("tasks.assignee_fixed", { login: currentUser.login })}</p>
        )}
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

export interface CreateTaskDialogProps {
  /** id проекта из пути `/projects/:projectId` (любая вкладка) или null. */
  currentProjectId: string | null;
  /** 006/FR-20: исполнитель по умолчанию; строка «Исполнитель: <логин>» у «Пользователя». */
  currentUser: { id: string; login: string };
  /** 006/FR-20: выбор исполнителя только у БА. */
  canPickAssignee: boolean;
  /** Закрытие без создания: Escape, «Отмена», «Закрыть». Фокус возвращает вызывающий. */
  onClose: () => void;
  /** 201: задача создана, кэши инвалидированы. Вызывающий закрывает диалог и открывает карточку. */
  onCreated: (task: TaskDetail) => void;
}

const DIALOG_FOCUSABLE = 'input, select, textarea, button, [tabindex]:not([tabindex="-1"])';

/**
 * 004/FR-8..FR-12, FR-19, FR-20; 006/FR-20: modal "new task" (project, title, description, due date,
 * assignee), submit per FR-13..FR-18.
 */
export function CreateTaskDialog({
  currentProjectId,
  currentUser,
  canPickAssignee,
  onClose,
  onCreated,
}: CreateTaskDialogProps) {
  const id = useId();
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const created = useRef(false);
  const mounted = useRef(false);
  const [pending, setPending] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const projectRef = useRef<HTMLSelectElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const dueRef = useRef<HTMLInputElement>(null);
  const assigneeBoxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const focusMoved = useRef(false);
  const [choice, setChoice] = useState<string | null>(null); // null: not touched, "": placeholder
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState(() => todayMsk());
  const [assignee, setAssignee] = useState<{ id: string; login: string } | null>(currentUser);
  const [errors, setErrors] = useState<DraftErrors>({});
  // A new key empties the picker's own text field.
  const [pickerKey, setPickerKey] = useState(0);

  const query = useQuery({
    queryKey: ["projects", "creatable"],
    queryFn: listCreatableProjects,
    retry: false,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
  });
  const projects = query.data;

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  // A window that is gone (the user left the screen) must not report a result to its caller.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // FR-20: once the list is there, focus moves one time from the window to the right element.
  useEffect(() => {
    if (projects === undefined || focusMoved.current) return;
    focusMoved.current = true;
    if (document.activeElement !== dialogRef.current) return;
    if (projects.length === 0) closeRef.current?.focus();
    else if (preselectProject(projects, currentProjectId) !== null) titleRef.current?.focus();
    else projectRef.current?.focus();
  }, [projects, currentProjectId]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!busy.current) onClose(); // FR-18: no closing while the create request is in flight
      return;
    }
    if (event.key !== "Tab") return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(DIALOG_FOCUSABLE)).filter(
      (el) => !(el as HTMLButtonElement).disabled,
    );
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (event.shiftKey) {
      if (index <= 0) {
        event.preventDefault();
        last.focus();
      }
    } else if (index === -1 || index === items.length - 1) {
      event.preventDefault();
      first.focus();
    }
  }

  const listError =
    query.isError ? errorMessage(query.error instanceof ApiError ? query.error.code : "unknown") : null;
  const loading = projects === undefined && !query.isError;
  const selected = choice ?? (projects === undefined ? null : preselectProject(projects, currentProjectId)) ?? "";

  // 006/FR-25: candidates are the members of the chosen project; asked only for a business admin.
  const members = useQuery({
    queryKey: ["projects", selected, "members-all"],
    queryFn: () => listAllMembers(selected),
    enabled: canPickAssignee && selected !== "",
    retry: false,
  });
  const assigneeIds =
    selected === "" || members.data === undefined
      ? []
      : members.data.filter((m) => !m.is_blocked && m.role !== null).map((m) => m.user.id);

  const errorId = (field: DraftField): string => `${id}-${field}-error`;
  const fieldProps = (field: DraftField) =>
    errors[field] === undefined
      ? { "aria-required": true as const }
      : { "aria-required": true as const, "aria-invalid": true as const, "aria-describedby": errorId(field) };
  const errorText = (field: DraftField): string | null => {
    const key = errors[field];
    return key === undefined ? null : t(key);
  };

  function focusField(field: DraftField): void {
    if (field === "title") titleRef.current?.focus();
    else if (field === "description") descriptionRef.current?.focus();
    else if (field === "due_date") dueRef.current?.focus();
    else assigneeBoxRef.current?.querySelector("input")?.focus();
  }

  // 006/PD-13: another project means another candidates list, the assignee is the current user again.
  function chooseProject(value: string): void {
    setChoice(value);
    setAssignee(currentUser);
    setPickerKey((k) => k + 1);
    setErrors((prev) => ({ ...prev, assignee: undefined }));
  }

  function clearAssignee(): void {
    setAssignee(null);
    setPickerKey((k) => k + 1);
  }

  // 004/FR-13..FR-17: one request at a time; the list must be there; input is kept on any failure.
  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current || created.current || loading) return;
    alert.clear();
    const found = taskDraftErrors(
      { title, description, dueDate, assigneeId: canPickAssignee ? (assignee?.id ?? null) : undefined },
      todayMsk(),
    );
    setErrors(found);
    const first = DRAFT_FIELDS.find((field) => found[field] !== undefined);
    if (first !== undefined) {
      focusField(first);
      return;
    }
    if (selected === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    const projectId = selected;
    // The date is sent exactly as the field holds it: YYYY-MM-DD, no time zone (NFR-5).
    const input: TaskCreateInput = { title: title.trim(), description, due_date: dueDate };
    if (canPickAssignee && assignee !== null) input.assignee_id = assignee.id;
    busy.current = true;
    setPending(true);
    void (async () => {
      let task: TaskDetail;
      try {
        task = await createTask(projectId, input);
      } catch (e) {
        const code = e instanceof ApiError ? e.code : "unknown";
        if (code === "due_date_in_past") setErrors({ due_date: "tasks.error_due_past" });
        else alert.show(errorMessage(code));
        busy.current = false;
        setPending(false);
        return;
      }
      // The task exists: a repeated submit must not create a duplicate even if onCreated throws.
      created.current = true;
      // invalidateQueries marks the cache stale synchronously; refetches are not awaited (FR-15).
      void queryClient.invalidateQueries({ queryKey: ["tasks", "project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["board", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", "mine"] });
      busy.current = false;
      setPending(false);
      if (!mounted.current) return;
      // Separate from the create try/catch: a failure of the caller is not a "create error" (no alert);
      // it is reported to the console so that it is not lost as an unhandled rejection.
      try {
        onCreated(task);
      } catch (e) {
        console.error("CreateTaskDialog: onCreated failed", e);
      }
    })();
  }

  const cancel = (
    <button type="button" data-action="cancel" disabled={pending} onClick={onClose}>
      {t("admin.cancel")}
    </button>
  );
  const taskFields = (
    <>
      <div className="ui-field">
        <label htmlFor={`${id}-title-input`}>{t("tasks.title_label")}</label>
        <input
          id={`${id}-title-input`}
          ref={titleRef}
          type="text"
          name="title"
          autoComplete="off"
          {...fieldProps("title")}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <FieldError id={errorId("title")} message={errorText("title")} />
      </div>
      <div className="ui-field">
        <label htmlFor={`${id}-description`}>
          {t("tasks.description_label")}
          <RequiredMark />
        </label>
        <textarea
          id={`${id}-description`}
          ref={descriptionRef}
          name="description"
          {...fieldProps("description")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <FieldError id={errorId("description")} message={errorText("description")} />
      </div>
      <div className="ui-field">
        <label htmlFor={`${id}-due`}>
          {t("tasks.due_label")}
          <RequiredMark />
        </label>
        <input
          id={`${id}-due`}
          ref={dueRef}
          type="date"
          name="due_date"
          {...fieldProps("due_date")}
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
        />
        <FieldError id={errorId("due_date")} message={errorText("due_date")} />
      </div>
      {canPickAssignee ? (
        <div ref={assigneeBoxRef}>
          <UserPicker
            key={pickerKey}
            label={t("tasks.assignee_label")}
            labelMark={<RequiredMark />}
            allowedIds={assigneeIds}
            quietError
            required
            invalid={errors.assignee !== undefined}
            describedBy={errors.assignee === undefined ? undefined : errorId("assignee")}
            onSelect={(user) => setAssignee({ id: user.id, login: user.login })}
          />
          <FieldError id={errorId("assignee")} message={errorText("assignee")} />
          {assignee === null ? null : (
            <p>
              {t("tasks.assignee_selected")}: <strong data-field="selected-assignee">{assignee.login}</strong>{" "}
              <button type="button" data-action="clear-assignee" onClick={clearAssignee}>
                {t("tasks.assignee_clear")}
              </button>
            </p>
          )}
        </div>
      ) : (
        <p data-field="fixed-assignee">{t("tasks.assignee_fixed", { login: currentUser.login })}</p>
      )}
    </>
  );

  let body;
  if (listError !== null) {
    body = cancel;
  } else if (projects !== undefined && projects.length === 0) {
    body = (
      <>
        <p>{t("tasks.no_creatable_projects")}</p>
        <button type="button" data-action="close" ref={closeRef} onClick={onClose}>
          {t("tasks.dialog_close")}
        </button>
      </>
    );
  } else {
    body = (
      <form data-form="create-task-dialog" onSubmit={onSubmit} noValidate>
        {loading || projects === undefined ? (
          <p role="status">{t("admin.loading")}</p>
        ) : (
          <div className="ui-field">
            <label htmlFor={`${id}-project`}>{t("tasks.project_label")}</label>
            <select
              id={`${id}-project`}
              ref={projectRef}
              name="project"
              value={selected}
              onChange={(e) => chooseProject(e.target.value)}
            >
              <option value="">{t("tasks.project_placeholder")}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {taskFields}
        <button type="submit" disabled={loading} aria-busy={pending ? "true" : undefined}>
          {t("tasks.create_submit")}
        </button>{" "}
        {cancel}
      </form>
    );
  }

  return (
    <div className="ui-overlay">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        tabIndex={-1}
        className="ui-dialog ui-create-dialog"
        onKeyDown={onKeyDown}
      >
        <h2 id={`${id}-title`}>{t("tasks.create_title")}</h2>
        <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />
        {body}
      </div>
    </div>
  );
}
