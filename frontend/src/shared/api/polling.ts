// Background polling on top of TanStack Query (plan §4.14, D-14, FR-29, FR-59).
//
// Every request that is not a user action carries X-GT-Background: timer ticks,
// their retries and the return of a hidden tab. Only the first load (with its
// own retries), refetch() and invalidateQueries() are plain requests that
// extend the session.
import {
  hashKey,
  onlineManager,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { ApiError } from "./client";

export const POLL_INTERVAL_MS = 15_000;
export const BACKGROUND_HEADER = "X-GT-Background";

// The session state changed: polling and retries stop until a user action succeeds.
const STOP_CODES: ReadonlySet<string> = new Set([
  "not_authenticated",
  "password_change_required",
  "no_role",
]);

// TanStack Query's own default when the QueryClient does not configure `retry`.
const DEFAULT_RETRIES = 3;

function isStopError(error: unknown): boolean {
  return error instanceof ApiError && STOP_CODES.has(error.code);
}

// Query hashes whose fetch is being started by the polling timer right now. The
// query function runs synchronously inside refetchQueries() and moves the mark
// to the fetch's own AbortSignal: all retries of that fetch share the signal,
// while a user action starts a fetch with a new signal and stays unmarked.
// Keyed by query hash, so parallel queries do not affect each other.
const startingBackground = new Set<string>();
const backgroundFetches = new WeakSet<AbortSignal>();

interface Poller {
  key: QueryKey;
  subscribers: number;
  stop: () => void;
}

// One timer per (QueryClient, query key) however many components use the key.
const pollers = new WeakMap<QueryClient, Map<string, Poller>>();

// The timer is a setTimeout chain anchored to the last data/error update, not to
// the mount: FR-29 allows at most POLL_INTERVAL_MS (+ response time) between
// updates, whatever moved the data last (first load, refetch(), a previous tick).
function startPoller(queryClient: QueryClient, key: QueryKey, hash: string): Poller {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  const arm = (delay: number) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = stopped ? undefined : setTimeout(tick, delay);
  };

  function tick() {
    timer = undefined;
    // Hidden tab: no timer at all; visibilitychange resumes polling.
    if (document.hidden) return;
    const state = queryClient.getQueryState(key);
    // Offline: the fetch would be paused and start later, outside the marked window.
    // In flight: its completion moves the anchor. Stop errors: wait for a user action.
    if (
      state === undefined ||
      !onlineManager.isOnline() ||
      state.fetchStatus !== "idle" ||
      isStopError(state.error)
    ) {
      arm(POLL_INTERVAL_MS);
      return;
    }
    const age = Date.now() - Math.max(state.dataUpdatedAt, state.errorUpdatedAt);
    if (age < POLL_INTERVAL_MS) {
      // Updated recently (refetch(), a tab return, a slow response): catch up later.
      arm(POLL_INTERVAL_MS - age);
      return;
    }
    startingBackground.add(hash);
    try {
      // cancelRefetch: false keeps a request that is already in flight.
      void queryClient.refetchQueries({ queryKey: key, exact: true }, { cancelRefetch: false });
    } finally {
      startingBackground.delete(hash);
    }
    arm(POLL_INTERVAL_MS);
  }

  const onVisibility = () => {
    if (document.hidden) {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    } else {
      tick();
    }
  };

  // Cached data from an earlier mount keeps its own anchor.
  const initial = queryClient.getQueryState(key);
  const anchor = initial ? Math.max(initial.dataUpdatedAt, initial.errorUpdatedAt) : 0;
  arm(anchor > 0 ? Math.max(0, anchor + POLL_INTERVAL_MS - Date.now()) : POLL_INTERVAL_MS);
  document.addEventListener("visibilitychange", onVisibility);
  return {
    key,
    subscribers: 0,
    stop: () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      document.removeEventListener("visibilitychange", onVisibility);
    },
  };
}

function subscribePoller(queryClient: QueryClient, key: QueryKey, hash: string): () => void {
  let byKey = pollers.get(queryClient);
  if (byKey === undefined) {
    byKey = new Map();
    pollers.set(queryClient, byKey);
  }
  let poller = byKey.get(hash);
  if (poller === undefined) {
    poller = startPoller(queryClient, key, hash);
    byKey.set(hash, poller);
  }
  poller.subscribers += 1;
  const registry = byKey;
  const active = poller;
  return () => {
    active.subscribers -= 1;
    if (active.subscribers === 0) {
      active.stop();
      if (registry.get(hash) === active) registry.delete(hash);
    }
  };
}

export interface PolledQueryOptions<T> {
  queryKey: readonly unknown[];
  queryFn: (ctx: { headers: Record<string, string>; signal: AbortSignal }) => Promise<T>;
  enabled?: boolean;
}

export function usePolledQuery<T>(options: PolledQueryOptions<T>): UseQueryResult<T, ApiError> {
  const { queryKey, queryFn, enabled = true } = options;
  const queryClient = useQueryClient();
  const keyHash = hashKey(queryKey);

  const result = useQuery<T, ApiError>({
    queryKey,
    enabled,
    queryFn: ({ signal }) => {
      if (startingBackground.delete(keyHash)) {
        backgroundFetches.add(signal);
      }
      const headers: Record<string, string> = backgroundFetches.has(signal)
        ? { [BACKGROUND_HEADER]: "1" }
        : {};
      return queryFn({ headers, signal });
    },
    // Window focus and reconnect would send non-background requests nobody asked for.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    // Session-state errors are never retried; everything else follows the
    // QueryClient's configured `retry` (a query-level option would override it).
    retry: (failureCount, error) => {
      if (isStopError(error)) return false;
      const configured = queryClient.getDefaultOptions().queries?.retry ?? DEFAULT_RETRIES;
      if (typeof configured === "function") return configured(failureCount, error);
      if (typeof configured === "number") return failureCount < configured;
      return configured;
    },
  });

  const keyRef = useRef(queryKey);
  useEffect(() => {
    keyRef.current = queryKey;
  });

  useEffect(() => {
    if (!enabled) return undefined;
    return subscribePoller(queryClient, keyRef.current, keyHash);
  }, [queryClient, enabled, keyHash]);

  return result;
}
