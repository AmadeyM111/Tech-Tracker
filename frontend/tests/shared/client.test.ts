// T22: API-клиент (plan §4.14, D-33, FR-45, FR-55, FR-59, FR-66, NFR-6).
//
// Контракт для исполнителя (frontend/src/shared/api/client.ts):
//   export class ApiError extends Error { status: number; code: string;
//                                         detail: string | ErrorDetail[] }
//   export interface NavigationHandlers { onUnauthenticated?(): void;
//       onPasswordChangeRequired?(): void; onNoRole?(): void }
//   export function createApiClient(options?: { baseUrl?: string; fetch?: typeof fetch }
//       & NavigationHandlers): Client<paths>   // openapi-fetch
// Вызовы клиента ОТКЛОНЯЮТСЯ (reject) значением ApiError для любого не-2xx,
// сетевой ошибки и нечитаемого тела. Сеть не используется: fetch передаётся клиенту.
import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient, type NavigationHandlers } from "../../src/shared/api/client";
import clientSource from "../../src/shared/api/client.ts?raw";

const ORIGIN = window.location.origin;
const SECRET = "S3cret-Pa55w0rd!";

type Responder = (req: Request, n: number) => Response | Promise<Response>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function err(status: number, code: string, detail: unknown = "msg"): Response {
  return json(status, { detail, code });
}

function setup(responder: Responder, handlers: NavigationHandlers = {}) {
  const calls: Request[] = [];
  const fetchImpl = vi.fn(async (input: Request) => {
    calls.push(input);
    return responder(input, calls.length);
  });
  const client = createApiClient({
    baseUrl: ORIGIN,
    fetch: fetchImpl as unknown as typeof fetch,
    ...handlers,
  });
  return { client, calls, fetchImpl };
}

function handlers() {
  return {
    onUnauthenticated: vi.fn(),
    onPasswordChangeRequired: vi.fn(),
    onNoRole: vi.fn(),
  };
}

function noRedirects(h: ReturnType<typeof handlers>) {
  expect(h.onUnauthenticated).not.toHaveBeenCalled();
  expect(h.onPasswordChangeRequired).not.toHaveBeenCalled();
  expect(h.onNoRole).not.toHaveBeenCalled();
}

describe("request shape (FR-44, D-33, D-14)", () => {
  it("builds URLs from schema paths exactly once with the /api/v1 prefix", async () => {
    const { client, calls } = setup(() => json(200, {}));
    await client.GET("/api/v1/me");
    const url = new URL(calls[0]!.url);
    expect(url.pathname).toBe("/api/v1/me");
    expect(url.pathname).not.toContain("/api/v1/api/v1");
  });

  it("default baseUrl is the site root: paths in the schema already carry /api/v1", () => {
    expect(clientSource).toMatch(/baseUrl\s*[:=]\s*["']\/["']/);
    expect(clientSource).not.toMatch(/["']\/api\/v1["']/);
  });

  it("sends cookies same-origin", async () => {
    const { client, calls } = setup(() => json(200, {}));
    await client.GET("/api/v1/me");
    expect(calls[0]!.credentials).toBe("same-origin");
  });

  it("GET carries no extra headers (no Content-Type, no X-GT-Background, no Authorization)", async () => {
    const { client, calls } = setup(() => json(200, {}));
    await client.GET("/api/v1/me");
    const h = calls[0]!.headers;
    expect(h.get("x-gt-background")).toBeNull();
    expect(h.get("content-type")).toBeNull();
    expect(h.get("authorization")).toBeNull();
  });

  it("POST with a body sends Content-Type: application/json and the JSON body", async () => {
    const { client, calls } = setup(() => json(200, {}));
    await client.POST("/api/v1/auth/login", { body: { login: "ivan", password: SECRET } });
    const req = calls[0]!;
    expect(req.method).toBe("POST");
    expect(req.headers.get("content-type")).toMatch(/^application\/json/);
    expect(await req.clone().json()).toEqual({ login: "ivan", password: SECRET });
  });

  it("POST without a body (logout) still sends Content-Type: application/json", async () => {
    const { client, calls } = setup(() => new Response(null, { status: 204 }));
    await client.POST("/api/v1/auth/logout");
    expect(calls[0]!.headers.get("content-type")).toMatch(/^application\/json/);
  });

  it("never adds X-GT-Background by default, on any method (FR-59)", async () => {
    const { client, calls } = setup(() => json(200, {}));
    await client.GET("/api/v1/me");
    await client.GET("/api/v1/health");
    await client.POST("/api/v1/auth/login", { body: { login: "a", password: "b" } });
    await client.POST("/api/v1/admin/users/{user_id}/block", {
      params: { path: { user_id: "00000000-0000-0000-0000-000000000001" } },
    });
    await client.PUT("/api/v1/admin/users/{user_id}/role", {
      params: { path: { user_id: "00000000-0000-0000-0000-000000000001" } },
      body: { role: "member" } as never,
    });
    expect(calls).toHaveLength(5);
    for (const c of calls) expect(c.headers.get("x-gt-background")).toBeNull();
  });

  it("204 without a body is success, not an error", async () => {
    const { client } = setup(() => new Response(null, { status: 204 }));
    const res = await client.POST("/api/v1/auth/logout");
    expect(res.response.status).toBe(204);
    expect(res.data).toBeUndefined();
  });
});

describe("error middleware (FR-45)", () => {
  it("turns a non-2xx ErrorResponse into ApiError {status, code, detail}", async () => {
    const { client } = setup(() => err(404, "not_found", "Не найдено"));
    const p = client.GET("/api/v1/admin/audit/{entry_id}", {
      params: { path: { entry_id: "1" } },
    } as never);
    await expect(p).rejects.toBeInstanceOf(ApiError);
    await expect(p).rejects.toMatchObject({ status: 404, code: "not_found", detail: "Не найдено" });
  });

  it("keeps ErrorDetail[] detail of a 422 validation error as a list", async () => {
    const detail = [
      { loc: ["body", "new_password"], msg: "too short", type: "string_too_short" },
      { loc: ["body", "login"], msg: "required", type: "missing" },
    ];
    const { client } = setup(() => err(422, "validation_error", detail));
    const p = client.POST("/api/v1/auth/password", {
      body: { current_password: "x", new_password: "y" },
    });
    await expect(p).rejects.toMatchObject({ status: 422, code: "validation_error", detail });
  });

  it("is an Error subclass with a stable name and message without server detail text", async () => {
    const { client } = setup(() => err(500, "internal_error", "Внутренняя ошибка"));
    const e = await client.GET("/api/v1/me").then(
      () => null,
      (x: unknown) => x,
    );
    expect(e).toBeInstanceOf(Error);
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).status).toBe(500);
    expect((e as ApiError).code).toBe("internal_error");
    expect(typeof (e as ApiError).message).toBe("string");
    // NFR-6: русских литералов в клиенте нет
    expect((e as ApiError).message).not.toMatch(/[Ѐ-ӿ]/);
  });

  it("network failure becomes ApiError with code network_error (status 0)", async () => {
    const { client } = setup(() => {
      throw new TypeError("Failed to fetch");
    });
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });

  it("non-JSON error body (proxy 502) becomes ApiError invalid_response with the HTTP status", async () => {
    const { client } = setup(
      () => new Response("<html>Bad gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } }),
    );
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({
      status: 502,
      code: "invalid_response",
    });
  });

  it("JSON error body of a foreign shape becomes invalid_response", async () => {
    const { client } = setup(() => json(500, { oops: true }));
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({
      status: 500,
      code: "invalid_response",
    });
  });

  it("2xx with an unreadable body becomes invalid_response", async () => {
    const { client } = setup(
      () => new Response("<html>", { status: 200, headers: { "Content-Type": "text/html" } }),
    );
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({
      status: 200,
      code: "invalid_response",
    });
  });

  it.each(["application/octet-stream", "application/pdf"])(
    "2xx %s binary body is not invalid_response and is returned as a Blob",
    async (type) => {
      const bytes = new Uint8Array([0, 255, 1, 2, 0xfe, 0x80]);
      const { client } = setup(
        () => new Response(bytes, { status: 200, headers: { "Content-Type": type } }),
      );
      const res = await client.GET("/api/v1/me", { parseAs: "blob" });
      // Не instanceof: в jsdom глобальный Blob отличается от Blob из Response.blob() (Node 22).
      expect(Object.prototype.toString.call(res.data)).toBe("[object Blob]");
      const blob = res.data as Blob;
      expect(blob.size).toBe(bytes.length);
      expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(bytes));
    },
  );

  it("JSON content type with an unreadable body is still invalid_response", async () => {
    const { client } = setup(
      () => new Response("{not json", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("204 is not read by the middleware", async () => {
    const resp = new Response(null, { status: 204 });
    const clone = vi.spyOn(resp, "clone");
    const text = vi.spyOn(resp, "text");
    const { client } = setup(() => resp);
    await client.POST("/api/v1/auth/logout");
    expect(clone).not.toHaveBeenCalled();
    expect(text).not.toHaveBeenCalled();
  });

  it("2xx responses are returned as data", async () => {
    const { client } = setup(() => json(200, { status: "ok" }));
    const res = await client.GET("/api/v1/health");
    expect(res.data).toEqual({ status: "ok" });
  });
});

describe("navigation callbacks (FR-55, FR-59, FR-66, T17 note)", () => {
  it("401 not_authenticated calls onUnauthenticated once and still rejects", async () => {
    const h = handlers();
    const { client } = setup(() => err(401, "not_authenticated"), h);
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({
      status: 401,
      code: "not_authenticated",
    });
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(1);
    expect(h.onPasswordChangeRequired).not.toHaveBeenCalled();
    expect(h.onNoRole).not.toHaveBeenCalled();
  });

  it("parallel 401s trigger onUnauthenticated exactly once (no redirect loop)", async () => {
    const h = handlers();
    const { client } = setup(() => err(401, "not_authenticated"), h);
    const results = await Promise.allSettled([
      client.GET("/api/v1/me"),
      client.GET("/api/v1/me"),
      client.GET("/api/v1/health"),
    ]);
    expect(results.every((r) => r.status === "rejected")).toBe(true);
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(1);
  });

  it("is re-armed after a successful response (login again without page reload)", async () => {
    const h = handlers();
    let mode: "401" | "200" = "401";
    const { client } = setup(
      () => (mode === "401" ? err(401, "not_authenticated") : json(200, {})),
      h,
    );
    await client.GET("/api/v1/me").catch(() => undefined);
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(1);
    mode = "200";
    await client.POST("/api/v1/auth/login", { body: { login: "a", password: "b" } });
    mode = "401";
    await client.GET("/api/v1/me").catch(() => undefined);
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["POST", "/api/v1/auth/login"],
    ["POST", "/api/v1/auth/logout"],
  ] as const)("401 not_authenticated on %s %s does not redirect (no loop)", async (_m, path) => {
    const h = handlers();
    const { client } = setup(() => err(401, "not_authenticated"), h);
    const call =
      path === "/api/v1/auth/login"
        ? client.POST(path, { body: { login: "a", password: "b" } })
        : client.POST(path);
    await expect(call).rejects.toMatchObject({ status: 401, code: "not_authenticated" });
    noRedirects(h);
  });

  it("401 invalid_credentials (wrong password at login) never redirects", async () => {
    const h = handlers();
    const { client } = setup(() => err(401, "invalid_credentials"), h);
    await expect(
      client.POST("/api/v1/auth/login", { body: { login: "a", password: SECRET } }),
    ).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
    noRedirects(h);
  });

  it("422 invalid_current_password is a form error, not a session end", async () => {
    const h = handlers();
    const { client } = setup(() => err(422, "invalid_current_password"), h);
    await expect(
      client.POST("/api/v1/auth/password", {
        body: { current_password: SECRET, new_password: "another-long-pass-1" },
      }),
    ).rejects.toMatchObject({ status: 422, code: "invalid_current_password" });
    noRedirects(h);
  });

  it("401 not_authenticated on change-password (account blocked meanwhile) ends the session", async () => {
    const h = handlers();
    const { client } = setup(() => err(401, "not_authenticated"), h);
    await expect(
      client.POST("/api/v1/auth/password", {
        body: { current_password: "x", new_password: "another-long-pass-1" },
      }),
    ).rejects.toMatchObject({ status: 401 });
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(1);
  });

  it("403 password_change_required calls onPasswordChangeRequired only", async () => {
    const h = handlers();
    const { client } = setup(() => err(403, "password_change_required"), h);
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({
      status: 403,
      code: "password_change_required",
    });
    expect(h.onPasswordChangeRequired).toHaveBeenCalledTimes(1);
    expect(h.onUnauthenticated).not.toHaveBeenCalled();
    expect(h.onNoRole).not.toHaveBeenCalled();
  });

  it("403 no_role calls onNoRole only", async () => {
    const h = handlers();
    const { client } = setup(() => err(403, "no_role"), h);
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({ status: 403, code: "no_role" });
    expect(h.onNoRole).toHaveBeenCalledTimes(1);
    expect(h.onUnauthenticated).not.toHaveBeenCalled();
    expect(h.onPasswordChangeRequired).not.toHaveBeenCalled();
  });

  it.each([
    [403, "origin_mismatch"],
    [403, "forbidden"],
    [404, "not_found"],
    [500, "internal_error"],
  ] as const)("%i %s is an ApiError without any redirect", async (status, code) => {
    const h = handlers();
    const { client } = setup(() => err(status, code), h);
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({ status, code });
    noRedirects(h);
  });

  it("works without any handlers configured", async () => {
    const { client } = setup(() => err(401, "not_authenticated"));
    await expect(client.GET("/api/v1/me")).rejects.toMatchObject({ status: 401 });
  });
});

describe("secrets never leak (NFR-4, FR-57)", () => {
  const CONSOLE = ["log", "info", "warn", "error", "debug"] as const;

  function spyConsole() {
    return CONSOLE.map((m) => vi.spyOn(console, m).mockImplementation(() => undefined));
  }

  function leaked(spies: ReturnType<typeof spyConsole>): boolean {
    return spies.some((s) => JSON.stringify(s.mock.calls).includes(SECRET));
  }

  it.each([
    ["401 invalid_credentials", () => err(401, "invalid_credentials")],
    ["422 validation_error", () => err(422, "validation_error", [{ loc: ["body", "password"], msg: "bad", type: "x" }])],
    ["502 non-JSON", () => new Response("gateway", { status: 502 })],
    [
      "network error",
      () => {
        throw new TypeError("Failed to fetch");
      },
    ],
  ] as const)("password is absent from ApiError and console on %s", async (_n, responder) => {
    const spies = spyConsole();
    const { client } = setup(responder as Responder);
    const e = await client
      .POST("/api/v1/auth/login", { body: { login: "ivan", password: SECRET } })
      .then(
        () => null,
        (x: unknown) => x,
      );
    expect(e).toBeInstanceOf(ApiError);
    const apiErr = e as ApiError;
    expect(apiErr.message).not.toContain(SECRET);
    expect(String(apiErr)).not.toContain(SECRET);
    expect(JSON.stringify({ ...apiErr, message: apiErr.message })).not.toContain(SECRET);
    expect(String(apiErr.stack ?? "")).not.toContain(SECRET);
    expect(leaked(spies)).toBe(false);
  });

  it("the client does not log through console.* at all on errors", async () => {
    const spies = spyConsole();
    const { client } = setup(() => err(401, "not_authenticated"), handlers());
    await client.GET("/api/v1/me").catch(() => undefined);
    for (const s of spies) expect(s).not.toHaveBeenCalled();
  });
});
