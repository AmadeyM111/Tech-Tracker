// Auth endpoints (T23). The only way the auth screens reach the network: every
// call goes through the shared application client and rejects with ApiError.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type LoginRequest = components["schemas"]["LoginRequest"];
export type LoginResponse = components["schemas"]["LoginResponse"];
export type ChangePasswordRequest = components["schemas"]["ChangePasswordRequest"];
export type MeResponse = components["schemas"]["MeResponse"];

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function login(body: LoginRequest): Promise<LoginResponse> {
  const { data } = await getAppClient().POST("/api/v1/auth/login", { body });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function logout(): Promise<void> {
  await getAppClient().POST("/api/v1/auth/logout");
}

export async function changePassword(body: ChangePasswordRequest): Promise<void> {
  await getAppClient().POST("/api/v1/auth/password", { body });
}

/** Current user profile; a flat MeResponse. Rejects with 401/403 when there is no usable session. */
export async function me(): Promise<MeResponse> {
  const { data } = await getAppClient().GET("/api/v1/me");
  if (data === undefined) throw invalidBody(200);
  return data;
}
