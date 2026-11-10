// 019/R8-T17: confirmation screen /register/confirm (RG-15, FR-8). The token is read once from the
// `#token=` fragment, the fragment is removed from the address bar, and the request is sent by the button only.
// v0.5 (2026-11-09): the success state shows the login the server created (mockup register-confirm-success).
import { GTrackLogo } from "../../shared/ui/GTrackLogo";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { confirmRegistration } from "./api";
import "./auth-screens.css";

/** The one-time token from the address fragment (`#token=...`); null if absent or empty. */
function readToken(): string | null {
  const value = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
  return value === null || value === "" ? null : value;
}

// feature_disabled has its own wording on this screen; every other code uses the common error dictionary.
// v0.5: there is no "login taken" state here, the server picks the next free login itself.
function messageFor(code: string): string {
  if (code === "feature_disabled") return t("auth.register_disabled");
  return errorMessage(code);
}

export function RegisterConfirmPage() {
  const alert = useAlertState();
  const busy = useRef(false);
  const [token] = useState(readToken);
  const [pending, setPending] = useState(false);
  // The login of the created account; null until the confirmation succeeds.
  const [login, setLogin] = useState<string | null>(null);
  const [restart, setRestart] = useState(false);

  // RG-15: the token must not stay in the address bar or in the history entry.
  useEffect(() => {
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current || token === null) return;
    busy.current = true;
    setPending(true);
    setRestart(false);
    alert.clear();
    try {
      setLogin(await confirmRegistration(token));
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "unknown";
      // A spent or expired link needs a new request from the start.
      setRestart(code === "registration_token_invalid");
      alert.show(messageFor(code));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  async function copyLogin(value: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Clipboard API is unavailable or refused: the login stays selectable on screen.
      alert.show(t("auth.register_copy_failed"));
    }
  }

  const registerAgain = (
    <div className="login-links">
      <Link to="/register">{t("auth.register_again")}</Link>
    </div>
  );

  if (token === null) {
    return (
      <section className="ui-form login-card">
        <div className="ui-brand">
          <GTrackLogo />
          <h1>{t("auth.register_confirm_title")}</h1>
        </div>
        <p>{t("auth.register_link_invalid")}</p>
        {registerAgain}
      </section>
    );
  }

  // AC-16: no session is created here, so the success state only shows the login and points to /login.
  if (login !== null) {
    return (
      <section className="ui-form login-card">
        <div className="ui-brand">
          <GTrackLogo />
          <h1>{t("auth.register_confirm_title")}</h1>
        </div>
        <p role="status" className="reg-status">
          {t("auth.register_confirmed")}
        </p>
        <div className="login-id">
          <span className="login-id-label">{t("auth.register_your_login")}</span>
          <div className="login-id-row">
            <code className="login-id-value">{login}</code>
            <button type="button" className="ui-btn-secondary" onClick={() => void copyLogin(login)}>
              {t("auth.register_copy")}
            </button>
          </div>
          <p className="reg-hint">{t("auth.register_login_hint")}</p>
        </div>
        <ErrorAlert message={alert.message} seq={alert.seq} />
        <Link to="/login" className="login-submit">
          {t("auth.register_login_link")}
        </Link>
      </section>
    );
  }

  return (
    <section className="ui-form login-card">
      <div className="ui-brand">
        <GTrackLogo />
        <h1>{t("auth.register_confirm_title")}</h1>
      </div>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <ErrorAlert message={alert.message} seq={alert.seq} />
        <button type="submit" className="login-submit" disabled={pending}>
          {t("auth.register_confirm_submit")}
        </button>
      </form>
      {restart && registerAgain}
    </section>
  );
}
