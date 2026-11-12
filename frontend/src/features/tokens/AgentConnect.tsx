// "Подключить ИИ-агента": one field with the ready text, a client switch and a one-click copy (spec: simple access).
// The token exists only in the props of the page state while it is shown: it is not stored or logged anywhere.
import { useEffect, useId, useRef, useState } from "react";

import { t } from "../../shared/i18n";
import type { CreatedAgentToken } from "./api";
import { connectText, type AgentClient } from "./model";
import "./agent-connect.css";

const CLIENTS: readonly AgentClient[] = ["claude", "other"];

export function AgentConnect({ token, onDismiss }: { token: CreatedAgentToken | null; onDismiss: () => void }) {
  const id = useId();
  const noteRef = useRef<HTMLParagraphElement>(null);
  const [client, setClient] = useState<AgentClient>("claude");
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  // The text appears in response to an action: the focus goes to the "token created" note (NFR-7).
  useEffect(() => {
    if (token !== null) noteRef.current?.focus();
  }, [token]);

  const text = token === null ? "" : connectText(client, window.location.origin, token.token);

  async function copy(): Promise<void> {
    setCopied(false);
    setCopyFailed(false);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // No clipboard permission or no secure context: the field is selected for a manual copy.
      area.current?.select();
      setCopyFailed(true);
    }
  }

  return (
    <div className="agent-connect">
      {token === null ? null : (
        <>
          <p ref={noteRef} tabIndex={-1} className="agent-note">
            <strong>{t("agent_connect.created_title")}</strong> {t("agent_connect.created_text")}
          </p>
          <div className="agent-seg" role="group" aria-label={t("agent_connect.client_label")}>
            {CLIENTS.map((c) => (
              <button
                key={c}
                type="button"
                data-client={c}
                aria-pressed={client === c}
                onClick={() => {
                  setClient(c);
                  setCopied(false);
                  setCopyFailed(false);
                }}
              >
                {t(`agent_connect.client_${c}`)}
              </button>
            ))}
          </div>
          {client === "other" ? (
            <p className="agent-hint" data-role="other-client-hint">
              {t("agent_connect.other_hint")}
            </p>
          ) : null}
        </>
      )}
      <label htmlFor={`${id}-text`} className="agent-label">
        {t("agent_connect.field_label")}
      </label>
      <textarea
        id={`${id}-text`}
        ref={area}
        readOnly
        disabled={token === null}
        spellCheck={false}
        autoComplete="off"
        value={token === null ? "" : text}
        placeholder={token === null ? t("agent_connect.placeholder") : undefined}
        onFocus={(event) => event.currentTarget.select()}
        rows={token === null ? 3 : client === "claude" ? 4 : 10}
      />
      <p className={token === null ? "agent-hint" : "agent-warn"}>
        {token === null ? t("agent_connect.hint_before") : t("agent_connect.warn_after")}
      </p>
      {token === null ? null : (
        <p className="agent-warn" data-role="no-chat-warning">
          {t("agent_connect.no_chat_warning")}
        </p>
      )}
      <div className="agent-copy-row">
        <button type="button" data-action="copy-token" disabled={token === null} onClick={() => void copy()}>
          {t("agent_tokens.copy")}
        </button>
        {token === null ? null : (
          <button type="button" data-action="dismiss-token" onClick={onDismiss}>
            {t("agent_tokens.dismiss")}
          </button>
        )}
        {copied ? <span role="status">{t("agent_connect.copied")}</span> : null}
        {copyFailed ? (
          <span role="alert" className="ui-error">
            {t("agent_tokens.copy_failed")}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** Collapsed short notes below the connect block (replaces the long Claude Code instruction). */
export function AgentMore() {
  return (
    <details className="agent-more" id="agent-more">
      <summary>{t("agent_connect.more_title")}</summary>
      <ol>
        <li>{t("agent_connect.more_1")}</li>
        <li>{t("agent_connect.more_2")}</li>
        <li>{t("agent_connect.more_3")}</li>
        <li>{t("agent_connect.more_4")}</li>
      </ol>
    </details>
  );
}
