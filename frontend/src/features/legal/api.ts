// Spec 021: public legal texts and the PDn consent calls. Every call goes through the shared client.
import { useQuery } from "@tanstack/react-query";

import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type LegalStatus = components["schemas"]["LegalStatus"];
export type LegalDocument = components["schemas"]["LegalDocument"];
export type LegalKind = "privacy" | "consent";

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function legalStatus(): Promise<LegalStatus> {
  const { data } = await getAppClient().GET("/api/v1/legal");
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function legalDocument(kind: LegalKind): Promise<LegalDocument> {
  const { data } = await getAppClient().GET("/api/v1/legal/{kind}", { params: { path: { kind } } });
  if (data === undefined) throw invalidBody(200);
  return data;
}

// The same key everywhere: the register page, the login page and the confirm screen share one request.
export const LEGAL_STATUS_KEY = ["legal", "status"] as const;

// `enabled: false` keeps a screen that has nothing to ask (no provider buttons) from calling the API.
export function useLegalStatus(enabled = true) {
  return useQuery({
    queryKey: LEGAL_STATUS_KEY,
    enabled,
    queryFn: () => legalStatus(),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export async function acceptPdnConsent(version: string): Promise<void> {
  await getAppClient().POST("/api/v1/me/pdn-consent", {
    body: { pdn_consent: true, pdn_consent_version: version },
  });
}
