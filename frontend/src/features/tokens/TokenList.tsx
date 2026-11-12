// Table of the user's agent tokens. Only active tokens can be revoked.
// Below 720 px the same table turns into cards through CSS (agent-connect.css): no duplicated markup.
import { t } from "../../shared/i18n";
import "./agent-connect.css";
import { formatMsk, tokenStatus, tokenStatusText } from "./model";
import type { AgentToken } from "./api";

export function TokenList({
  tokens,
  disabled,
  onRevoke,
}: {
  tokens: AgentToken[];
  disabled: boolean;
  onRevoke: (token: AgentToken) => void;
}) {
  return (
    <table className="ui-table agent-tokens" aria-label={t("agent_tokens.list_label")}>
      <thead>
        <tr>
          <th scope="col">{t("agent_tokens.col_name")}</th>
          <th scope="col">{t("agent_tokens.col_created")}</th>
          <th scope="col">{t("agent_tokens.col_expires")}</th>
          <th scope="col">{t("agent_tokens.col_last_used")}</th>
          <th scope="col">{t("agent_tokens.col_status")}</th>
          <th scope="col">{t("agent_tokens.col_actions")}</th>
        </tr>
      </thead>
      <tbody>
        {tokens.map((token) => {
          const status = tokenStatus(token);
          return (
            <tr key={token.id} data-token-id={token.id}>
              <td data-field="name" data-label={t("agent_tokens.col_name")}>{token.name}</td>
              <td data-field="created" data-label={t("agent_tokens.col_created")}>{formatMsk(token.created_at)}</td>
              <td data-field="expires" data-label={t("agent_tokens.col_expires")}>{formatMsk(token.expires_at)}</td>
              <td data-field="last_used" data-label={t("agent_tokens.col_last_used")}>
                {token.last_used_at === null ? t("agent_tokens.never_used") : formatMsk(token.last_used_at)}
              </td>
              <td data-field="status" data-status={status} data-label={t("agent_tokens.col_status")}>
                {tokenStatusText(status)}
              </td>
              <td data-field="actions">
                {status === "active" ? (
                  <button
                    type="button"
                    data-action="revoke-token"
                    aria-label={t("agent_tokens.revoke_aria", { name: token.name })}
                    disabled={disabled}
                    onClick={() => onRevoke(token)}
                  >
                    {t("agent_tokens.revoke")}
                  </button>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
