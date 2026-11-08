// Files of a task card (011/FR-9): list, upload, download, delete by rights.
// Polling every 15 s like the comments; errors go to the card's single alert region.
import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";

import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t } from "../../shared/i18n";
import type { AlertState } from "../../shared/ui/ErrorAlert";
import { contentUrl, deleteAttachment, listAttachments, uploadAttachment, type Attachment } from "./api";

const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.xlsx,.pptx,.txt,.csv,.png,.jpg,.jpeg,.gif,.webp";
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function codeOf(e: unknown): string {
  const code = (e as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : "unknown";
}

/** Human size: bytes → КБ/МБ with one decimal (ru). */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return t("attachments.size_b", { n: bytes });
  if (bytes < 1024 * 1024) return t("attachments.size_kb", { n: (bytes / 1024).toFixed(1).replace(".", ",") });
  return t("attachments.size_mb", { n: (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") });
}

function Item({ item, busy, onDelete }: { item: Attachment; busy: boolean; onDelete: (a: Attachment) => void }) {
  return (
    <li data-attachment-id={item.id}>
      <a
        href={contentUrl(item.id)}
        {...(item.inline ? { target: "_blank", rel: "noopener noreferrer" } : { download: item.name })}
      >
        {item.name}
      </a>{" "}
      <span className="ui-hint">
        {formatSize(item.size_bytes)} · {item.author?.login ?? t("tasks.assignee_none")} ·{" "}
        <time dateTime={item.created_at}>{WHEN.format(new Date(item.created_at))}</time>
      </span>{" "}
      {item.can_delete ? (
        <button type="button" data-action="delete-attachment" disabled={busy} onClick={() => onDelete(item)}>
          {t("attachments.delete")}
        </button>
      ) : null}
    </li>
  );
}

export function Attachments({ taskId, alert }: { taskId: string; alert: AlertState }) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const key = ["attachments", taskId] as const;
  const query = usePolledQuery({
    queryKey: key,
    queryFn: ({ headers, signal }) => listAttachments(taskId, { headers, signal }),
  });

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      alert.clear();
      await queryClient.invalidateQueries({ queryKey: key });
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
    } finally {
      setBusy(false);
    }
  }

  function onPick(files: FileList | null) {
    const file = files?.[0];
    if (input.current) input.current.value = "";
    if (file === undefined) return;
    if (file.size > MAX_BYTES) {
      alert.show(errorMessage("attachment_too_large"));
      return;
    }
    void run(() => uploadAttachment(taskId, file));
  }

  const items = query.data ?? [];
  return (
    <section data-slot="attachments" aria-labelledby={`${inputId}-title`}>
      <h2 id={`${inputId}-title`}>{t("attachments.title")}</h2>
      {items.length === 0 ? (
        query.isPending ? null : <p data-role="empty">{t("attachments.empty")}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <Item key={item.id} item={item} busy={busy} onDelete={(a) => void run(() => deleteAttachment(a.id))} />
          ))}
        </ul>
      )}
      <div className="ui-field">
        <label htmlFor={inputId}>{t("attachments.add")}</label>
        <input
          ref={input}
          id={inputId}
          type="file"
          accept={ACCEPT}
          disabled={busy}
          onChange={(e) => onPick(e.target.files)}
        />
        <p className="ui-hint">{t("attachments.hint")}</p>
      </div>
    </section>
  );
}
