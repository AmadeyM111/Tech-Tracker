// Notification endpoints (012/FR-5). Polled reads carry the background header via `headers`.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { ReadOptions } from "../tasks/api";

export type Notification = components["schemas"]["NotificationOut"];
export type NotificationPage = components["schemas"]["NotificationPage"];

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function getUnread(options: ReadOptions = {}): Promise<number> {
  const { data } = await getAppClient().GET("/api/v1/me/notifications/unread", {
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data.unread;
}

export async function listNotifications(page: number, options: ReadOptions = {}): Promise<NotificationPage> {
  const { data } = await getAppClient().GET("/api/v1/me/notifications", {
    params: { query: { page } },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

/** Selected ids, or all when `ids` is null. */
export async function markRead(ids: string[] | null): Promise<void> {
  await getAppClient().POST("/api/v1/me/notifications/read", {
    body: ids === null ? { all: true } : { ids, all: false },
  });
}
