// "Облачные клиенты" on the agent access page (spec 028 FR-11): connected OAuth clients, "Отключить" at once.
// The same table turns into cards below 720 px through CSS (agent-connect.css).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { OAUTH_GRANTS_KEY, listOauthGrants, revokeOauthGrant, type OauthGrant } from "../oauth/api";
import "./agent-connect.css";
import { formatMsk } from "./model";

export function CloudClients() {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const [confirming, setConfirming] = useState<OauthGrant | null>(null);
  const [pending, setPending] = useState(false);
  const grants = useQuery({ queryKey: OAUTH_GRANTS_KEY, queryFn: listOauthGrants, retry: false });

  async function onRevoke(): Promise<void> {
    if (confirming === null || busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await revokeOauthGrant(confirming.id);
    } catch (e) {
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
    setConfirming(null);
    await queryClient.invalidateQueries({ queryKey: OAUTH_GRANTS_KEY });
    titleRef.current?.focus();
    busy.current = false;
    setPending(false);
  }

  const data = grants.data;
  const listError = grants.isError ? errorMessage(grants.error instanceof ApiError ? grants.error.code : "unknown") : null;
  return (
    <section data-section="cloud-clients" aria-labelledby="cloud-clients-title" className="cloud-clients">
      <h2 id="cloud-clients-title" ref={titleRef} tabIndex={-1}>
        {t("oauth.clients_title")}
      </h2>
      <p>{t("oauth.clients_intro")}</p>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />
      {data === undefined ? (
        grants.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : data.length === 0 ? (
        <p role="status">{t("oauth.clients_empty")}</p>
      ) : (
        <table className="ui-table agent-tokens cloud-table" aria-label={t("oauth.clients_list_label")}>
          <thead>
            <tr>
              <th scope="col">{t("oauth.col_client")}</th>
              <th scope="col">{t("oauth.col_connected")}</th>
              <th scope="col">{t("oauth.col_last_used")}</th>
              <th scope="col">{t("oauth.col_status")}</th>
              <th scope="col">{t("agent_tokens.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((g) => (
              <tr key={g.id} data-grant-id={g.id}>
                <td data-field="name" data-label={t("oauth.col_client")}>
                  {g.client_name}
                  <span className="cloud-host"> · {g.redirect_host}</span>
                </td>
                <td data-field="created" data-label={t("oauth.col_connected")}>
                  {formatMsk(g.created_at)}
                </td>
                <td data-field="last_used" data-label={t("oauth.col_last_used")}>
                  {g.last_used_at === null ? t("agent_tokens.never_used") : formatMsk(g.last_used_at)}
                </td>
                <td data-field="status" data-label={t("oauth.col_status")}>
                  {t(g.revoked_at === null ? "oauth.status_active" : "oauth.status_revoked")}
                </td>
                <td data-field="actions">
                  {g.revoked_at === null ? (
                    <button
                      type="button"
                      data-action="disconnect-client"
                      aria-label={t("oauth.disconnect_aria", { client: g.client_name })}
                      disabled={pending}
                      onClick={() => setConfirming(g)}
                    >
                      {t("oauth.disconnect")}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {confirming === null ? null : (
        <ConfirmDialog
          title={t("oauth.disconnect_title")}
          message={t("oauth.disconnect_message", { client: confirming.client_name })}
          confirmLabel={t("oauth.disconnect")}
          pending={pending}
          onConfirm={() => void onRevoke()}
          onCancel={() => setConfirming(null)}
        />
      )}
    </section>
  );
}
