// T23: features/auth/api.ts поверх общего клиента: пути, тела, ApiError.
import { describe, expect, it, vi } from "vitest";

import { changePassword, confirmPasswordReset, login, logout, me, passwordResetStatus, requestPasswordReset } from "../../../src/features/auth/api";
import { ApiError } from "../../../src/shared/api/client";

const j = (s: number, b: unknown) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

function stub(resp: () => Response) {
  const calls: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (r: Request) => (calls.push(r), resp())));
  return calls;
}

describe("auth api (T23)", () => {
  it("login_posts_json_to_auth_login_and_returns_user", async () => {
    const user = { id: "11111111-1111-4111-8111-111111111111", login: "a", role: null, must_change_password: false };
    const calls = stub(() => j(200, { user }));
    const res = await login({ login: "a", password: "pw-pw-pw-pw-pw" });
    expect(res.user.login).toBe("a");
    const req = calls[0]!;
    expect(new URL(req.url).pathname).toBe("/api/v1/auth/login");
    expect(req.method).toBe("POST");
    expect(await req.json()).toEqual({ login: "a", password: "pw-pw-pw-pw-pw" });
    expect(req.url).not.toContain("pw-pw");
  });

  it("login_rejects_with_api_error_code", async () => {
    stub(() => j(401, { detail: "bad", code: "invalid_credentials" }));
    await expect(login({ login: "a", password: "b" })).rejects.toMatchObject({ code: "invalid_credentials", status: 401 });
    await expect(login({ login: "a", password: "b" })).rejects.toBeInstanceOf(ApiError);
  });

  it("change_password_posts_to_auth_password_and_logout_to_auth_logout", async () => {
    const calls = stub(() => new Response(null, { status: 204 }));
    await changePassword({ current_password: "old", new_password: "new" });
    await logout();
    expect(new URL(calls[0]!.url).pathname).toBe("/api/v1/auth/password");
    expect(await calls[0]!.json()).toEqual({ current_password: "old", new_password: "new" });
    expect(new URL(calls[1]!.url).pathname).toBe("/api/v1/auth/logout");
    expect(calls[1]!.method).toBe("POST");
  });

  it("me_gets_api_v1_me_and_returns_profile", async () => {
    const body = { id: "11111111-1111-4111-8111-111111111111", login: "a", role: "user", must_change_password: false, capabilities: [] };
    const calls = stub(() => j(200, body));
    const res = await me();
    expect(res).toMatchObject({ login: "a", role: "user", must_change_password: false });
    expect(new URL(calls[0]!.url).pathname).toBe("/api/v1/me");
    expect(calls[0]!.method).toBe("GET");
  });

  it("me_rejects_with_api_error_code", async () => {
    stub(() => j(403, { detail: "x", code: "no_role" }));
    await expect(me()).rejects.toMatchObject({ code: "no_role", status: 403 });
  });

  it("password_reset_status_gets_status_and_returns_enabled", async () => {
    const calls = stub(() => j(200, { enabled: true }));
    expect(await passwordResetStatus()).toEqual({ enabled: true });
    expect(new URL(calls[0]!.url).pathname).toBe("/api/v1/auth/password-reset/status");
    expect(calls[0]!.method).toBe("GET");
  });

  it("request_password_reset_posts_email", async () => {
    const calls = stub(() => new Response(null, { status: 204 }));
    await requestPasswordReset({ email: "a@x.ru" });
    expect(new URL(calls[0]!.url).pathname).toBe("/api/v1/auth/password-reset/request");
    expect(calls[0]!.method).toBe("POST");
    expect(await calls[0]!.json()).toEqual({ email: "a@x.ru" });
  });

  it("confirm_password_reset_posts_token_and_password_body_only", async () => {
    const calls = stub(() => new Response(null, { status: 204 }));
    await confirmPasswordReset({ token: "tok-123", new_password: "New-Pass-12345" });
    expect(new URL(calls[0]!.url).pathname).toBe("/api/v1/auth/password-reset/confirm");
    expect(calls[0]!.method).toBe("POST");
    expect(await calls[0]!.json()).toEqual({ token: "tok-123", new_password: "New-Pass-12345" });
    expect(calls[0]!.url).not.toContain("tok-123");
  });

  it("password_reset_calls_reject_with_api_error_code", async () => {
    stub(() => j(404, { detail: "x", code: "feature_disabled" }));
    await expect(requestPasswordReset({ email: "a@x.ru" })).rejects.toMatchObject({ code: "feature_disabled", status: 404 });
    await expect(passwordResetStatus()).rejects.toBeInstanceOf(ApiError);
  });
});
