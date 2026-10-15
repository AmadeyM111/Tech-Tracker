// Comments of the task card (T85): UF-6, FR-23 (plain text), FR-29 (polling), AC-58, NFR-5..7.
// The text of a comment is a plain React text node with `white-space: pre-wrap`: nothing is
// interpreted as HTML (SC-11).
import { useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { usePolledQuery } from "../../shared/api/polling";
import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, type AlertState } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import type { Page } from "../admin/api";
import {
  createComment,
  deleteComment,
  listComments,
  updateComment,
  type Comment,
} from "./api";

// Display time is Europe/Moscow (NFR-5); the API speaks UTC. The same format as the audit log
// (features/admin/AuditPage.tsx): duplicated on purpose, moving it to shared would change
// a file outside this task.
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const codeOf = (e: unknown): string => (e instanceof ApiError ? e.code : "unknown");

export interface CommentsProps {
  taskId: string;
  /** The card's single alert region: the comments show no alert of their own for actions. */
  alert: AlertState;
  /** True while the card itself shows a load error: the list does not add a second alert. */
  suppressLoadError?: boolean;
}

interface ItemProps {
  comment: Comment;
  pending: boolean;
  alert: AlertState;
  onSave: (id: string, body: string) => Promise<boolean>;
  onDelete: (id: string) => void;
}

function CommentItem({ comment, pending, alert, onSave, onDelete }: ItemProps) {
  const baseId = useId();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const editRef = useRef<HTMLButtonElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  // After the edit form was closed the focus goes back to the button that opened it (NFR-7).
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (editing) {
      areaRef.current?.focus();
    } else if (restoreFocus.current) {
      restoreFocus.current = false;
      editRef.current?.focus();
    }
  }, [editing]);

  function close(): void {
    restoreFocus.current = true;
    setEditing(false);
  }

  function open(): void {
    setDraft(comment.body ?? "");
    setEditing(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const text = draft.trim();
    if (text === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    void onSave(comment.id, text).then((saved) => {
      if (saved) close();
    });
  }

  const author = (
    <span data-field="author">{comment.author.login}</span>
  );
  const when = (
    <span data-field="created_at">
      <time dateTime={comment.created_at}>{WHEN.format(new Date(comment.created_at))}</time>
    </span>
  );

  if (comment.is_deleted) {
    return (
      <li data-comment-id={comment.id} data-deleted="true">
        {author} {when}{" "}
        <span data-field="deleted">{t("comments.deleted")}</span>
      </li>
    );
  }

  return (
    <li data-comment-id={comment.id}>
      {author} {when}
      {comment.edited_at === null ? null : (
        <>
          {" "}
          <span data-field="edited">{t("comments.edited")}</span>
        </>
      )}
      {editing ? (
        <form data-form="edit-comment" onSubmit={onSubmit} noValidate aria-busy={pending ? "true" : undefined}>
          <div className="ui-field">
            <label htmlFor={`${baseId}-body`}>{t("comments.edit_label")}</label>
            <textarea
              id={`${baseId}-body`}
              ref={areaRef}
              name="body"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
            />
          </div>
          <button type="submit">{t("comments.save")}</button>{" "}
          <button type="button" data-action="cancel-edit" onClick={close}>
            {t("comments.cancel_edit")}
          </button>
        </form>
      ) : (
        <>
          <p data-field="body" style={{ whiteSpace: "pre-wrap" }}>
            {comment.body}
          </p>
          {comment.permissions.edit ? (
            <button type="button" data-action="edit-comment" ref={editRef} onClick={open}>
              {t("comments.edit")}
            </button>
          ) : null}
          {comment.permissions.delete ? (
            <>
              {" "}
              <button type="button" data-action="delete-comment" onClick={() => onDelete(comment.id)}>
                {t("comments.delete")}
              </button>
            </>
          ) : null}
        </>
      )}
    </li>
  );
}

export function Comments({ taskId, alert, suppressLoadError = false }: CommentsProps) {
  const baseId = useId();
  const queryClient = useQueryClient();
  const busy = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  // Set when the comment that had the focus' button is gone: the focus goes to the heading.
  const focusHeading = useRef(false);
  const [page, setPage] = useState(1);
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // The page on screen: the previous one stays until the requested page arrives.
  const [shown, setShown] = useState<Page<Comment> | undefined>(undefined);

  const listKey = ["tasks", "comments", taskId] as const;
  const query = usePolledQuery({
    queryKey: [...listKey, page],
    queryFn: ({ headers, signal }) => listComments(taskId, { page }, { headers, signal }),
  });
  if (query.data !== undefined && query.data !== shown) setShown(query.data);

  useEffect(() => {
    if (deletingId === null && focusHeading.current) {
      focusHeading.current = false;
      headingRef.current?.focus();
    }
  }, [deletingId]);

  /** One action at a time; the error (if any) goes to the card's alert region. */
  async function run(action: () => Promise<void>): Promise<boolean> {
    if (busy.current) return false;
    busy.current = true;
    setPending(true);
    alert.clear();
    let ok = false;
    try {
      await action();
      ok = true;
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
    }
    busy.current = false;
    setPending(false);
    return ok;
  }

  const reload = (): Promise<void> => queryClient.invalidateQueries({ queryKey: listKey });

  function onCreate(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    const body = text.trim();
    if (body === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    void run(async () => {
      await createComment(taskId, body);
      setText("");
      areaRef.current?.focus();
      await reload();
    });
  }

  function onSave(id: string, body: string): Promise<boolean> {
    return run(async () => {
      await updateComment(id, body);
      await reload();
    });
  }

  function onConfirmDelete(): void {
    const id = deletingId;
    if (id === null) return;
    void run(async () => {
      await deleteComment(id);
      focusHeading.current = true;
      await reload();
    }).then(() => setDeletingId(null));
  }

  const loadError =
    query.isError && !suppressLoadError && alert.message === null ? errorMessage(codeOf(query.error)) : null;
  const items = shown?.items;

  return (
    <section data-section="comments" aria-labelledby={`${baseId}-title`}>
      <h2 id={`${baseId}-title`} ref={headingRef} tabIndex={-1}>
        {t("comments.title")}
      </h2>
      <ErrorAlert message={loadError} />
      {items === undefined ? (
        query.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : items.length === 0 ? (
        <p data-role="empty">{t("comments.empty")}</p>
      ) : (
        <ul>
          {items.map((c) => (
            <CommentItem
              key={c.id}
              comment={c}
              pending={pending}
              alert={alert}
              onSave={onSave}
              onDelete={setDeletingId}
            />
          ))}
        </ul>
      )}
      <Pagination
        page={page}
        hasNext={shown?.has_next ?? false}
        busy={query.data === undefined && query.isFetching}
        onPage={setPage}
      />
      <form data-form="create-comment" onSubmit={onCreate} noValidate aria-busy={pending ? "true" : undefined}>
        <div className="ui-field">
          <label htmlFor={`${baseId}-body`}>{t("comments.body_label")}</label>
          <textarea
            id={`${baseId}-body`}
            ref={areaRef}
            name="body"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <button type="submit">{t("comments.add")}</button>
      </form>
      {deletingId === null ? null : (
        <ConfirmDialog
          title={t("comments.delete_title")}
          message={t("comments.delete_confirm_message")}
          pending={pending}
          onConfirm={onConfirmDelete}
          onCancel={() => setDeletingId(null)}
        />
      )}
    </section>
  );
}
