// Pure helpers of the agent access section: status, display time, name check, error text.
import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import type { AgentToken } from "./api";

/** Same limit as the server (NAME_MAX_LENGTH, code points). */
export const NAME_MAX_LENGTH = 64;

export type TokenStatus = "active" | "revoked" | "expired";

/**
 * `active` is computed by the server against its clock (`expires_at` and `revoked_at` included):
 * revoked when `revoked_at` is set, expired when it is not active any more, otherwise active.
 */
export function tokenStatus(token: Pick<AgentToken, "active" | "revoked_at">): TokenStatus {
  if (token.revoked_at !== null) return "revoked";
  return token.active ? "active" : "expired";
}

const STATUS_KEY: Record<TokenStatus, MessageKey> = {
  active: "agent_tokens.status_active",
  revoked: "agent_tokens.status_revoked",
  expired: "agent_tokens.status_expired",
};

export function tokenStatusText(status: TokenStatus): string {
  return t(STATUS_KEY[status]);
}

// Display time is Europe/Moscow (NFR-5); the API speaks UTC (same format as the audit log).
const WHEN = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatMsk(iso: string): string {
  return WHEN.format(new Date(iso));
}

/** Client-side check of the token name; the server repeats it (422 validation_error). */
export function nameProblem(name: string): MessageKey | null {
  const value = name.trim();
  if (value === "") return "agent_tokens.name_required";
  if ([...value].length > NAME_MAX_LENGTH) return "agent_tokens.name_too_long";
  return null;
}

/** User-facing text of a failed request; raw codes are never shown. */
export function failureMessage(error: unknown): string {
  return errorMessage(error instanceof ApiError ? error.code : "unknown");
}

export type AgentClient = "claude" | "other";

/**
 * The text the user pastes into the agent (docs/ai-integration.md). The address is the origin of this
 * page plus /mcp; the token value is put in only here, for the one moment it is shown.
 */
export function connectText(client: AgentClient, origin: string, token: string): string {
  const url = `${origin}/mcp`;
  if (client === "claude") {
    return `claude mcp add --transport http gtrack ${url} --header "Authorization: Bearer ${token}"`;
  }
  return JSON.stringify(
    { mcpServers: { gtrack: { type: "http", url, headers: { Authorization: `Bearer ${token}` } } } },
    null,
    2,
  );
}
