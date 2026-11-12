// "ChatGPT просит доступ к вашему GTrack": the consent screen of the OAuth flow (spec 028 FR-5, FR-6).
// Without a session the user goes to /login and comes back here (only to this path, see LoginPage).
// Mockups: Shared/Design/gtrack-oauth (consent, login-context, error-unknown).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { GTrackLogo } from "../../shared/ui/GTrackLogo";
import { decide, getConsentContext } from "./api";
import "./oauth.css";

export const CONSENT_PATH = "/oauth/authorize";

/** Navigates the browser away (to the client); a function so that tests can replace it. */
export const redirects = {
  go(url: string): void {
    window.location.assign(url);
  },
};

const PAGE_ERRORS: Record<string, "oauth.error_unknown" | "oauth.error_request"> = {
  oauth_client_unknown: "oauth.error_unknown",
  oauth_request_invalid: "oauth.error_request",
};

export function ConsentPage() {
  const { search } = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(search);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const context = useQuery({
    queryKey: ["oauth", "context", search],
    queryFn: () => getConsentContext(params),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
  const data = context.data;
  const failure = context.error instanceof ApiError ? context.error : null;

  // No session: log in first and come back to the same request.
  useEffect(() => {
    if (failure?.status === 401) navigate(`/login?next=${encodeURIComponent(CONSENT_PATH + search)}`, { replace: true });
  }, [failure, navigate, search]);

  // A protocol error that is answered to the client with a redirect (the user sees nothing).
  useEffect(() => {
    if (data?.status === "redirect" && data.redirect_to) redirects.go(data.redirect_to);
  }, [data]);

  useEffect(() => {
    if (data?.status === "ok" || (failure !== null && failure.status !== 401)) headingRef.current?.focus();
  }, [data, failure]);

  async function answer(allow: boolean): Promise<void> {
    if (pending || data?.request_token == null) return;
    setPending(true);
    setError(null);
    try {
      redirects.go(await decide(data.request_token, allow));
    } catch (e) {
      setError(errorMessage(e instanceof ApiError ? PAGE_ERRORS[e.code] ?? e.code : "unknown"));
      setPending(false);
    }
  }

  if (data?.status === "ok") {
    const client = data.client_name ?? "";
    return (
      <section className="ui-form login-card oauth-card" aria-labelledby="oauth-title">
        <div className="ui-brand">
          <GTrackLogo />
          <h1 id="oauth-title" ref={headingRef} tabIndex={-1}>
            {t("oauth.title", { client })}
          </h1>
        </div>
        <ErrorAlert message={error} />
        <p>{t("oauth.lead", { client })}</p>
        <ul className="oauth-list">
          <li>{t("oauth.item_read")}</li>
          <li>{t("oauth.item_write")}</li>
        </ul>
        <p className="oauth-muted">{t("oauth.signed_in_as", { login: data.login ?? "" })}</p>
        <div className="oauth-actions">
          <button type="button" data-action="allow" disabled={pending} onClick={() => void answer(true)}>
            {t("oauth.allow")}
          </button>
          <button
            type="button"
            className="ui-btn-secondary"
            data-action="deny"
            disabled={pending}
            onClick={() => void answer(false)}
          >
            {t("oauth.deny")}
          </button>
        </div>
        <p className="oauth-redirect">
          {t("oauth.return_to")}: <code>{data.redirect_uri}</code>
        </p>
      </section>
    );
  }

  if (failure !== null && failure.status !== 401) {
    const key = PAGE_ERRORS[failure.code];
    return (
      <section className="ui-form login-card oauth-card" aria-labelledby="oauth-title">
        <div className="ui-brand">
          <GTrackLogo />
          <h1 id="oauth-title" ref={headingRef} tabIndex={-1}>
            {t("oauth.error_title")}
          </h1>
        </div>
        <ErrorAlert message={key !== undefined ? t(key) : errorMessage(failure.code)} />
        <p>
          <Link className="ui-btn-secondary oauth-back" to="/">
            {t("oauth.back")}
          </Link>
        </p>
      </section>
    );
  }
  return (
    <section className="ui-form login-card oauth-card">
      <p role="status">{t("admin.loading")}</p>
    </section>
  );
}
