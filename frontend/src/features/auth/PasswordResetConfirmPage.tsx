import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { PASSWORD_MIN_LENGTH, errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { confirmPasswordReset } from "./api";

/** The one-time token from the address fragment (`#token=...`); null if absent or empty. */
function readToken(): string | null {
  const value = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
  return value === null || value === "" ? null : value;
}

export function PasswordResetConfirmPage() {
  const alert = useAlertState();
  const busy = useRef(false);
  const [token] = useState(readToken);
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [showNext, setShowNext] = useState(false);
  const [showRepeat, setShowRepeat] = useState(false);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const [tokenInvalid, setTokenInvalid] = useState(false);

  // PR-18: the token must not stay in the address bar or the history entry.
  useEffect(() => {
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setShowNext(false);
    setShowRepeat(false);
    if (busy.current || token === null) return;
    if (next !== repeat) {
      alert.show(t("auth.password_mismatch"));
      return;
    }
    busy.current = true;
    setPending(true);
    setTokenInvalid(false);
    alert.clear();
    try {
      await confirmPasswordReset({ token, new_password: next });
      setDone(true);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "unknown";
      if (code === "reset_token_invalid") setTokenInvalid(true);
      alert.show(errorMessage(code));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  const requestAgain = <Link to="/password-reset">{t("auth.reset_request_again")}</Link>;

  if (token === null) {
    return (
      <section className="ui-form">
        <h1>{t("auth.reset_confirm_title")}</h1>
        <p>{t("auth.reset_link_invalid")}</p>
        {requestAgain}
      </section>
    );
  }

  if (done) {
    return (
      <section className="ui-form">
        <h1>{t("auth.reset_confirm_title")}</h1>
        <p role="status">{t("auth.reset_done")}</p>
        <Link to="/login">{t("auth.reset_login_link")}</Link>
      </section>
    );
  }

  return (
    <section className="ui-form">
      <h1>{t("auth.reset_confirm_title")}</h1>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <ErrorAlert message={alert.message} seq={alert.seq} />
        <TextField
          label={t("auth.reset_new_password_label")}
          type="password"
          value={next}
          onChange={setNext}
          autoComplete="new-password"
          hint={t("auth.password_min_length_hint", { min: PASSWORD_MIN_LENGTH })}
          disabled={pending}
          reveal={{ label: t("auth.show_new_password"), shown: showNext, onToggle: () => setShowNext((v) => !v) }}
        />
        <TextField
          label={t("auth.reset_repeat_password_label")}
          type="password"
          value={repeat}
          onChange={setRepeat}
          autoComplete="new-password"
          disabled={pending}
          reveal={{ label: t("auth.show_confirm_password"), shown: showRepeat, onToggle: () => setShowRepeat((v) => !v) }}
        />
        <button type="submit" disabled={pending}>
          {t("auth.reset_confirm_submit")}
        </button>
      </form>
      {tokenInvalid && requestAgain}
    </section>
  );
}
