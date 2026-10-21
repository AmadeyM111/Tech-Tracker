// Task lists (T83): the project's "Tasks" tab and the personal /my-tasks page.
// UF-3, FR-26, FR-27, FR-29 (polling), AC-6, NFR-5..7.
import { useId, useState } from "react";

import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import type { ProjectMember } from "../projects/api";
import {
  listMyTasks,
  listProjectTasks,
  type TaskListItem,
  type TaskStatus,
} from "./api";
import { CreateTaskForm } from "./CreateTaskForm";

const STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "review", "done"];
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

function TaskTable({ items, withProject }: { items: TaskListItem[]; withProject: boolean }) {
  return (
    <table className="ui-table" aria-label={t("tasks.list_label")}>
      <thead>
        <tr>
          <th scope="col">{t("tasks.col_title")}</th>
          {withProject ? <th scope="col">{t("tasks.col_project")}</th> : null}
          <th scope="col">{t("tasks.col_status")}</th>
          <th scope="col">{t("tasks.col_priority")}</th>
          <th scope="col">{t("tasks.col_assignee")}</th>
          <th scope="col">{t("tasks.col_due")}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((task) => (
          <tr key={task.id} data-task-id={task.id}>
            <td data-field="title">
              <a href={`/tasks/${task.id}`}>{task.title}</a>
            </td>
            {withProject ? (
              <td data-field="project">
                <a href={`/projects/${task.project.id}`}>{task.project.name}</a>
              </td>
            ) : null}
            <td data-field="status">{t(`tasks.status.${task.status}`)}</td>
            <td data-field="priority">{t(`tasks.priority.${task.priority}`)}</td>
            <td data-field="assignee">{task.assignee === null ? t("tasks.assignee_none") : task.assignee.login}</td>
            <td data-field="due_date">
              {task.due_date === null ? (
                t("tasks.due_none")
              ) : (
                <time dateTime={task.due_date}>{formatDate(task.due_date)}</time>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface ListViewProps {
  items: TaskListItem[] | undefined;
  isPending: boolean;
  error: unknown;
  isError: boolean;
  page: number;
  hasNext: boolean;
  onPage: (page: number) => void;
  withProject: boolean;
}

function ListView(props: ListViewProps) {
  const { items, isPending, isError, error, page, hasNext, onPage, withProject } = props;
  return (
    <>
      <ErrorAlert message={isError ? errorMessage(codeOf(error)) : null} />
      {items === undefined ? (
        isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : items.length === 0 ? (
        <p data-role="empty">{t("tasks.empty")}</p>
      ) : (
        <TaskTable items={items} withProject={withProject} />
      )}
      {/* Not before the first answer (or after a failed first load): no empty navigation landmark. */}
      {items !== undefined || page > 1 ? (
        <Pagination page={page} hasNext={hasNext} busy={isPending} onPage={onPage} />
      ) : null}
    </>
  );
}

export interface ProjectTaskListProps {
  projectId: string;
  /** Members of the project (assignee filter options, assignee picker limit). */
  members: readonly ProjectMember[];
  /** `permissions.create_task` of the project. */
  canCreate: boolean;
  /** The actor's role from /me: only a business admin may choose an assignee (FR-9). */
  actorRole: string | null;
  /** 006/FR-19: исполнитель по умолчанию в форме создания. */
  currentUser: { id: string; login: string };
}

/** Content of the "Tasks" tab (without the tab heading). */
export function ProjectTaskList({ projectId, members, canCreate, actorRole, currentUser }: ProjectTaskListProps) {
  const baseId = useId();
  const [page, setPage] = useState(1);
  const [assigneeId, setAssigneeId] = useState("");
  const [status, setStatus] = useState("");

  const query = usePolledQuery({
    queryKey: ["tasks", "project", projectId, { page, assigneeId, status }],
    queryFn: ({ headers, signal }) =>
      listProjectTasks(
        {
          projectId,
          page,
          assigneeId: assigneeId === "" ? undefined : assigneeId,
          status: status === "" ? undefined : (status as TaskStatus),
        },
        { headers, signal },
      ),
  });

  const canPickAssignee = actorRole === "business_admin";
  const assigneeIds = members.filter((m) => !m.is_blocked && m.role !== null).map((m) => m.user.id);

  return (
    <>
      {canCreate ? (
        <CreateTaskForm
          projectId={projectId}
          canPickAssignee={canPickAssignee}
          assigneeIds={assigneeIds}
          currentUser={currentUser}
        />
      ) : null}
      <div className="ui-actions">
        <div className="ui-field">
          <label htmlFor={`${baseId}-assignee`}>{t("tasks.filter_assignee")}</label>
          <select
            id={`${baseId}-assignee`}
            name="assignee_id"
            value={assigneeId}
            onChange={(e) => {
              setAssigneeId(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t("tasks.filter_assignee_all")}</option>
            {members.map((m) => (
              <option key={m.user.id} value={m.user.id}>
                {m.user.login}
              </option>
            ))}
          </select>
        </div>
        <div className="ui-field">
          <label htmlFor={`${baseId}-status`}>{t("tasks.filter_status")}</label>
          <select
            id={`${baseId}-status`}
            name="status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t("tasks.filter_status_all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`tasks.status.${s}`)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <ListView
        items={query.data?.items}
        isPending={query.isPending}
        isError={query.isError}
        error={query.error}
        page={page}
        hasNext={query.data?.has_next ?? false}
        onPage={setPage}
        withProject={false}
      />
    </>
  );
}

/** The /my-tasks screen: tasks assigned to the current user, all projects (AC-6). */
export function MyTasksPage() {
  const [page, setPage] = useState(1);
  const query = usePolledQuery({
    queryKey: ["tasks", "mine", { page }],
    queryFn: ({ headers, signal }) => listMyTasks({ page }, { headers, signal }),
  });
  return (
    <section className="ui-wide">
      <h1>{t("tasks.my_title")}</h1>
      <ListView
        items={query.data?.items}
        isPending={query.isPending}
        isError={query.isError}
        error={query.error}
        page={page}
        hasNext={query.data?.has_next ?? false}
        onPage={setPage}
        withProject
      />
    </section>
  );
}
