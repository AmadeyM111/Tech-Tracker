// OAuth consent for cloud MCP clients (spec 028): context of the request, the decision, own grants.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type ConsentContext = components["schemas"]["ConsentContext"];
export type OauthGrant = components["schemas"]["OauthGrantItem"];

export const OAUTH_GRANTS_KEY = ["me", "oauth-grants"] as const;
export type ClientInfo = components["schemas"]["ClientInfo"];
const FIELDS = [
  "response_type",
  "client_id",
  "redirect_uri",
  "code_challenge",
  "code_challenge_method",
  "state",
  "scope",
  "resource",
] as const;

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

/** Checks the authorization request under the user's session; a 422 means a page error, not a redirect. */
export async function getConsentContext(search: URLSearchParams): Promise<ConsentContext> {
  const query: Record<string, string> = {};
  for (const name of FIELDS) {
    const value = search.get(name);
    if (value !== null) query[name] = value;
  }
  const { data } = await getAppClient().GET("/api/v1/oauth/authorize/context", { params: { query } });
  if (data === undefined) throw invalidBody(200);
  return data;
}

/** «Разрешить» / «Отклонить»: returns the address to send the browser to. */
export async function decide(requestToken: string, allow: boolean): Promise<string> {
  const { data } = await getAppClient().POST("/api/v1/oauth/authorize/decision", {
    body: { request_token: requestToken, allow },
  });
  if (data === undefined) throw invalidBody(200);
  return data.redirect_to;
}

export async function listOauthGrants(): Promise<OauthGrant[]> {
  const { data } = await getAppClient().GET("/api/v1/me/oauth-grants");
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function revokeOauthGrant(id: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/me/oauth-grants/{grant_id}", { params: { path: { grant_id: id } } });
}

/** Public: the name of the client of an authorization request, for the login screen (no session yet). */
export async function getClientInfo(search: URLSearchParams): Promise<ClientInfo> {
  const query = { client_id: search.get("client_id") ?? "", redirect_uri: search.get("redirect_uri") ?? "" };
  const { data } = await getAppClient().GET("/api/v1/oauth/client-info", { params: { query } });
  if (data === undefined) throw invalidBody(200);
  return data;
}
