import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { requestPasswordReset } from "./api";

export function PasswordResetRequestPage() {
  const alert = useAlertState();
  const emailRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setSent(false);
    alert.clear();
    try {
      await requestPasswordReset({ email: email.trim() });
      setSent(true);
    } catch (e) {
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return (
    <section className="ui-form">
      <h1>{t("auth.reset_request_title")}</h1>
      {!sent && (
        <form onSubmit={(e) => void onSubmit(e)} noValidate>
          <ErrorAlert message={alert.message} seq={alert.seq} />
          <TextField
            label={t("auth.reset_email_label")}
            value={email}
            onChange={setEmail}
            autoComplete="email"
            inputRef={emailRef}
            disabled={pending}
          />
          <button type="submit" disabled={pending}>
            {t("auth.reset_request_submit")}
          </button>
        </form>
      )}
      {sent && <p role="status">{t("auth.reset_request_sent")}</p>}
      <Link to="/login">{t("auth.reset_back_to_login")}</Link>
    </section>
  );
}
