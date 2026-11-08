// Menu item «Уведомления» with the unread counter (012/FR-5), polled every 15 s; > 99 — «99+».
import { NavLink } from "react-router-dom";

import { usePolledQuery } from "../../shared/api/polling";
import { t } from "../../shared/i18n";
import { Icon } from "../../shared/ui/Icon";
import { getUnread } from "./api";
import { UNREAD_KEY } from "./NotificationsPage";

export function badgeText(unread: number): string {
  return unread > 99 ? "99+" : String(unread);
}

export function NotificationsMenuItem() {
  const query = usePolledQuery({
    queryKey: UNREAD_KEY,
    queryFn: ({ headers, signal }) => getUnread({ headers, signal }),
  });
  const unread = query.data ?? 0;
  return (
    <NavLink to="/notifications" aria-label={unread > 0 ? t("notifications.menu_unread", { n: unread }) : undefined}>
      <Icon name="tasks" />
      {t("notifications.title")}
      {unread > 0 ? (
        <span className="nav-badge" data-unread={unread} aria-hidden="true">
          {badgeText(unread)}
        </span>
      ) : null}
    </NavLink>
  );
}
