// Session profile request (T103): used by the router guards, kept apart from the auth form calls.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type MeResponse = components["schemas"]["MeResponse"];

/** Current user profile; a flat MeResponse. Rejects with 401/403 when there is no usable session. */
export async function me(): Promise<MeResponse> {
  const { data } = await getAppClient().GET("/api/v1/me");
  if (data === undefined) throw new ApiError(200, INVALID_RESPONSE, "invalid response body");
  return data;
}
