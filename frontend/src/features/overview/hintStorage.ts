// Browser-side memory of the closed AI agent hint card (spec 026, FR-3, Q-6).
// Only localStorage: no request to the server, no migration. Any storage failure (private mode,
// quota, denied access) is swallowed: the card then stays closed only until the page is reloaded.

const KEY_PREFIX = "gtrack.hint.ai_agent.";

function keyOf(userId: string): string {
  return `${KEY_PREFIX}${userId}`;
}

/** True when this user closed the card in this browser; false when the storage cannot be read. */
export function isHintDismissed(userId: string): boolean {
  try {
    return window.localStorage.getItem(keyOf(userId)) !== null;
  } catch {
    return false;
  }
}

/** Remembers the closing for this user; a storage failure is ignored (the card is hidden in memory anyway). */
export function dismissHint(userId: string): void {
  try {
    window.localStorage.setItem(keyOf(userId), "1");
  } catch {
    // Storage is unavailable: there is nothing to remember.
  }
}
