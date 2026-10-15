import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { TextField } from "../../shared/ui/TextField";
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
  actorId: string;
}

const NO_FILTERS: Filters = { entityType: "", actorId: "" };

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
  "user.role_assigned",
  "user.role_changed",
  "user.role_removed",
];
const ROLE_VALUES: readonly string[] = ["tech_admin", "business_admin", "mixed", "user"];

// An unknown action code is shown as it is.
function actionText(code: string): string {
  return ACTION_CODES.includes(code) ? t(`admin.audit.action.${code}` as MessageKey) : code;
}

function roleName(value: string | null | undefined): string {
  if (value === null || value === undefined) return t("admin.role.none");
  return ROLE_VALUES.includes(value) ? t(`admin.role.${value}` as MessageKey) : value;
}

// Role names (never the raw keys) for the role events; empty for other actions.
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

// Only metadata is shown (BR-2): which fields changed, never their values.
function EntryRow({ entry }: { entry: AuditEntry }) {
  return (
    <tr data-entry-id={entry.id}>
      <td data-field="occurred_at">{WHEN.format(new Date(entry.occurred_at))}</td>
      <td data-field="actor">{actorText(entry)}</td>
      <td data-field="action">{actionText(entry.action)}</td>
      <td data-field="entity_type">{entityText(entry.entity_type)}</td>
      <td data-field="entity_id">
        {entry.entity_id}
        {entry.entity_deleted ? ` ${t("admin.audit.entity_deleted")}` : ""}
      </td>
      <td data-field="changed_fields">{entry.changed_fields.join(", ")}</td>
      <td data-field="details">{detailsText(entry)}</td>
    </tr>
  );
}

export function AuditPage() {
  const typeId = useId();
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);

  const audit = useQuery({
    queryKey: ["admin", "audit", page, applied.entityType, applied.actorId],
    queryFn: () =>
      listAudit({
        page,
        ...(applied.entityType === "" ? {} : { entityType: applied.entityType }),
        ...(applied.actorId === "" ? {} : { actorId: applied.actorId }),
      }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  function onApply(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setApplied({ entityType: draft.entityType, actorId: draft.actorId.trim() });
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
      <h1>{t("admin.audit.title")}</h1>
      <ErrorAlert message={error} seq={audit.errorUpdateCount} />

      <form onSubmit={onApply} noValidate aria-label={t("admin.audit.filters_title")}>
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
          name="actor_id"
          value={draft.actorId}
          onChange={(actorId) => setDraft({ ...draft, actorId })}
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
        <table className="ui-table" aria-label={t("admin.audit.list_label")}>
          <thead>
            <tr>
              <th scope="col">{t("admin.audit.col_time")}</th>
              <th scope="col">{t("admin.audit.col_actor")}</th>
              <th scope="col">{t("admin.audit.col_action")}</th>
              <th scope="col">{t("admin.audit.col_entity_type")}</th>
              <th scope="col">{t("admin.audit.col_entity_id")}</th>
              <th scope="col">{t("admin.audit.col_fields")}</th>
              <th scope="col">{t("admin.audit.col_details")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((entry) => (
              <EntryRow key={entry.id} entry={entry} />
            ))}
          </tbody>
        </table>
      )}

      <Pagination
        page={page}
        hasNext={data?.has_next ?? false}
        busy={audit.isPlaceholderData}
        onPage={setPage}
      />
    </section>
  );
}
