// The token issued by the last create request: shown once, copied by the user, then dismissed.
// Rendered with key=token id by the page, so copy state never leaks into the next token.
import { useEffect, useId, useRef, useState } from "react";

import { t } from "../../shared/i18n";
import type { CreatedAgentToken } from "./api";

export function IssuedToken({ token, onDismiss }: { token: CreatedAgentToken; onDismiss: () => void }) {
  const id = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  // The panel appears in response to an action: the focus goes to it (NFR-7).
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  async function copy(): Promise<void> {
    setCopied(false);
    setCopyFailed(false);
    try {
      await navigator.clipboard.writeText(token.token);
      setCopied(true);
    } catch {
      // No clipboard permission or no secure context: the field stays selectable for manual copy.
      setCopyFailed(true);
    }
  }

  return (
    <section className="ui-secret" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>
        {t("agent_tokens.issued_title")}
      </h2>
      <p>
        <strong>{t("agent_tokens.issued_warning")}</strong>
      </p>
      <div className="ui-field">
        <label htmlFor={`${id}-value`}>{t("agent_tokens.token_label")}</label>
        <input
          id={`${id}-value`}
          type="text"
          readOnly
          value={token.token}
          autoComplete="off"
          spellCheck={false}
          onFocus={(event) => event.currentTarget.select()}
        />
      </div>
      <div className="ui-actions">
        <button type="button" data-action="copy-token" onClick={() => void copy()}>
          {t("agent_tokens.copy")}
        </button>
        <button type="button" data-action="dismiss-token" onClick={onDismiss}>
          {t("agent_tokens.dismiss")}
        </button>
      </div>
      {copied ? <p role="status">{t("agent_tokens.copied")}</p> : null}
      {copyFailed ? (
        <p role="alert" className="ui-error">
          {t("agent_tokens.copy_failed")}
        </p>
      ) : null}
    </section>
  );
}
