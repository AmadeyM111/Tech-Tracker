import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { TextField } from "../../shared/ui/TextField";
import { useFocusHeadingOnArrival } from "../auth/session";
import "./audit.css";
import { listAudit, type AuditEntry, type EntityType } from "./api";

const ENTITY_TYPES: readonly EntityType[] = [
  "user",
  "project",
  "task",
  "comment",
  "attachment",
  "stage",
  "deal",
];

interface Filters {
  entityType: EntityType | "";
  actorLogin: string;
}

const NO_FILTERS: Filters = { entityType: "", actorLogin: "" };

// Display time is Europe/Moscow (NFR-5); the API speaks UTC.
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function entityText(type: EntityType): string {
  return t(`admin.entity.${type}` as MessageKey);
}

function actorText(entry: AuditEntry): string {
  const { actor } = entry;
  if (actor.kind === "system") return t("admin.audit.actor_system");
  return actor.login ?? actor.id ?? t("admin.audit.actor_system");
}

const ACTION_CODES: readonly string[] = [
  "user.created",
  "user.blocked",
  "user.unblocked",
  "user.password_reset",
  "user.sessions_revoked",
  "user.email_changed",
  "user.password_reset_requested",
  "user.password_reset_completed",
  "user.role_assigned",
  "user.role_changed",
  "user.role_removed",
  "user.self_registered",
  "user.name_changed",
  "project.ownership_transferred",
];
// Field names with a readable text; any other name is shown as it is.
const FIELD_CODES: readonly string[] = ["owner_id", "first_name", "last_name"];
const ROLE_VALUES: readonly string[] = ["tech_admin", "business_admin", "mixed", "user"];

// An unknown action code is shown as it is.
function actionText(code: string): string {
  return ACTION_CODES.includes(code) ? t(`admin.audit.action.${code}` as MessageKey) : code;
}

function fieldText(name: string): string {
  return FIELD_CODES.includes(name) ? t(`admin.audit.field.${name}` as MessageKey) : name;
}

function roleName(value: string | null | undefined): string {
  if (value === null || value === undefined) return t("admin.role.none");
  return ROLE_VALUES.includes(value) ? t(`admin.role.${value}` as MessageKey) : value;
}

// Role names (never the raw keys) for the role events; empty for other actions. The audit API
// gives no old/new owner for project.ownership_transferred (details exist only for user events,
// changes are not exposed, BR-2), so that event shows just the action text.
function detailsText(entry: AuditEntry): string {
  const from = entry.details?.["role_from"];
  const to = entry.details?.["role_to"];
  switch (entry.action) {
    case "user.role_assigned":
      return roleName(to);
    case "user.role_removed":
      return roleName(from);
    case "user.role_changed":
      return t("admin.audit.role_change", { from: roleName(from), to: roleName(to) });
    default:
      return "";
  }
}

// Only metadata is shown (BR-2): which fields changed, never their values. The object id is
// kept in a collapsed block: an administrator works with logins, the id is for support.
function Details({ entry }: { entry: AuditEntry }) {
  return (
    <>
      <span data-field="changed_fields">{entry.changed_fields.map(fieldText).join(", ")}</span>
      <span data-field="details">{detailsText(entry)}</span>
      <details data-field="entity_id" className="audit-id">
        <summary>{t("admin.audit.col_details")}</summary>
        <span className="audit-uuid">{entry.entity_id}</span>
        {entry.entity_deleted ? ` ${t("admin.audit.entity_deleted")}` : ""}
      </details>
    </>
  );
}

function EntryRow({ entry }: { entry: AuditEntry }) {
  return (
    <tr data-entry-id={entry.id}>
      <td data-field="occurred_at">{WHEN.format(new Date(entry.occurred_at))}</td>
      <td data-field="actor">{actorText(entry)}</td>
      <td data-field="action">{actionText(entry.action)}</td>
      <td data-field="entity_type">{entityText(entry.entity_type)}</td>
      <td>
        <Details entry={entry} />
      </td>
    </tr>
  );
}

// Below 720 px the table becomes cards (same data, no horizontal scroll).
function EntryCard({ entry }: { entry: AuditEntry }) {
  const extra = [entry.changed_fields.map(fieldText).join(", "), detailsText(entry)]
    .filter((x) => x !== "")
    .join(" · ");
  return (
    <li data-card-id={entry.id}>
      <span className="c-title">{actionText(entry.action)}</span>
      <span className="c-meta">
        {WHEN.format(new Date(entry.occurred_at))} · {actorText(entry)}
      </span>
      <span className="c-meta">
        {entityText(entry.entity_type)}
        {extra === "" ? "" : `: ${extra}`}
      </span>
      <details className="audit-id">
        <summary>{t("admin.audit.col_details")}</summary>
        <span className="audit-uuid">{entry.entity_id}</span>
        {entry.entity_deleted ? ` ${t("admin.audit.entity_deleted")}` : ""}
      </details>
    </li>
  );
}

export function AuditPage() {
  const typeId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  useFocusHeadingOnArrival(headingRef);
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);

  const audit = useQuery({
    queryKey: ["admin", "audit", page, applied.entityType, applied.actorLogin],
    queryFn: () =>
      listAudit({
        page,
        ...(applied.entityType === "" ? {} : { entityType: applied.entityType }),
        ...(applied.actorLogin === "" ? {} : { actorLogin: applied.actorLogin }),
      }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  function onApply(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setApplied({ entityType: draft.entityType, actorLogin: draft.actorLogin.trim() });
    setPage(1);
  }

  function onReset(): void {
    setDraft(NO_FILTERS);
    setApplied(NO_FILTERS);
    setPage(1);
  }

  const data = audit.data;
  const error = audit.isError
    ? errorMessage(audit.error instanceof ApiError ? audit.error.code : "unknown")
    : null;

  return (
    <section className="ui-wide">
      <h1 ref={headingRef} tabIndex={-1}>
        {t("admin.audit.title")}
      </h1>
      <ErrorAlert message={error} seq={audit.errorUpdateCount} />

      <form className="audit-filters" onSubmit={onApply} noValidate aria-label={t("admin.audit.filters_title")}>
        <div className="ui-field">
          <label htmlFor={typeId}>{t("admin.audit.entity_type_label")}</label>
          <select
            id={typeId}
            name="entity_type"
            value={draft.entityType}
            onChange={(e) => setDraft({ ...draft, entityType: e.target.value as EntityType | "" })}
          >
            <option value="">{t("admin.audit.entity_any")}</option>
            {ENTITY_TYPES.map((type) => (
              <option key={type} value={type}>
                {entityText(type)}
              </option>
            ))}
          </select>
        </div>
        <TextField
          label={t("admin.audit.actor_label")}
          name="actor_login"
          value={draft.actorLogin}
          onChange={(actorLogin) => setDraft({ ...draft, actorLogin })}
          autoComplete="off"
        />
        <button type="submit">{t("admin.audit.apply")}</button>{" "}
        <button type="button" data-action="reset-filters" onClick={onReset}>
          {t("admin.audit.reset")}
        </button>
      </form>

      {data === undefined ? (
        audit.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : data.items.length === 0 ? (
        <p role="status">{t("admin.audit.empty")}</p>
      ) : (
        <>
          <div className="audit-table-wrap">
            <table className="ui-table" aria-label={t("admin.audit.list_label")}>
              <thead>
                <tr>
                  <th scope="col">{t("admin.audit.col_time")}</th>
                  <th scope="col">{t("admin.audit.col_actor")}</th>
                  <th scope="col">{t("admin.audit.col_action")}</th>
                  <th scope="col">{t("admin.audit.col_entity_type")}</th>
                  <th scope="col">{t("admin.audit.col_details")}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
          <ul className="audit-cards" aria-label={t("admin.audit.list_label")}>
            {data.items.map((entry) => (
              <EntryCard key={entry.id} entry={entry} />
            ))}
          </ul>
        </>
      )}

      {/* Аудит #9: пустая первая страница - без пагинации; со страницы > 1 остаётся, чтобы вернуться назад. */}
      {(data?.items.length ?? 0) > 0 || page > 1 ? (
        <Pagination
          page={page}
          hasNext={data?.has_next ?? false}
          busy={audit.isPlaceholderData}
          onPage={setPage}
        />
      ) : null}
    </section>
  );
}
