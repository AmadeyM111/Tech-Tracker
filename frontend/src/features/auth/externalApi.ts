// External login (spec 029, ADR-0026): providers for the login screen and «Способы входа» in the profile.
// Kept apart from api.ts: those calls are optional, the login screen must work without them.
import { INVALID_RESPONSE, ApiError, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type ProviderName = components["schemas"]["ProviderItem"]["name"];
export type LoginMethods = components["schemas"]["LoginMethods"];
export type LinkedIdentity = components["schemas"]["LinkedIdentity"];

export const LOGIN_METHODS_KEY = ["me", "login-methods"] as const;

function invalidBody(): ApiError {
  return new ApiError(200, INVALID_RESPONSE, "invalid response body");
}

/** Enabled providers (public): the buttons on the login screen. */
export async function listProviders(): Promise<ProviderName[]> {
  const { data } = await getAppClient().GET("/api/v1/auth/external/providers");
  if (data === undefined) throw invalidBody();
  return data.map((p) => p.name);
}

/** Start address of the login: a plain link, the browser navigates (redirect to the provider). */
export function loginStartUrl(provider: ProviderName, remember: boolean): string {
  return `/api/v1/auth/external/${provider}/start${remember ? "?remember=true" : ""}`;
}

export async function getLoginMethods(): Promise<LoginMethods> {
  const { data } = await getAppClient().GET("/api/v1/me/login-methods");
  if (data === undefined) throw invalidBody();
  return data;
}

/** Starts linking under the open session: returns the provider address to navigate to. */
export async function startLink(provider: ProviderName): Promise<string> {
  const { data } = await getAppClient().POST("/api/v1/me/login-methods/{provider}/link", {
    params: { path: { provider } },
  });
  if (data === undefined) throw invalidBody();
  return data.url;
}

export async function unlinkMethod(identityId: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/me/login-methods/{identity_id}", {
    params: { path: { identity_id: identityId } },
  });
}

export async function setInitialPassword(newPassword: string): Promise<void> {
  await getAppClient().POST("/api/v1/me/login-methods/password", {
    body: { new_password: newPassword },
  });
}
