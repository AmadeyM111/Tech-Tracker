import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { TextField } from "../../shared/ui/TextField";
import { UserName } from "../../shared/ui/UserPicker";
import {
  blockUser,
  createAgent,
  createUser,
  issueApiKey,
  listApiKeys,
  listUsers,
  resetPassword,
  revokeApiKey,
  revokeSessions,
  setRole,
  unblockUser,
  type AdminUser,
  type ApiKeyInfo,
  type Role,
} from "./api";
import { useFocusHeadingOnArrival } from "../auth/session";
import { generateOneTimePassword } from "./password";

const USERS_KEY = ["admin", "users"] as const;
const ROLES: readonly Role[] = ["tech_admin", "business_admin", "user"];
// An agent never gets the tech admin role (007/FR-2): the server answers 422, the UI does not offer it.
const AGENT_ROLES: readonly Role[] = ["business_admin", "user"];

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
  onKeys: () => void;
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
      <td data-field="login">
        <UserName user={user} />
      </td>
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
          {user.is_agent ? null : (
            // An agent has no password, so nothing to reset (007/FR-1).
            <button
              type="button"
              data-action="reset-password"
              aria-label={t("admin.users.reset_password_aria", params)}
              disabled={disabled}
              onClick={props.onReset}
            >
              {t("admin.users.reset_password")}
            </button>
          )}
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
                {(user.is_agent ? AGENT_ROLES : ROLES).map((r) => (
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
          {user.is_agent ? (
            <button
              type="button"
              data-action="keys"
              aria-label={t("admin.users.keys_aria", params)}
              onClick={props.onKeys}
            >
              {t("admin.users.keys")}
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

const KEYS_KEY = ["admin", "agent-keys"] as const;
// Allowed key lifetimes in days (007/FR-9); sent as a JSON integer, the server is strict.
const TTL_DAYS: readonly number[] = [30, 90, 180, 365];
const DEFAULT_TTL_DAYS = 90;

// Display time is Europe/Moscow (NFR-5), the same format as the audit log; the API speaks UTC.
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function when(iso: string): string {
  return WHEN.format(new Date(iso));
}

function keyStateText(key: ApiKeyInfo): string {
  switch (key.state) {
    case "active":
      return t("admin.keys.state_active");
    case "expired":
      return t("admin.keys.state_expired");
    case "revoked":
      return key.revoked_at === null
        ? t("admin.keys.state_revoked")
        : t("admin.keys.state_revoked_at", { when: when(key.revoked_at) });
  }
}

interface KeyRowProps {
  apiKey: ApiKeyInfo;
  disabled: boolean;
  onRevoke: () => void;
}

// The list has no secret and no part of it (007/FR-7).
function KeyRow({ apiKey, disabled, onRevoke }: KeyRowProps) {
  return (
    <tr data-key-id={apiKey.id}>
      <td data-field="id">{apiKey.id}</td>
      <td data-field="name">{apiKey.name}</td>
      <td data-field="issued">
        {apiKey.created_by === null ? t("admin.keys.issuer_unknown") : <UserName user={apiKey.created_by} />},{" "}
        {when(apiKey.created_at)}
      </td>
      <td data-field="expires_at">{when(apiKey.expires_at)}</td>
      <td data-field="last_used_at">
        {apiKey.last_used_at === null ? t("admin.keys.never_used") : when(apiKey.last_used_at)}
      </td>
      <td data-field="state">{keyStateText(apiKey)}</td>
      <td>
        {apiKey.state === "active" ? (
          <button
            type="button"
            data-action="revoke-key"
            aria-label={t("admin.keys.revoke_aria", { name: apiKey.name })}
            disabled={disabled}
            onClick={onRevoke}
          >
            {t("admin.keys.revoke")}
          </button>
        ) : null}
      </td>
    </tr>
  );
}

interface IssuedSecret {
  name: string;
  secret: string;
}

interface SecretDialogProps {
  issued: IssuedSecret;
  onClose: () => void;
  /** Called when the dialog goes away: the focus goes back into the keys section. */
  returnFocus: () => void;
}

/**
 * One-time view of a new key secret (007/FR-6, plan PD-17). Closed only by its button: no
 * Escape and no overlay click, so the secret is not lost by accident. The secret is never
 * logged, stored or put into an attribute.
 */
function SecretDialog({ issued, onClose, returnFocus }: SecretDialogProps) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [copy, setCopy] = useState<"done" | "failed" | null>(null);

  // The secret is set as the DOM property only (a `value` prop would be mirrored into the
  // value attribute) and wiped when the dialog goes away.
  useEffect(() => {
    const input = inputRef.current;
    if (input === null) return undefined;
    input.value = issued.secret;
    input.focus();
    input.select();
    return () => {
      input.value = "";
      returnFocus();
    };
  }, [issued.secret, returnFocus]);

  async function onCopy(): Promise<void> {
    setCopy(null);
    try {
      await navigator.clipboard.writeText(issued.secret);
      setCopy("done");
    } catch {
      // The clipboard may be unavailable or denied: the dialog stays, the key can be copied by hand.
      setCopy("failed");
    }
  }

  // Tab stays inside the dialog (NFR-7).
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== "Tab") return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("input, button"));
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    const active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="ui-overlay">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-warning`}
        className="ui-dialog"
        onKeyDown={onKeyDown}
      >
        <h2 id={`${id}-title`}>{t("admin.keys.secret_title", { name: issued.name })}</h2>
        <p id={`${id}-warning`}>{t("admin.keys.secret_warning")}</p>
        <div className="ui-field">
          <label htmlFor={`${id}-secret`}>{t("admin.keys.secret_label")}</label>
          <input
            id={`${id}-secret`}
            ref={inputRef}
            type="text"
            readOnly
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        </div>
        <div role="status">{copy === "done" ? <p>{t("admin.keys.copied")}</p> : null}</div>
        {copy === "failed" ? (
          <p role="alert" className="ui-error">
            {t("admin.keys.copy_failed")}
          </p>
        ) : null}
        <div className="ui-actions">
          <button type="button" data-action="copy-key" onClick={() => void onCopy()}>
            {t("admin.keys.copy")}
          </button>
          <button type="button" data-action="close-key" onClick={onClose}>
            {t("admin.keys.close")}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Keys of one agent account: list, issue with a one-time secret, revoke (007/FR-40). */
function AgentKeys({ user }: { user: AdminUser }) {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const headingId = useId();
  const ttlId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const [page, setPage] = useState(1);
  const [name, setName] = useState("");
  const [ttl, setTtl] = useState(DEFAULT_TTL_DAYS);
  const [pending, setPending] = useState(false);
  const [revoking, setRevoking] = useState<ApiKeyInfo | null>(null);
  // The secret lives in this state only (PD-17): no useMutation, no query cache; null after close.
  const [issued, setIssued] = useState<IssuedSecret | null>(null);

  const keys = useQuery({
    queryKey: [...KEYS_KEY, user.id, page],
    queryFn: () => listApiKeys(user.id, { page }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  // A finished action may leave the focus on <body> (its button got disabled or removed).
  useEffect(() => {
    if (pending) return;
    const active = document.activeElement;
    if (active === null || active === document.body) headingRef.current?.focus();
  }, [pending]);

  const returnFocus = useCallback(() => {
    const submit = submitRef.current;
    if (submit !== null && !submit.disabled) submit.focus();
    else headingRef.current?.focus();
  }, []);

  /** One action at a time; the list is reloaded after a success. */
  async function run(task: () => Promise<void>): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await task();
      setRevoking(null);
      await queryClient.invalidateQueries({ queryKey: [...KEYS_KEY, user.id] });
    } catch (e) {
      setRevoking(null);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
    busy.current = false;
    setPending(false);
  }

  function onIssue(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (busy.current) return;
    const keyName = name.trim();
    if (keyName === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    const expiresInDays = ttl;
    void run(async () => {
      // A direct call, not useMutation: the mutation cache would keep the response (PD-17).
      const result = await issueApiKey(user.id, { name: keyName, expires_in_days: expiresInDays });
      setIssued({ name: result.key.name, secret: result.secret });
      setName("");
    });
  }

  function onConfirmRevoke(): void {
    if (revoking === null) return;
    const keyId = revoking.id;
    void run(() => revokeApiKey(user.id, keyId));
  }

  const listError =
    keys.isError && alert.message === null
      ? errorMessage(keys.error instanceof ApiError ? keys.error.code : "unknown")
      : null;
  const data = keys.data;

  return (
    <section data-section="agent-keys" aria-labelledby={headingId}>
      <h2 id={headingId} ref={headingRef} tabIndex={-1}>
        {t("admin.keys.title", { login: user.login })}
      </h2>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />

      <form onSubmit={onIssue} noValidate aria-label={t("admin.keys.issue_title")}>
        <TextField
          label={t("admin.keys.name_label")}
          name="name"
          value={name}
          onChange={setName}
          autoComplete="off"
          disabled={pending}
        />
        <div className="ui-field">
          <label htmlFor={ttlId}>{t("admin.keys.ttl_label")}</label>
          <select
            id={ttlId}
            name="expires_in_days"
            value={String(ttl)}
            disabled={pending}
            onChange={(e) => setTtl(Number(e.target.value))}
          >
            {TTL_DAYS.map((days) => (
              <option key={days} value={String(days)}>
                {t("admin.keys.ttl_days", { days })}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" ref={submitRef} disabled={pending}>
          {t("admin.keys.issue_submit")}
        </button>
      </form>

      {data === undefined ? (
        keys.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : data.items.length === 0 ? (
        <p role="status">{t("admin.keys.empty")}</p>
      ) : (
        <table className="ui-table" aria-label={t("admin.keys.list_label")}>
          <thead>
            <tr>
              <th scope="col">{t("admin.keys.col_id")}</th>
              <th scope="col">{t("admin.keys.col_name")}</th>
              <th scope="col">{t("admin.keys.col_issued")}</th>
              <th scope="col">{t("admin.keys.col_expires")}</th>
              <th scope="col">{t("admin.keys.col_last_used")}</th>
              <th scope="col">{t("admin.keys.col_state")}</th>
              <th scope="col">{t("admin.keys.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((apiKey) => (
              <KeyRow
                key={apiKey.id}
                apiKey={apiKey}
                disabled={pending}
                onRevoke={() => setRevoking(apiKey)}
              />
            ))}
          </tbody>
        </table>
      )}

      <Pagination
        page={page}
        hasNext={data?.has_next ?? false}
        busy={keys.isPlaceholderData || pending}
        onPage={(next) => {
          alert.clear();
          setPage(next);
        }}
      />

      {revoking === null ? null : (
        <ConfirmDialog
          title={t("admin.keys.revoke_title")}
          message={t("admin.keys.revoke_message", { name: revoking.name })}
          pending={pending}
          onConfirm={onConfirmRevoke}
          onCancel={() => setRevoking(null)}
        />
      )}

      {issued === null ? null : (
        <SecretDialog issued={issued} onClose={() => setIssued(null)} returnFocus={returnFocus} />
      )}
    </section>
  );
}

export function UsersPage({ canAssignRoles = false }: { canAssignRoles?: boolean }) {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const [page, setPage] = useState(1);
  const [login, setLogin] = useState("");
  const [isAgent, setIsAgent] = useState(false);
  const [agentRole, setAgentRole] = useState<Role | "">("user");
  const [notice, setNotice] = useState<string | null>(null);
  const [keysFor, setKeysFor] = useState<AdminUser | null>(null);
  const agentBoxId = useId();
  const agentRoleId = useId();
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [shown, setShown] = useState<ShownPassword | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useFocusHeadingOnArrival(headingRef);
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
    setNotice(null);
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
    if (isAgent) {
      // No password for an agent (007/FR-1): only the login and the role are sent.
      const role = agentRole === "" ? null : agentRole;
      void run(async () => {
        await createAgent({ login: name, role });
        setNotice(t("admin.users.agent_created"));
        setLogin("");
      });
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
      <h1 ref={headingRef} tabIndex={-1}>
        {t("admin.users.title")}
      </h1>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />
      {/* Always present, so the success text is announced when it appears. */}
      <div role="status">{notice === null ? null : <p>{notice}</p>}</div>

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
        <div className="ui-field">
          <div>
            <input
              id={agentBoxId}
              type="checkbox"
              name="is_agent"
              checked={isAgent}
              disabled={disabled}
              onChange={(e) => setIsAgent(e.target.checked)}
            />{" "}
            <label htmlFor={agentBoxId}>{t("admin.users.agent_label")}</label>
          </div>
        </div>
        {isAgent ? (
          <div className="ui-field">
            <label htmlFor={agentRoleId}>{t("admin.users.role_label")}</label>
            <select
              id={agentRoleId}
              name="role"
              value={agentRole}
              disabled={disabled}
              onChange={(e) => setAgentRole(e.target.value as Role | "")}
            >
              {AGENT_ROLES.map((r) => (
                <option key={r} value={r}>
                  {roleText(r)}
                </option>
              ))}
              <option value="">{t("admin.role.none")}</option>
            </select>
          </div>
        ) : null}
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
                onKeys={() => setKeysFor(user)}
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

      {/* A new agent remounts the section: nothing of the previous one (a secret included) survives. */}
      {keysFor === null ? null : <AgentKeys key={keysFor.id} user={keysFor} />}

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
