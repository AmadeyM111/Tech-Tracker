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
import { MentionSuggest, MentionText, insertMention, mentionAt, useMentionOptions } from "./MentionSuggest";
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
  /** 012/FR-2: project of the task — «@» suggests its members; null — no suggestions. */
  projectId?: string | null;
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
            <MentionText text={comment.body ?? ""} />
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

export function Comments({ taskId, alert, suppressLoadError = false, projectId = null }: CommentsProps) {
  const baseId = useId();
  const queryClient = useQueryClient();
  const busy = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  // Set when the comment that had the focus' button is gone: the focus goes to the heading.
  const focusHeading = useRef(false);
  const [page, setPage] = useState(1);
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const pendingCaret = useRef<number | null>(null);
  const partial = mentionAt(text, caret);
  const options = useMentionOptions(projectId, partial);

  // После вставки логина курсор ставится сразу за ним (ревью 012, п. 8).
  useEffect(() => {
    if (pendingCaret.current !== null && areaRef.current !== null) {
      areaRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  }, [text]);

  function pickMention(login: string) {
    const next = insertMention(text, caret, login);
    pendingCaret.current = next.caret;
    setText(next.text);
    setCaret(next.caret);
    setActive(0);
    areaRef.current?.focus();
  }

  function onMentionKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (options === undefined || options.length === 0) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const login = options[Math.min(active, options.length - 1)];
      if (login !== undefined) pickMention(login);
    }
  }
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
            onChange={(e) => {
              setText(e.target.value);
              setCaret(e.target.selectionStart);
              setActive(0);
            }}
            onSelect={(e) => setCaret(e.currentTarget.selectionStart)}
            onKeyDown={onMentionKey}
          />
          <MentionSuggest partial={partial} options={options} active={active} onPick={pickMention} />
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
