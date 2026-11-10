// Лента проекта (FR-38, ADR-0015): вкладка «Лента» карточки проекта. Опрос — usePolledQuery
// (FR-29, FR-59). Текст комментариев в ленту не приходит; удалённый объект — «объект удалён».
import { useState } from "react";

import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { Pagination } from "../../shared/ui/Pagination";
import { listActivity, type ActivityChange, type ActivityItem } from "./api";

// Display time is Europe/Moscow (NFR-5); the API speaks UTC (same format as comments and audit).
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const ACTION_KEYS: Readonly<Record<string, MessageKey>> = {
  "project.updated": "activity.action.project.updated",
  "project.ownership_transferred": "activity.action.project.ownership_transferred",
  "member.added": "activity.action.member.added",
  "member.removed": "activity.action.member.removed",
  "task.created": "activity.action.task.created",
  "task.updated": "activity.action.task.updated",
  "task.deleted": "activity.action.task.deleted",
  "task.unassigned_member_removed": "activity.action.task.unassigned_member_removed",
  "comment.created": "activity.action.comment.created",
  "comment.deleted": "activity.action.comment.deleted",
};

const FIELD_KEYS: Readonly<Record<string, MessageKey>> = {
  name: "activity.field.name",
  description: "activity.field.description",
  title: "activity.field.title",
  status: "activity.field.status",
  assignee_id: "activity.field.assignee_id",
  due_date: "activity.field.due_date",
  owner_id: "activity.field.owner_id",
};

const STATUS_KEYS: Readonly<Record<string, MessageKey>> = {
  todo: "tasks.status.todo",
  in_progress: "tasks.status.in_progress",
  review: "tasks.status.review",
  done: "tasks.status.done",
};

const YMD = /^(\d{4})-(\d{2})-(\d{2})/;

/** Текст словаря по ключу из таблицы; неизвестный код — `undefined` (показывается как есть). */
function translated(table: Readonly<Record<string, MessageKey>>, code: string): string | undefined {
  const key = Object.hasOwn(table, code) ? table[code] : undefined;
  return key === undefined ? undefined : t(key);
}

function fieldLabel(field: string): string {
  return translated(FIELD_KEYS, field) ?? field;
}

function valueText(field: string, value: unknown): string {
  if (value === null || value === undefined) return t("activity.empty_value");
  if (typeof value === "string") {
    if (field === "status") {
      const label = translated(STATUS_KEYS, value);
      if (label !== undefined) return label;
    }
    const m = YMD.exec(value);
    if (field === "due_date" && m !== null) return `${m[3]}.${m[2]}.${m[1]}`;
    return value;
  }
  if (typeof value === "object" && "login" in value && typeof value.login === "string") {
    return value.login;
  }
  return t("activity.empty_value");
}

function changeText(change: ActivityChange): string {
  return t("activity.change", {
    field: fieldLabel(change.field),
    old: valueText(change.field, change.old),
    new: valueText(change.field, change.new),
  });
}

function actionText(action: string): string {
  return translated(ACTION_KEYS, action) ?? action;
}

function entityText(item: ActivityItem): string | null {
  if (item.entity.deleted) return t("activity.deleted");
  if (item.entity.title !== null && item.entity.title !== undefined) return item.entity.title;
  return item.entity.type === "comment" ? t("activity.comment") : null;
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const entity = entityText(item);
  const actor = item.actor.kind === "system" ? t("activity.system") : (item.actor.login ?? "—");
  return (
    <li data-activity-id={item.id} className="ui-activity-item">
      <time dateTime={item.occurred_at}>{WHEN.format(new Date(item.occurred_at))}</time>{" "}
      <span data-field="actor">{actor}</span> <span data-field="action">{actionText(item.action)}</span>
      {entity === null ? null : (
        <>
          {" "}
          «<span data-field="entity">{entity}</span>»
        </>
      )}
      {item.changes !== null && item.changes.length > 0 ? (
        <ul data-field="changes">
          {item.changes.map((change) => (
            <li key={change.field}>{changeText(change)}</li>
          ))}
        </ul>
      ) : item.changed_fields.length > 0 ? (
        <p data-field="changed-fields">
          {t("activity.changed_fields", { fields: item.changed_fields.map(fieldLabel).join(", ") })}
        </p>
      ) : null}
    </li>
  );
}

export function ActivityFeed({ projectId }: { projectId: string }) {
  // Номер страницы — локальное состояние панели; сбрасывается вместе с перемонтированием вкладки.
  const [page, setPage] = useState(1);
  const feed = usePolledQuery({
    queryKey: ["projects", projectId, "activity", page],
    queryFn: ({ headers, signal }) => listActivity(projectId, { page, headers, signal }),
  });

  if (feed.isPending) return <p>{t("activity.loading")}</p>;
  if (feed.isError) return <p role="alert">{errorMessage(feed.error.code)}</p>;

  const items = feed.data.items;
  return (
    <section aria-label={t("activity.list_label")}>
      {items.length === 0 ? (
        <p>{t("activity.empty")}</p>
      ) : (
        <ol data-field="activity-list" className="ui-activity-list">
          {items.map((item) => (
            <ActivityRow key={item.id} item={item} />
          ))}
        </ol>
      )}
      {/* Аудит #9: пустая первая страница - без пагинации; со страницы > 1 остаётся, чтобы вернуться назад. */}
      {items.length > 0 || page > 1 ? (
        <Pagination
          page={page}
          hasNext={feed.data.has_next}
          busy={feed.isFetching}
          onPage={setPage}
        />
      ) : null}
    </section>
  );
}
