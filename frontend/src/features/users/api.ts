// Users directory (T35): active users with a business role, for recipient pickers.
// Goes through the shared application client; rejects with ApiError, never sends
// the background header (FR-59).
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { Page } from "../admin/api";

export type DirectoryUser = components["schemas"]["DirectoryUser"];

export interface DirectoryParams {
  q?: string;
  page?: number;
  pageSize?: number;
}

/** `GET /api/v1/users`; a parameter is sent only if it is set (empty `q` is not). */
export async function listDirectory(p: DirectoryParams): Promise<Page<DirectoryUser>> {
  const query: { q?: string; page?: number; page_size?: number } = {};
  if (p.q !== undefined && p.q !== "") query.q = p.q;
  if (p.page !== undefined) query.page = p.page;
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  const { data } = await getAppClient().GET("/api/v1/users", { params: { query } });
  if (data === undefined) throw new ApiError(200, INVALID_RESPONSE, "invalid response body");
  return data;
}
