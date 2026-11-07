// Personal agent access tokens (ADR-0018, PN-15). Goes through the shared application client and
// rejects with ApiError. The token value exists only in the result of createAgentToken: it is never
// put into the TanStack Query cache (no mutation cache either), the page keeps it in local state only.
import { useQuery } from "@tanstack/react-query";

import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type AgentToken = components["schemas"]["TokenItem"];
export type CreatedAgentToken = components["schemas"]["TokenCreated"];

export const AGENT_TOKENS_KEY = ["me", "tokens"] as const;

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function listAgentTokens(): Promise<AgentToken[]> {
  const { data } = await getAppClient().GET("/api/v1/me/tokens");
  if (data === undefined) throw invalidBody(200);
  return data;
}

/** The returned `token` value is shown once; the caller must not store it anywhere but local state. */
export async function createAgentToken(name: string): Promise<CreatedAgentToken> {
  const { data } = await getAppClient().POST("/api/v1/me/tokens", { body: { name } });
  if (data === undefined) throw invalidBody(201);
  return data;
}

export async function revokeAgentToken(id: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/me/tokens/{token_id}", {
    params: { path: { token_id: id } },
  });
}

/** The current user's tokens, newest first (server order). */
export function useAgentTokens() {
  return useQuery({
    queryKey: AGENT_TOKENS_KEY,
    queryFn: listAgentTokens,
    retry: false,
  });
}
