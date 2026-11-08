// «Вложения» of a task card (011/FR-9; mockups Shared/Design/gtrack-r2-attachments-notifications,
// approved 2026-11-08): list with type badge, «Открыть» (images) and «Скачать», «Удалить» by rights
// with confirmation, counter «N из 20», drop zone with «Выбрать файл», limit state, upload errors
// inside the section. Polling every 15 s like the comments.
import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type DragEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import type { AlertState } from "../../shared/ui/ErrorAlert";
import { contentUrl, deleteAttachment, listAttachments, uploadAttachment, type Attachment } from "./api";
import "./attachments.css";

const MAX_BYTES = 10 * 1024 * 1024;
/** Server default ATTACHMENTS_PER_TASK (FR-3). */
export const LIMIT = 20;
const ACCEPT = ".pdf,.docx,.xlsx,.pptx,.txt,.csv,.png,.jpg,.jpeg,.gif,.webp";
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
// Upload errors shown inside the section with the mockup texts; other codes — generic messages.
const UPLOAD_ERRORS: Record<string, MessageKey> = {
  attachment_type_not_allowed: "attachments.err_type",
  attachment_too_large: "attachments.err_size",
  storage_full: "attachments.err_storage",
  too_many_attachments: "attachments.limit",
};

function codeOf(e: unknown): string {
  const code = (e as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : "unknown";
}

function uploadError(code: string): string {
  const key = UPLOAD_ERRORS[code];
  return key === undefined ? errorMessage(code) : t(key);
}

/** «820 КБ», «1,2 МБ» (mockup). */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return t("attachments.size_b", { n: bytes });
  if (bytes < 1024 * 1024) return t("attachments.size_kb", { n: Math.round(bytes / 1024) });
  return t("attachments.size_mb", { n: (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") });
}

function Item({ item, busy, onDelete }: { item: Attachment; busy: boolean; onDelete: (a: Attachment) => void }) {
  return (
    <li className="att-item" data-attachment-id={item.id}>
      <span className="att-name">
        <span className="att-kind">{item.kind.toUpperCase()}</span>
        {item.name}
      </span>
      <span className="att-actions">
        {item.inline ? (
          <a href={contentUrl(item.id)} target="_blank" rel="noopener noreferrer" data-action="open">
            {t("attachments.open")}
          </a>
        ) : null}
        <a href={contentUrl(item.id)} download={item.name} data-action="download">
          {t("attachments.download")}
        </a>
        {item.can_delete ? (
          <button
            type="button"
            className="ui-secondary"
            data-action="delete-attachment"
            disabled={busy}
            onClick={() => onDelete(item)}
          >
            {t("attachments.delete")}
          </button>
        ) : null}
      </span>
      <span className="att-meta">
        {formatSize(item.size_bytes)} · {item.author?.login ?? t("tasks.assignee_none")} ·{" "}
        <time dateTime={item.created_at}>{WHEN.format(new Date(item.created_at))}</time>
      </span>
    </li>
  );
}

export function Attachments({ taskId, alert }: { taskId: string; alert: AlertState }) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Attachment | null>(null);
  const key = ["attachments", taskId] as const;
  const query = usePolledQuery({
    queryKey: key,
    queryFn: ({ headers, signal }) => listAttachments(taskId, { headers, signal }),
  });

  async function upload(file: File) {
    setError(null);
    if (file.size > MAX_BYTES) {
      setError(t("attachments.err_size"));
      return;
    }
    setBusy(true);
    setUploading(file.name);
    try {
      await uploadAttachment(taskId, file);
      await queryClient.invalidateQueries({ queryKey: key });
    } catch (e) {
      setError(uploadError(codeOf(e)));
    } finally {
      setBusy(false);
      setUploading(null);
    }
  }

  async function confirmDelete() {
    if (deleting === null) return;
    setBusy(true);
    try {
      await deleteAttachment(deleting.id);
      alert.clear();
      await queryClient.invalidateQueries({ queryKey: key });
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  }

  function onPick(files: FileList | null) {
    const file = files?.[0];
    if (input.current) input.current.value = "";
    if (file !== undefined) void upload(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!busy) onPick(event.dataTransfer.files);
  }

  const title = (
    <h2 className="sec-title" id={`${id}-title`}>
      {t("attachments.title")}
    </h2>
  );
  if (query.error instanceof ApiError && query.error.status === 403) {
    return (
      <section data-slot="attachments" aria-labelledby={`${id}-title`}>
        {title}
        <p className="att-note">{t("attachments.not_member")}</p>
      </section>
    );
  }
  const items = query.data ?? [];
  const full = items.length >= LIMIT;
  return (
    <section data-slot="attachments" aria-labelledby={`${id}-title`}>
      {title}
      {items.length > 0 ? (
        <ul className="att-list">
          {items.map((item) => (
            <Item key={item.id} item={item} busy={busy} onDelete={setDeleting} />
          ))}
        </ul>
      ) : null}
      {query.data !== undefined ? (
        <p className="ui-hint" data-role="counter">
          {t("attachments.counter", { n: items.length, max: LIMIT })}
        </p>
      ) : null}
      {uploading !== null ? (
        <div className="att-progress">
          <div className="att-progress-row">{t("attachments.uploading", { name: uploading })}</div>
          <div className="att-track" role="progressbar" aria-label={t("attachments.uploading", { name: uploading })}>
            <div className="att-fill att-fill--busy" />
          </div>
        </div>
      ) : full ? (
        <div className="att-drop is-disabled" data-role="limit">
          <strong>{t("attachments.limit")}</strong>
          {t("attachments.limit_hint")}
        </div>
      ) : (
        <div className="att-drop" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <strong>{t("attachments.drop")}</strong>
          {t("attachments.hint")}
          <p>
            <input
              ref={input}
              id={`${id}-file`}
              type="file"
              accept={ACCEPT}
              hidden
              onChange={(e) => onPick(e.target.files)}
            />
            <button type="button" data-action="pick-file" disabled={busy} onClick={() => input.current?.click()}>
              {t("attachments.pick")}
            </button>
          </p>
        </div>
      )}
      {error === null ? null : (
        <p className="att-error" role="alert">
          {error}
        </p>
      )}
      {items.some((i) => !i.can_delete) ? <p className="att-hint">{t("attachments.no_rights")}</p> : null}
      {deleting === null ? null : (
        <ConfirmDialog
          title={t("attachments.delete_title")}
          message={t("attachments.delete_message", { name: deleting.name })}
          pending={busy}
          confirmLabel={t("attachments.delete")}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleting(null)}
        />
      )}
    </section>
  );
}
