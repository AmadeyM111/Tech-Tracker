// 019/R8-T17: confirmation screen /register/confirm (RG-15, FR-8). The token is read once from the
// `#token=` fragment, the fragment is removed from the address bar, and the request is sent by the button only.
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

// Codes with their own wording on this screen; every other code uses the common error dictionary.
function messageFor(code: string): string {
  if (code === "login_taken") return t("auth.register_login_taken");
  if (code === "feature_disabled") return t("auth.register_disabled");
  return errorMessage(code);
}

export function RegisterConfirmPage() {
  const alert = useAlertState();
  const busy = useRef(false);
  const [token] = useState(readToken);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
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
      await confirmRegistration(token);
      setDone(true);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "unknown";
      // A spent or expired link and a taken login both need a new request from the start.
      setRestart(code === "registration_token_invalid" || code === "login_taken");
      alert.show(messageFor(code));
    } finally {
      busy.current = false;
      setPending(false);
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

  // AC-16: no session is created here, so the success state only points to the login screen.
  if (done) {
    return (
      <section className="ui-form login-card">
        <div className="ui-brand">
          <GTrackLogo />
          <h1>{t("auth.register_confirm_title")}</h1>
        </div>
        <p role="status" className="reg-status">
          {t("auth.register_confirmed")}
        </p>
        <div className="login-links">
          <Link to="/login" className="login-submit">
            {t("auth.register_login_link")}
          </Link>
        </div>
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
