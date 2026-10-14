// T22: фоновый опрос (plan §4.14, D-14, FR-29, FR-59, AC-79).
//
// Контракт для исполнителя (frontend/src/shared/api/polling.ts):
//   export const POLL_INTERVAL_MS = 15_000;
//   export const BACKGROUND_HEADER = "X-GT-Background";
//   export function usePolledQuery<T>(options: {
//       queryKey: readonly unknown[];
//       queryFn: (ctx: { headers: Record<string, string>; signal: AbortSignal }) => Promise<T>;
//       enabled?: boolean;
//   }): UseQueryResult<T, ApiError>
// ctx.headers == {} для первой загрузки и любого действия пользователя (refetch(),
// invalidateQueries после мутации) и == { "X-GT-Background": "1" } только для запроса,
// инициированного таймером опроса, когда у запроса уже есть данные. queryFn передаёт
// headers в client.GET(...). Опрос идёт только пока вкладка видима; 401 останавливает
// опрос (без повторов).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient } from "../../src/shared/api/client";
import {
  BACKGROUND_HEADER,
  POLL_INTERVAL_MS,
  usePolledQuery,
} from "../../src/shared/api/polling";

const ORIGIN = window.location.origin;
const KEY = ["polled", "me"] as const;

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => (hidden ? "hidden" : "visible"),
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  Reflect.deleteProperty(document, "hidden");
  Reflect.deleteProperty(document, "visibilityState");
});

function setup(
  responder: (n: number) => Response = () =>
    new Response(JSON.stringify({ n: 1 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  handlers: { onUnauthenticated?: () => void } = {},
  retry?: false,
) {
  const calls: Request[] = [];
  const fetchImpl = vi.fn(async (input: Request) => {
    calls.push(input);
    return responder(calls.length);
  });
  const api = createApiClient({
    baseUrl: ORIGIN,
    fetch: fetchImpl as unknown as typeof fetch,
    ...handlers,
  });
  const queryFn = vi.fn(async ({ headers }: { headers: Record<string, string> }) => {
    const res = await api.GET("/api/v1/me", { headers });
    return res.data;
  });
  // Настройки QueryClient — по умолчанию: повторы при ошибках включены.
  const queryClient = new QueryClient(
    retry === false ? { defaultOptions: { queries: { retry: false } } } : undefined,
  );
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  const hook = renderHook(
    () => usePolledQuery({ queryKey: KEY, queryFn: (ctx) => queryFn(ctx) }),
    { wrapper },
  );
  const bg = () => calls.map((c) => c.headers.get(BACKGROUND_HEADER));
  return { calls, fetchImpl, queryFn, queryClient, hook, bg };
}

describe("usePolledQuery", () => {
  it("exports the interval and the header name from plan §4.14", () => {
    expect(POLL_INTERVAL_MS).toBe(15_000);
    expect(BACKGROUND_HEADER).toBe("X-GT-Background");
  });

  it("first load is a user action: no X-GT-Background", async () => {
    const { hook, bg, queryFn } = setup();
    await vi.advanceTimersByTimeAsync(0);
    expect(hook.result.current.data).toEqual({ n: 1 });
    expect(bg()).toEqual([null]);
    expect(queryFn.mock.calls[0]![0].headers).toEqual({});
  });

  it("poll ticks (data already present) carry X-GT-Background: 1", async () => {
    const { bg, queryFn } = setup();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    expect(bg()).toEqual([null, "1"]);
    expect(queryFn.mock.calls[1]![0].headers).toEqual({ "X-GT-Background": "1" });
  });

  it("makes 4 background requests per 60 s after the first load (FR-29: not less than every 15 s)", async () => {
    const { bg, calls } = setup();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(calls).toHaveLength(4);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(5);
    expect(bg()).toEqual([null, "1", "1", "1", "1"]);
  });

  it("manual refetch() is a user action: no header; the next tick is background again", async () => {
    const { hook, bg } = setup();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    expect(bg()).toEqual([null, "1"]);
    await act(async () => {
      await hook.result.current.refetch();
    });
    expect(bg()).toEqual([null, "1", null]);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    expect(bg().at(-1)).toBe("1");
  });

  it("invalidateQueries after a mutation is a user action: no header", async () => {
    const { queryClient, bg } = setup();
    await vi.advanceTimersByTimeAsync(0);
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: KEY });
    });
    expect(bg()).toEqual([null, null]);
  });

  it("pauses while the tab is hidden and resumes when it becomes visible", async () => {
    const { calls } = setup();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);
    await act(async () => {
      setHidden(true);
    });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls).toHaveLength(1);
    await act(async () => {
      setHidden(false);
    });
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    expect(calls.length).toBeGreaterThan(1);
  });

  it("401 stops polling (no retries, no timer ticks) and fires the callback once", async () => {
    const onUnauthenticated = vi.fn();
    const { hook, calls } = setup(
      () =>
        new Response(JSON.stringify({ detail: "x", code: "not_authenticated" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      { onUnauthenticated },
    );
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls).toHaveLength(1);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
    expect(hook.result.current.isError).toBe(true);
    expect(hook.result.current.error).toBeInstanceOf(ApiError);
    expect(hook.result.current.error).toMatchObject({ status: 401, code: "not_authenticated" });
  });

  it("unmount clears the timers: no requests afterwards", async () => {
    const { hook, calls } = setup();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    const before = calls.length;
    hook.unmount();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls).toHaveLength(before);
  });

  it("enabled: false does not request and does not poll", async () => {
    const calls: number[] = [];
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    renderHook(
      () =>
        usePolledQuery({
          queryKey: ["off"],
          enabled: false,
          queryFn: async () => {
            calls.push(1);
            return 1;
          },
        }),
      { wrapper },
    );
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls).toHaveLength(0);
  });

  // FR-59: каждый запрос от таймера — фоновый, независимо от наличия данных.
  describe("timer ticks are always background (FR-59)", () => {
    const ok = () =>
      new Response(JSON.stringify({ n: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    const fail500 = () =>
      new Response(JSON.stringify({ detail: "x", code: "internal_error" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });

    // Реализация вправе повторять неудачную загрузку (retry с нарастающей паузой, до ~7 с);
    // повторы первой загрузки в тестах пережидаются отдельно от тиков таймера.
    const SETTLE_MS = 10_000;

    it("first load 500 (no data): later ticks carry X-GT-Background and polling continues", async () => {
      const { bg, calls } = setup(fail500, {}, false);
      await vi.advanceTimersByTimeAsync(0);
      expect(bg()[0]).toBeNull();
      await vi.advanceTimersByTimeAsync(SETTLE_MS);
      const settled = calls.length;
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
      const ticks = bg().slice(settled);
      expect(ticks.length).toBeGreaterThanOrEqual(3);
      expect(ticks.every((h) => h === "1")).toBe(true);
    });

    it("first load network error: later ticks carry X-GT-Background", async () => {
      const { bg, calls } = setup(
        () => {
          throw new TypeError("Failed to fetch");
        },
        {},
        false,
      );
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(SETTLE_MS);
      const settled = calls.length;
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
      const ticks = bg().slice(settled);
      expect(ticks.length).toBeGreaterThanOrEqual(2);
      expect(ticks.every((h) => h === "1")).toBe(true);
    });

    it("200, then 500, then 200: every tick is background", async () => {
      const { bg, hook } = setup((n) => (n === 2 ? fail500() : ok()), {}, false);
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
      expect(bg()).toEqual([null, "1", "1"]);
      expect(hook.result.current.data).toEqual({ n: 1 });
    });

    it("manual refetch() after a failed first load is a user action: no header", async () => {
      const { hook, bg, calls } = setup(fail500, {}, false);
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(SETTLE_MS);
      const settled = calls.length;
      await act(async () => {
        void hook.result.current.refetch();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(calls.length).toBeGreaterThan(settled);
      expect(bg()[settled]).toBeNull();
      await vi.advanceTimersByTimeAsync(SETTLE_MS + POLL_INTERVAL_MS * 2);
      expect(bg().slice(settled + 1)).toContain("1");
    });

    it("returning to a visible tab: the next poll request is background", async () => {
      const { bg, calls } = setup(ok, {}, false);
      await vi.advanceTimersByTimeAsync(0);
      await act(async () => {
        setHidden(true);
      });
      await vi.advanceTimersByTimeAsync(60_000);
      const before = calls.length;
      await act(async () => {
        setHidden(false);
      });
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
      expect(calls.length).toBeGreaterThan(before);
      // Все запросы после первой загрузки — без действия пользователя.
      expect(bg().slice(1).every((h) => h === "1")).toBe(true);
    });
  });
});

describe("polling load control (review T22)", () => {
  const okJson = () =>
    new Response(JSON.stringify({ n: 1 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  function mount() {
    const calls: Request[] = [];
    const api = createApiClient({
      baseUrl: ORIGIN,
      fetch: (async (input: Request) => {
        calls.push(input);
        return okJson();
      }) as unknown as typeof fetch,
    });
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    function usePoll(key: readonly unknown[], path: "/api/v1/me" | "/api/v1/health") {
      return usePolledQuery({
        queryKey: key,
        queryFn: async ({ headers }) => (await api.GET(path, { headers })).data,
      });
    }
    function mountPolled(key: readonly unknown[], path: "/api/v1/me" | "/api/v1/health") {
      return renderHook(() => usePoll(key, path), { wrapper });
    }
    const use = mountPolled;
    const count = (path: string) => calls.filter((c) => new URL(c.url).pathname === path).length;
    return { calls, use, count };
  }

  it("10 returns to a visible tab within 4 s cause at most one extra request", async () => {
    const { calls, use } = mount();
    use(["a"], "/api/v1/me");
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);
    for (let i = 0; i < 10; i += 1) {
      await act(async () => {
        setHidden(true);
      });
      await vi.advanceTimersByTimeAsync(200);
      await act(async () => {
        setHidden(false);
      });
      await vi.advanceTimersByTimeAsync(200);
    }
    expect(calls.length).toBeLessThanOrEqual(2);
  });

  it("two hooks with the same key share one timer: at most 5 requests in 65 s", async () => {
    const { calls, use } = mount();
    use(["same"], "/api/v1/me");
    use(["same"], "/api/v1/me");
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(65_000);
    expect(calls.length).toBeLessThanOrEqual(5);
    expect(calls.length).toBeGreaterThanOrEqual(4);
  });

  it("two different keys are polled independently: 5 requests each in 60 s", async () => {
    const { use, count } = mount();
    use(["k1"], "/api/v1/me");
    use(["k2"], "/api/v1/health");
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(count("/api/v1/me")).toBe(5);
    expect(count("/api/v1/health")).toBe(5);
  });

  it("returning after a long idle triggers one request, not a burst", async () => {
    const { calls, use } = mount();
    use(["idle"], "/api/v1/me");
    await vi.advanceTimersByTimeAsync(0);
    await act(async () => {
      setHidden(true);
    });
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    const before = calls.length;
    await act(async () => {
      setHidden(false);
    });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(calls.length - before).toBe(1);
  });
});


// FR-29 / AC-107: между обновлениями данных не больше POLL_INTERVAL_MS плюс время ответа.
describe("polling cadence is not phase-locked to mount (review T22 attempt 3)", () => {
  const TOL = 1;

  function mountTimed(delayFirstMs = 0) {
    const starts: number[] = [];
    const ends: number[] = [];
    const headers: (string | null)[] = [];
    const t0 = Date.now();
    const api = createApiClient({
      baseUrl: ORIGIN,
      fetch: (async (input: Request) => {
        starts.push(Date.now() - t0);
        headers.push(input.headers.get(BACKGROUND_HEADER));
        if (starts.length === 1 && delayFirstMs > 0) {
          await new Promise((r) => setTimeout(r, delayFirstMs));
        }
        ends.push(Date.now() - t0);
        return new Response(JSON.stringify({ n: 1 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }) as unknown as typeof fetch,
    });
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const hook = renderHook(
      () =>
        usePolledQuery({
          queryKey: ["cadence"],
          queryFn: async ({ headers: h }) => (await api.GET("/api/v1/me", { headers: h })).data,
        }),
      { wrapper },
    );
    return { starts, ends, headers, hook, t0 };
  }

  // Следующий запрос после момента `from` должен начаться не позже from + 15 с.
  function nextStartAfter(starts: number[], from: number): number | undefined {
    return starts.find((s) => s > from);
  }

  it("refetch() at t=8 s: next background request by t=23 s", async () => {
    const { starts, headers, hook } = mountTimed();
    await vi.advanceTimersByTimeAsync(8_000);
    await act(async () => {
      await hook.result.current.refetch();
    });
    const refetchAt = starts.at(-1)!;
    expect(refetchAt).toBeGreaterThanOrEqual(8_000);
    await vi.advanceTimersByTimeAsync(50_000);
    const next = nextStartAfter(starts, refetchAt);
    expect(next).toBeDefined();
    expect(next!).toBeLessThanOrEqual(refetchAt + POLL_INTERVAL_MS + TOL);
    expect(headers[starts.indexOf(next!)]).toBe("1");
  });

  it("return to the tab at t=8 s: next background request by t=23 s", async () => {
    const { starts, headers } = mountTimed();
    await vi.advanceTimersByTimeAsync(7_000);
    await act(async () => {
      setHidden(true);
    });
    await vi.advanceTimersByTimeAsync(1_000);
    await act(async () => {
      setHidden(false);
    });
    await vi.advanceTimersByTimeAsync(0);
    // Данные не старше 15 с обновлены не позже момента возврата.
    const lastUpdate = starts.at(-1)!;
    await vi.advanceTimersByTimeAsync(50_000);
    // Максимальный промежуток между запросами после возврата не больше интервала.
    const after = starts.filter((s) => s >= lastUpdate);
    for (let i = 1; i < after.length; i += 1) {
      expect(after[i]! - after[i - 1]!).toBeLessThanOrEqual(POLL_INTERVAL_MS + TOL);
    }
    const next = nextStartAfter(starts, 8_000);
    expect(next).toBeDefined();
    expect(next!).toBeLessThanOrEqual(8_000 + POLL_INTERVAL_MS + TOL);
    expect(headers.slice(1).every((h) => h === "1")).toBe(true);
  });

  it("first load finishing at t=8 s: next request by t=23 s", async () => {
    const { starts, ends } = mountTimed(8_000);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(ends[0]).toBeGreaterThanOrEqual(8_000);
    const next = nextStartAfter(starts, 0);
    expect(next).toBeDefined();
    expect(next!).toBeLessThanOrEqual(ends[0]! + POLL_INTERVAL_MS + TOL);
  });

  it("no gap longer than the interval over 65 s of steady polling", async () => {
    const { starts } = mountTimed();
    await vi.advanceTimersByTimeAsync(65_000);
    for (let i = 1; i < starts.length; i += 1) {
      expect(starts[i]! - starts[i - 1]!).toBeLessThanOrEqual(POLL_INTERVAL_MS + TOL);
    }
    expect(starts.length).toBeLessThanOrEqual(6);
  });
});
