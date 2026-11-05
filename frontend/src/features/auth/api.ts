// Auth endpoints (T23). The only way the auth screens reach the network: every
// call goes through the shared application client and rejects with ApiError.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type LoginRequest = components["schemas"]["LoginRequest"];
export type LoginResponse = components["schemas"]["LoginResponse"];
export type ChangePasswordRequest = components["schemas"]["ChangePasswordRequest"];
export type PasswordResetRequest = components["schemas"]["PasswordResetRequest"];
export type PasswordResetConfirm = components["schemas"]["PasswordResetConfirm"];
export type PasswordResetStatus = components["schemas"]["PasswordResetStatus"];
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

export async function passwordResetStatus(): Promise<PasswordResetStatus> {
  const { data } = await getAppClient().GET("/api/v1/auth/password-reset/status");
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function requestPasswordReset(body: PasswordResetRequest): Promise<void> {
  await getAppClient().POST("/api/v1/auth/password-reset/request", { body });
}

// The token travels only in the request body.
export async function confirmPasswordReset(body: PasswordResetConfirm): Promise<void> {
  await getAppClient().POST("/api/v1/auth/password-reset/confirm", { body });
}

// The profile request lives in session.ts (the router reads it independently of the form calls above).
export { me } from "./session";
