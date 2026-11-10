// Hint card above the heading of the summary screen (spec 026): a local AI agent acts for the user.
// Shown until the user closes it in this browser; there is no way back to a closed card.
// The route (RoleScreen, capability business_access) decides who sees the summary at all.
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { t } from "../../shared/i18n";
import { dismissHint, isHintDismissed } from "./hintStorage";

export function AiAgentHint({ userId, onDismiss }: { userId: string; onDismiss: () => void }) {
  const titleId = useId();
  // Read once, on mount: the closing made on this page is kept in state even if storage fails.
  const [dismissed, setDismissed] = useState(() => isHintDismissed(userId));
  if (dismissed) return null;

  function close(): void {
    dismissHint(userId);
    setDismissed(true);
    // Focus goes to the page heading (FR-6): the button is removed by this render.
    onDismiss();
  }

  return (
    <aside className="ai-card" aria-labelledby={titleId}>
      <h2 id={titleId}>{t("ai_hint.title")}</h2>
      <p>{t("ai_hint.text")}</p>
      <div className="ai-links">
        <Link to="/profile/agents">{t("ai_hint.link_tokens")}</Link>
        <Link to="/profile/agents#claude-code-instructions">{t("ai_hint.link_instructions")}</Link>
      </div>
      <button type="button" className="ui-btn-secondary ai-close" aria-label={t("ai_hint.close_aria")} onClick={close}>
        {t("ai_hint.close")}
      </button>
    </aside>
  );
}
