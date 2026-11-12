// The /notifications screen (012/FR-5; mockup Shared/Design/gtrack-r2-attachments-notifications,
// approved 2026-11-08): newest first; unread — accent border, «Новое», «Прочитано»; a click on the
// title opens the task and marks it read; «Прочитать все». No comment text is shown (FR-6).
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

function Item(props: { item: Notification; onOpen: (n: Notification) => void; onRead: (n: Notification) => void }) {
  const { item, onOpen, onRead } = props;
  return (
    <li className={item.read ? "notif" : "notif is-unread"} data-notification-id={item.id} data-read={item.read}>
      <div>
        <button type="button" className="ui-link notif-title" onClick={() => onOpen(item)}>
          {t(`notifications.kind.${item.kind}`)}
        </button>
        {item.read ? null : <span className="notif-tag">{t("notifications.new")}</span>}
      </div>
      <div className="notif-actions">
        {item.read ? null : (
          <button type="button" className="ui-secondary" data-action="read-one" onClick={() => onRead(item)}>
            {t("notifications.mark_read")}
          </button>
        )}
      </div>
      <p className="notif-meta">
        {item.task.title} · {item.project.name}
        {item.actor === null ? "" : ` · ${item.actor.login}`} ·{" "}
        <time dateTime={item.created_at}>{WHEN.format(new Date(item.created_at))}</time>
      </p>
    </li>
  );
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

  async function read(ids: string[] | null): Promise<boolean> {
    try {
      await markRead(ids);
      await queryClient.invalidateQueries({ queryKey: ["notifications"] });
      return true;
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
      return false;
    }
  }

  async function open(item: Notification) {
    if (!item.read) await read([item.id]);
    navigate(`/tasks/${item.task.id}`);
  }

  const items = query.data?.items;
  const unread = query.data?.unread ?? 0;
  return (
    <section className="ui-wide">
      <h1>{t("notifications.title")}</h1>
      <ErrorAlert message={alert.message ?? (query.isError ? errorMessage(codeOf(query.error)) : null)} seq={alert.seq} />
      {items === undefined ? null : items.length === 0 ? (
        <div className="notif-empty" data-role="empty">
          <p>{t("notifications.empty")}</p>
          <p>{t("notifications.empty_hint")}</p>
        </div>
      ) : (
        <>
          <div className="notif-toolbar">
            <p className="ui-hint">{t("notifications.window")}</p>
            {unread > 0 ? (
              <button type="button" data-action="read-all" onClick={() => void read(null)}>
                {t("notifications.read_all")}
              </button>
            ) : null}
          </div>
          <ul className="notif-list">
            {items.map((item) => (
              <Item key={item.id} item={item} onOpen={(n) => void open(n)} onRead={(n) => void read([n.id])} />
            ))}
          </ul>
        </>
      )}
      {/* Аудит #9: пустая первая страница - без пагинации; со страницы > 1 остаётся, чтобы вернуться назад. */}
      {page > 1 || ((items?.length ?? 0) > 0 && (query.data?.has_next ?? false)) ? (
        <Pagination page={page} hasNext={query.data?.has_next ?? false} busy={query.isPending} onPage={setPage} />
      ) : null}
    </section>
  );
}
