import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { TextField } from "../../shared/ui/TextField";
import {
  blockUser,
  createUser,
  listUsers,
  resetPassword,
  revokeSessions,
  setRole,
  unblockUser,
  type AdminUser,
  type Role,
} from "./api";
import { generateOneTimePassword } from "./password";

const USERS_KEY = ["admin", "users"] as const;
const ROLES: readonly Role[] = ["tech_admin", "business_admin", "user"];

type Confirmation =
  | { kind: "block" | "reset" | "revoke" | "remove_role"; user: AdminUser };

const CONFIRM_TEXT: Record<Confirmation["kind"], { title: MessageKey; message: MessageKey }> = {
  block: { title: "admin.users.block_title", message: "admin.users.block_message" },
  reset: { title: "admin.users.reset_title", message: "admin.users.reset_message" },
  revoke: { title: "admin.users.revoke_title", message: "admin.users.revoke_message" },
  remove_role: {
    title: "admin.users.remove_role_title",
    message: "admin.users.remove_role_message",
  },
};

/** The password exists only in this component state until the panel is closed. */
interface ShownPassword {
  login: string;
  password: string;
}

function roleText(role: Role | null): string {
  return t(role === null ? "admin.role.none" : (`admin.role.${role}` as MessageKey));
}

interface RowProps {
  user: AdminUser;
  canAssignRoles: boolean;
  disabled: boolean;
  onBlock: () => void;
  onUnblock: () => void;
  onReset: () => void;
  onRevoke: () => void;
  onSetRole: (role: Role | null) => void;
}

function UserRow(props: RowProps) {
  const { user, canAssignRoles, disabled } = props;
  // null: follow the server value (a reload then shows the new role at once).
  const [draft, setDraft] = useState<string | null>(null);
  const current = user.role ?? "";
  const selected = draft ?? current;
  const params = { login: user.login };
  return (
    <tr data-user-id={user.id}>
      <td data-field="login">{user.login}</td>
      <td data-field="role">{roleText(user.role)}</td>
      <td data-field="status">
        {t(user.is_blocked ? "admin.users.status_blocked" : "admin.users.status_active")}
      </td>
      <td>
        <div className="ui-actions">
          {user.is_blocked ? (
            <button
              type="button"
              data-action="unblock"
              aria-label={t("admin.users.unblock_aria", params)}
              disabled={disabled}
              onClick={props.onUnblock}
            >
              {t("admin.users.unblock")}
            </button>
          ) : (
            <button
              type="button"
              data-action="block"
              aria-label={t("admin.users.block_aria", params)}
              disabled={disabled}
              onClick={props.onBlock}
            >
              {t("admin.users.block")}
            </button>
          )}
          <button
            type="button"
            data-action="reset-password"
            aria-label={t("admin.users.reset_password_aria", params)}
            disabled={disabled}
            onClick={props.onReset}
          >
            {t("admin.users.reset_password")}
          </button>
          <button
            type="button"
            data-action="revoke-sessions"
            aria-label={t("admin.users.revoke_sessions_aria", params)}
            disabled={disabled}
            onClick={props.onRevoke}
          >
            {t("admin.users.revoke_sessions")}
          </button>
          {canAssignRoles ? (
            <>
              <select
                name="role"
                aria-label={t("admin.users.role_select_aria", params)}
                value={selected}
                disabled={disabled}
                onChange={(e) => setDraft(e.target.value)}
              >
                <option value="">{t("admin.role.none")}</option>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleText(r)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                data-action="set-role"
                aria-label={t("admin.users.set_role_aria", params)}
                disabled={disabled || selected === current}
                onClick={() => {
                  props.onSetRole(selected === "" ? null : (selected as Role));
                  setDraft(null);
                }}
              >
                {t("admin.users.set_role")}
              </button>
            </>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

export function UsersPage({ canAssignRoles = false }: { canAssignRoles?: boolean }) {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const [page, setPage] = useState(1);
  const [login, setLogin] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [shown, setShown] = useState<ShownPassword | null>(null);
  const shownRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  // Row whose control had the focus when an action started (see the effect below).
  const restoreRow = useRef<string | null>(null);

  const users = useQuery({
    queryKey: [...USERS_KEY, page],
    queryFn: () => listUsers({ page }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  useEffect(() => {
    if (shown !== null) shownRef.current?.focus();
  }, [shown]);

  // The controls are disabled while an action runs, which drops the focus to
  // <body>; when they come back, the focus returns to the same row (or the table).
  useEffect(() => {
    const rowId = restoreRow.current;
    if (pending || rowId === null) return;
    restoreRow.current = null;
    const active = document.activeElement;
    if (active !== null && active !== document.body) return;
    const table = tableRef.current;
    if (table === null) return;
    const row = Array.from(table.querySelectorAll<HTMLElement>("tr[data-user-id]")).find(
      (el) => el.dataset["userId"] === rowId,
    );
    const target = row?.querySelector<HTMLElement>("button:not(:disabled), select:not(:disabled)");
    (target ?? table).focus();
  }, [pending]);

  /**
   * One action at a time. The controls stay disabled until the list has been
   * reloaded, so a stale row is never active.
   */
  async function run(task: () => Promise<void>, rowId: string | null = null): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    restoreRow.current = rowId;
    try {
      await task();
      setConfirmation(null);
      await queryClient.invalidateQueries({ queryKey: USERS_KEY });
    } catch (e) {
      setConfirmation(null);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
    busy.current = false;
    setPending(false);
  }

  function onCreate(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    const name = login.trim();
    if (name === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    // The password lives in this closure and, after success, in `shown` only.
    const password = generateOneTimePassword();
    void run(async () => {
      const created = await createUser({ login: name, one_time_password: password });
      // The login as the server stored it (FR-73a), not the typed one.
      setShown({ login: created.login, password });
      setLogin("");
    });
  }

  function onConfirm(): void {
    if (confirmation === null) return;
    const { kind, user } = confirmation;
    if (kind === "block") {
      void run(() => blockUser(user.id), user.id);
    } else if (kind === "revoke") {
      void run(() => revokeSessions(user.id), user.id);
    } else if (kind === "remove_role") {
      void run(async () => {
        await setRole(user.id, null);
      }, user.id);
    } else {
      const password = generateOneTimePassword();
      void run(async () => {
        await resetPassword(user.id, { one_time_password: password });
        setShown({ login: user.login, password });
      }, user.id);
    }
  }

  function changePage(next: number): void {
    alert.clear();
    setPage(next);
  }

  const listError =
    users.isError && alert.message === null
      ? errorMessage(users.error instanceof ApiError ? users.error.code : "unknown")
      : null;
  const data = users.data;
  const disabled = pending;

  return (
    <section className="ui-wide">
      <h1>{t("admin.users.title")}</h1>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />

      {shown === null ? null : (
        <div className="ui-secret" role="group" aria-labelledby="admin-password-title" ref={shownRef} tabIndex={-1}>
          <h2 id="admin-password-title">{t("admin.password.title", { login: shown.login })}</h2>
          <p>
            <code data-role="one-time-password">{shown.password}</code>
          </p>
          <p>{t("admin.password.hint")}</p>
          <button type="button" data-action="close-password" onClick={() => setShown(null)}>
            {t("admin.password.close")}
          </button>
        </div>
      )}

      <form onSubmit={onCreate} noValidate aria-label={t("admin.users.create_title")}>
        <TextField
          label={t("admin.users.login_label")}
          name="login"
          value={login}
          onChange={setLogin}
          autoComplete="username"
          hint={t("admin.users.login_hint")}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled}>
          {t("admin.users.create_submit")}
        </button>
      </form>

      {data === undefined ? (
        users.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : data.items.length === 0 ? (
        <p role="status">{t("admin.users.empty")}</p>
      ) : (
        <table className="ui-table" aria-label={t("admin.users.list_label")} ref={tableRef} tabIndex={-1}>
          <thead>
            <tr>
              <th scope="col">{t("admin.users.col_login")}</th>
              <th scope="col">{t("admin.users.col_role")}</th>
              <th scope="col">{t("admin.users.col_status")}</th>
              <th scope="col">{t("admin.users.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                canAssignRoles={canAssignRoles}
                disabled={disabled}
                onBlock={() => setConfirmation({ kind: "block", user })}
                onUnblock={() => void run(() => unblockUser(user.id), user.id)}
                onReset={() => setConfirmation({ kind: "reset", user })}
                onRevoke={() => setConfirmation({ kind: "revoke", user })}
                onSetRole={(role) => {
                  if (role === null) {
                    setConfirmation({ kind: "remove_role", user });
                  } else {
                    void run(async () => {
                      await setRole(user.id, role);
                    }, user.id);
                  }
                }}
              />
            ))}
          </tbody>
        </table>
      )}

      <Pagination
        page={page}
        hasNext={data?.has_next ?? false}
        busy={users.isPlaceholderData || pending}
        onPage={changePage}
      />

      {confirmation === null ? null : (
        <ConfirmDialog
          title={t(CONFIRM_TEXT[confirmation.kind].title)}
          message={t(CONFIRM_TEXT[confirmation.kind].message, { login: confirmation.user.login })}
          pending={pending}
          onConfirm={onConfirm}
          onCancel={() => setConfirmation(null)}
        />
      )}
    </section>
  );
}
