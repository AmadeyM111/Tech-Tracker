// Typed API client (plan §4.14, D-33). The only module allowed to call fetch
// (see eslint.config.js). Every non-2xx response, network failure and
// unreadable body rejects with ApiError. No console.* calls here and no
// request data in errors: passwords and tokens must never leave the request.
import createClient, { type Client, type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type ErrorDetail = components["schemas"]["ErrorDetail"];

export const NETWORK_ERROR = "network_error";
export const INVALID_RESPONSE = "invalid_response";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string | ErrorDetail[];

  constructor(status: number, code: string, detail: string | ErrorDetail[]) {
    // Server text is kept in `detail` only; the message stays machine-readable.
    super(`API error ${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export interface NavigationHandlers {
  /** 401 not_authenticated: the session is over; navigate to the login page. */
  onUnauthenticated?: () => void;
  /** 403 password_change_required: only change-password and logout are allowed. */
  onPasswordChangeRequired?: () => void;
  /** 403 no_role: show the "no role" screen. */
  onNoRole?: () => void;
}

export interface ApiClientOptions extends NavigationHandlers {
  /** Site root by default: schema paths already carry the /api/v1 prefix. */
  baseUrl?: string;
  fetch?: typeof fetch;
}

type Redirect = "unauthenticated" | "passwordChangeRequired" | "noRole";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

// A 401 here is a normal outcome, not an ended session: redirecting would loop.
const NO_UNAUTH_REDIRECT_PATHS: ReadonlySet<string> = new Set([
  "/api/v1/auth/login",
  "/api/v1/auth/logout",
]);

function isErrorDetail(value: unknown): value is ErrorDetail {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v["loc"]) && typeof v["msg"] === "string" && typeof v["type"] === "string";
}

function parseErrorBody(text: string): { code: string; detail: string | ErrorDetail[] } | null {
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof body !== "object" || body === null) return null;
  const { code, detail } = body as Record<string, unknown>;
  if (typeof code !== "string" || code === "") return null;
  if (typeof detail === "string") return { code, detail };
  if (Array.isArray(detail) && detail.every(isErrorDetail)) return { code, detail };
  return null;
}

function isJsonContentType(response: Response): boolean {
  const type = (response.headers.get("Content-Type") ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
  return type === "application/json" || type.endsWith("+json");
}

function parsesAsJson(text: string): boolean {
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

export function createApiClient(options: ApiClientOptions = {}): Client<paths> {
  const { baseUrl = "/", fetch: fetchImpl, onUnauthenticated, onPasswordChangeRequired, onNoRole } =
    options;

  // Each redirect fires once per series (parallel requests fail together);
  // any successful response re-arms them (login again without a page reload).
  const fired = new Set<Redirect>();

  function redirectOnce(kind: Redirect, handler: (() => void) | undefined): void {
    if (fired.has(kind)) return;
    fired.add(kind);
    handler?.();
  }

  const middleware: Middleware = {
    onRequest({ request }) {
      // Unsafe methods always declare JSON, even without a body (logout, block).
      if (!SAFE_METHODS.has(request.method) && !request.headers.has("Content-Type")) {
        request.headers.set("Content-Type", "application/json");
      }
    },

    async onResponse({ response, schemaPath, options: requestOptions }) {
      if (response.ok) {
        fired.clear();
        // Only bodies the caller will parse as JSON are checked: downloads
        // (parseAs: "blob" etc.) and 204 responses are passed through unread.
        if (response.status !== 204 && requestOptions.parseAs === "json") {
          const text = await response.clone().text();
          if (text !== "" && !(isJsonContentType(response) && parsesAsJson(text))) {
            throw new ApiError(response.status, INVALID_RESPONSE, "invalid response body");
          }
        }
        return undefined;
      }

      const parsed = parseErrorBody(await response.clone().text().catch(() => ""));
      if (parsed === null) {
        throw new ApiError(response.status, INVALID_RESPONSE, "invalid response body");
      }
      const { code, detail } = parsed;
      if (response.status === 401 && code === "not_authenticated") {
        if (!NO_UNAUTH_REDIRECT_PATHS.has(schemaPath)) {
          redirectOnce("unauthenticated", onUnauthenticated);
        }
      } else if (response.status === 403 && code === "password_change_required") {
        redirectOnce("passwordChangeRequired", onPasswordChangeRequired);
      } else if (response.status === 403 && code === "no_role") {
        redirectOnce("noRole", onNoRole);
      }
      throw new ApiError(response.status, code, detail);
    },

    onError({ error }) {
      // A cancelled request (TanStack Query signal) is not a network failure.
      if (error instanceof Error && error.name === "AbortError") return undefined;
      return new ApiError(0, NETWORK_ERROR, "network error");
    },
  };

  const client = createClient<paths>({
    baseUrl,
    credentials: "same-origin",
    ...(fetchImpl === undefined ? {} : { fetch: fetchImpl }),
  });
  client.use(middleware);
  return client;
}

// One client for the whole application (plan §4.14): navigation callbacks are
// registered once at the app level (AppRoutes) and shared by every request.
let appHandlers: NavigationHandlers = {};

/** Registers the app-level callbacks; returns a function that removes them. */
export function setNavigationHandlers(handlers: NavigationHandlers): () => void {
  appHandlers = handlers;
  return () => {
    if (appHandlers === handlers) appHandlers = {};
  };
}

let appClient: Client<paths> | undefined;

/** The shared client. fetch is looked up per request, so a replaced global works. */
export function getAppClient(): Client<paths> {
  appClient ??= createApiClient({
    // Request needs an absolute URL outside a browser page (jsdom, Node).
    baseUrl: globalThis.location.origin,
    fetch: (input, init) => globalThis.fetch(input, init),
    onUnauthenticated: () => appHandlers.onUnauthenticated?.(),
    onPasswordChangeRequired: () => appHandlers.onPasswordChangeRequired?.(),
    onNoRole: () => appHandlers.onNoRole?.(),
  });
  return appClient;
}
