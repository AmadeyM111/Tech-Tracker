// The way back to an OAuth consent request through the login and the forced password change (spec 028 FR-6).
// Only the consent path with its query is accepted: never an arbitrary address (no open redirect).
export const CONSENT_PATH = "/oauth/authorize";

/** `next` if it is a relative consent request (`/oauth/authorize?...`), otherwise null. */
export function safeConsentNext(next: string | null): string | null {
  if (next === null || !next.startsWith(`${CONSENT_PATH}?`) || next.startsWith("//") || next.includes("\\")) return null;
  return next;
}

export function withNext(path: string, next: string | null): string {
  return next === null ? path : `${path}?next=${encodeURIComponent(next)}`;
}
