// Session profile request (T103): used by the router guards, kept apart from the auth form calls.
import { useEffect, type RefObject } from "react";
import { useLocation } from "react-router-dom";

import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type MeResponse = components["schemas"]["MeResponse"];

/** Current user profile; a flat MeResponse. Rejects with 401/403 when there is no usable session. */
export async function me(): Promise<MeResponse> {
  const { data } = await getAppClient().GET("/api/v1/me");
  if (data === undefined) throw new ApiError(200, INVALID_RESPONSE, "invalid response body");
  return data;
}

/** Navigation state: the target screen puts the focus on its h1 (003/FR-15, FR-16). */
export const FOCUS_HEADING_STATE: { readonly focusHeading: true } = { focusHeading: true };

/** Returns FOCUS_HEADING_STATE when the state has focusHeading === true, otherwise undefined. */
export function focusHeadingState(state: unknown): typeof FOCUS_HEADING_STATE | undefined {
  if (typeof state === "object" && state !== null && (state as { focusHeading?: unknown }).focusHeading === true) {
    return FOCUS_HEADING_STATE;
  }
  return undefined;
}

/** Once after mount: if location.state has focusHeading, focuses ref.current. */
export function useFocusHeadingOnArrival(ref: RefObject<HTMLElement | null>): void {
  const wanted = focusHeadingState(useLocation().state) !== undefined;
  useEffect(() => {
    if (wanted) ref.current?.focus();
    // Once after mount: later changes of the state must not move the focus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
