// Tech admin warning about stale backups (009/FR-7, plan PB-6); block with a border and an icon (UI kit, mockup gtrack-r2-backup-banner). One plain request per
// screen visit (status changes once a day: no polling). A failed request shows nothing:
// the banner is advisory and must not block the admin screens.
import { useQuery } from "@tanstack/react-query";

import { t } from "../../shared/i18n";
import { Icon } from "../../shared/ui/Icon";
import { getBackupStatus, type BackupStatus } from "./api";

// Display time is Europe/Moscow (NFR-5); the API speaks UTC.
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export const BACKUP_STATUS_KEY = ["admin", "system", "backup"] as const;

/** Text of the banner or null when backups are fine. Pure function. */
export function backupWarning(status: BackupStatus): string | null {
  if (!status.stale) return null;
  if (status.last_run_status === "failed" && status.last_run_at !== null) {
    return t("admin.backup.failed", { when: WHEN.format(new Date(status.last_run_at)) });
  }
  if (status.last_success_at === null) return t("admin.backup.none");
  return t("admin.backup.old", {
    hours: status.stale_after_hours,
    when: WHEN.format(new Date(status.last_success_at)),
  });
}

export function BackupBanner() {
  const query = useQuery({
    queryKey: BACKUP_STATUS_KEY,
    queryFn: getBackupStatus,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
  const message = query.data === undefined ? null : backupWarning(query.data);
  if (message === null) return null;
  return (
    <p role="status" className="ui-error-alert" data-banner="backup">
      <Icon name="alert" />
      {message}
    </p>
  );
}
