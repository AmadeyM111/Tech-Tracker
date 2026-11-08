// 019/R8-T16: self-registration request screen /register (FR-2, FR-3, FR-4, AC-1, AC-2).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { PASSWORD_MIN_LENGTH, errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { passwordResetStatus, requestRegistration, type RegistrationRequest } from "./api";
import "./auth-screens.css";

// The field the error refers to; it is marked invalid, the text stays above the submit button (design 2026-11-08).
function badFieldFor(code: string): "email" | "username" | null {
  if (code === "login_taken") return "username";
  if (code === "email_invalid") return "email";
  return null;
}

export function RegisterPage() {
  const alert = useAlertState();
  const emailRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  // feature_disabled on submit (FR-1): the form is hidden as if registration were off (plan §10, p. 2).
  const [off, setOff] = useState(false);
  const [badField, setBadField] = useState<"email" | "username" | null>(null);

  // The same query and key as on /login (RG-13): the status is shared, no extra request is made.
  const status = useQuery({
    queryKey: ["auth", "password-reset-status"],
    queryFn: () => passwordResetStatus(),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const registrationOff = off || status.data?.enabled === false;

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    const body: RegistrationRequest = {
      email: email.trim(),
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      login: login.trim(),
      password,
    };
    if (body.email === "" || body.first_name === "" || body.last_name === "" || body.login === "" || body.password === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    busy.current = true;
    setPending(true);
    alert.clear();
    setBadField(null);
    try {
      await requestRegistration(body);
      setSent(true);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "unknown";
      if (code === "feature_disabled") {
        setOff(true);
      } else {
        setBadField(badFieldFor(code));
        alert.show(errorMessage(code));
      }
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return (
    <section className="ui-form login-card">
      <h1>{t("auth.register_title")}</h1>
      {registrationOff ? (
        <p>{t("auth.register_disabled")}</p>
      ) : sent ? (
        <p role="status" className="reg-status">
          {t("auth.register_sent")}
        </p>
      ) : (
        <form className="reg-form" onSubmit={(e) => void onSubmit(e)} noValidate>
          <TextField
            label={t("auth.register_email_label")}
            value={email}
            onChange={setEmail}
            autoComplete="email"
            inputRef={emailRef}
            invalid={badField === "email"}
            disabled={pending}
          />
          <TextField
            label={t("auth.register_first_name_label")}
            value={firstName}
            onChange={setFirstName}
            autoComplete="given-name"
            disabled={pending}
          />
          <TextField
            label={t("auth.register_last_name_label")}
            value={lastName}
            onChange={setLastName}
            autoComplete="family-name"
            disabled={pending}
          />
          <TextField
            label={t("auth.register_login_label")}
            value={login}
            onChange={setLogin}
            autoComplete="username"
            invalid={badField === "username"}
            disabled={pending}
          />
          <TextField
            label={t("auth.register_password_label")}
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            hint={t("auth.password_min_length_hint", { min: PASSWORD_MIN_LENGTH })}
            disabled={pending}
            reveal={{
              label: shown ? t("auth.hide_password") : t("auth.show_password"),
              shown,
              onToggle: () => setShown((v) => !v),
            }}
          />
          <ErrorAlert message={alert.message} seq={alert.seq} />
          <button type="submit" className="login-submit" disabled={pending}>
            {t("auth.register_submit")}
          </button>
        </form>
      )}
      <div className="login-links">
        <Link to="/login">{t("auth.register_back_to_login")}</Link>
      </div>
    </section>
  );
}
