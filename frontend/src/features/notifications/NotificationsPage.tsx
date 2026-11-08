// The /notifications screen (012/FR-5): last 30 days, newest first; a click opens the task and
// marks the notification read; «Прочитать все». No comment text is shown (FR-6).
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { listNotifications, markRead, type Notification } from "./api";

export const UNREAD_KEY = ["notifications", "unread"] as const;
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function codeOf(e: unknown): string {
  const code = (e as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : "unknown";
}

export function NotificationsPage() {
  const [page, setPage] = useState(1);
  const alert = useAlertState();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = usePolledQuery({
    queryKey: ["notifications", "list", { page }],
    queryFn: ({ headers, signal }) => listNotifications(page, { headers, signal }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["notifications"] }),
      queryClient.invalidateQueries({ queryKey: UNREAD_KEY }),
    ]);
  }

  async function open(item: Notification) {
    try {
      if (!item.read) await markRead([item.id]);
      await refresh();
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
    }
    navigate(`/tasks/${item.task.id}`);
  }

  async function readAll() {
    try {
      await markRead(null);
      await refresh();
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
    }
  }

  const items = query.data?.items;
  return (
    <section className="ui-wide">
      <h1>{t("notifications.title")}</h1>
      <ErrorAlert message={alert.message ?? (query.isError ? errorMessage(codeOf(query.error)) : null)} seq={alert.seq} />
      {(query.data?.unread ?? 0) > 0 ? (
        <p>
          <button type="button" data-action="read-all" onClick={() => void readAll()}>
            {t("notifications.read_all")}
          </button>
        </p>
      ) : null}
      {items === undefined ? null : items.length === 0 ? (
        <p data-role="empty">{t("notifications.empty")}</p>
      ) : (
        <ul className="ui-notifications">
          {items.map((item) => (
            <li key={item.id} data-notification-id={item.id} data-read={item.read}>
              <button type="button" className="ui-link" onClick={() => void open(item)}>
                {item.read ? null : <span className="burn-tag">{t("notifications.new")}</span>}{" "}
                {t(`notifications.kind.${item.kind}`)}: {item.task.title}
              </button>{" "}
              <span className="ui-hint">
                {item.project.name}
                {item.actor === null ? "" : ` · ${item.actor.login}`} ·{" "}
                <time dateTime={item.created_at}>{WHEN.format(new Date(item.created_at))}</time>
              </span>
            </li>
          ))}
        </ul>
      )}
      {page > 1 || (query.data?.has_next ?? false) ? (
        <Pagination page={page} hasNext={query.data?.has_next ?? false} busy={query.isPending} onPage={setPage} />
      ) : null}
    </section>
  );
}
