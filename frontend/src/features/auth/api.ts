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
export type RegistrationRequest = components["schemas"]["RegistrationRequest"];
export type RegistrationConfirm = components["schemas"]["RegistrationConfirm"];
export type RegistrationConfirmed = components["schemas"]["RegistrationConfirmed"];
export type SetNameRequest = components["schemas"]["SetNameRequest"];

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

// «Запомнить меня» (spec 029 FR-5) по умолчанию выключено: тело всегда содержит remember.
export async function login(
  body: Omit<LoginRequest, "remember"> & { remember?: boolean },
): Promise<LoginResponse> {
  const { data } = await getAppClient().POST("/api/v1/auth/login", {
    body: { ...body, remember: body.remember ?? false },
  });
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

// The answer is the same for a free and a taken address (FR-4), so the form shows one text in both cases.
export async function requestRegistration(body: RegistrationRequest): Promise<void> {
  await getAppClient().POST("/api/v1/auth/registration/request", { body });
}

// The token travels only in the request body; it is sent on the confirm button press only.
// v0.5: the answer names the login the server created for this account (the token holder sees it once).
export async function confirmRegistration(token: string): Promise<string> {
  const body: RegistrationConfirm = { token };
  const { data } = await getAppClient().POST("/api/v1/auth/registration/confirm", { body });
  if (data === undefined) throw invalidBody(200);
  return data.login;
}

// AC-34: the user changes own first and last name; the answer is the refreshed profile (MeResponse).
export async function updateMyName(body: SetNameRequest): Promise<MeResponse> {
  const { data } = await getAppClient().PUT("/api/v1/me/name", { body });
  if (data === undefined) throw invalidBody(200);
  return data;
}

// The profile request lives in session.ts (the router reads it independently of the form calls above).
export { me } from "./session";
