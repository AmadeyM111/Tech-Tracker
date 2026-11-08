// 019/R8-T21: accounts without a role (AC-30, FR-13a). Only the business admin reaches this page
// (RoleScreen capability "onboard_accounts"); the server checks the role and the target again.
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { assignUserRole, listUnassigned, type UnassignedAccount } from "./api";
import { useFocusHeadingOnArrival } from "../auth/session";

const UNASSIGNED_KEY = ["admin", "unassigned"] as const;

export function UnassignedAccountsPage() {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const [page, setPage] = useState(1);
  const [pending, setPending] = useState(false);
  const [target, setTarget] = useState<UnassignedAccount | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useFocusHeadingOnArrival(headingRef);

  const accounts = useQuery({
    queryKey: [...UNASSIGNED_KEY, page],
    queryFn: () => listUnassigned({ page }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  /**
   * One assignment at a time. The controls stay disabled until the list has been
   * reloaded, so an account that already got its role is never offered again.
   */
  async function assign(account: UnassignedAccount): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await assignUserRole(account.id);
      setTarget(null);
      await queryClient.invalidateQueries({ queryKey: UNASSIGNED_KEY });
    } catch (e) {
      setTarget(null);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
    busy.current = false;
    setPending(false);
  }

  function changePage(next: number): void {
    alert.clear();
    setPage(next);
  }

  const listError =
    accounts.isError && alert.message === null
      ? errorMessage(accounts.error instanceof ApiError ? accounts.error.code : "unknown")
      : null;
  const data = accounts.data;

  return (
    <section className="ui-wide">
      <h1 ref={headingRef} tabIndex={-1}>
        {t("accounts.unassigned_title")}
      </h1>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />

      {data === undefined ? (
        accounts.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : data.items.length === 0 ? (
        <p role="status">{t("accounts.unassigned_empty")}</p>
      ) : (
        <table className="ui-table" aria-label={t("accounts.unassigned_title")}>
          <thead>
            <tr>
              <th scope="col">{t("admin.users.col_login")}</th>
              <th scope="col">{t("admin.users.first_name_column")}</th>
              <th scope="col">{t("admin.users.last_name_column")}</th>
              <th scope="col">{t("admin.users.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((account) => (
              <tr key={account.id} data-user-id={account.id}>
                <td data-field="login">{account.login}</td>
                <td data-field="first_name">{account.first_name || t("admin.users.name_missing")}</td>
                <td data-field="last_name">{account.last_name || t("admin.users.name_missing")}</td>
                <td>
                  <button
                    type="button"
                    data-action="assign-user"
                    disabled={pending}
                    onClick={() => setTarget(account)}
                  >
                    {t("accounts.assign_user")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Pagination
        page={page}
        hasNext={data?.has_next ?? false}
        busy={accounts.isPlaceholderData || pending}
        onPage={changePage}
      />

      {target === null ? null : (
        <ConfirmDialog
          title={t("accounts.assign_title")}
          message={t("accounts.assign_message", { login: target.login })}
          pending={pending}
          onConfirm={() => void assign(target)}
          onCancel={() => setTarget(null)}
        />
      )}
    </section>
  );
}
