// 019/R8-T16: self-registration request screen /register (FR-2, FR-3, FR-4, AC-1, AC-2).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { PASSWORD_MIN_LENGTH, errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { passwordResetStatus, requestRegistration, type RegistrationRequest } from "./api";

// feature_disabled means the registration is off (FR-1): the screen says so instead of the generic text.
function messageFor(code: string): string {
  return code === "feature_disabled" ? t("auth.register_disabled") : errorMessage(code);
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

  // The same query and key as on /login (RG-13): the status is shared, no extra request is made.
  const status = useQuery({
    queryKey: ["auth", "password-reset-status"],
    queryFn: () => passwordResetStatus(),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const registrationOff = status.data?.enabled === false;

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
    try {
      await requestRegistration(body);
      setSent(true);
    } catch (e) {
      alert.show(messageFor(e instanceof ApiError ? e.code : "unknown"));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return (
    <section className="ui-form">
      <h1>{t("auth.register_title")}</h1>
      {registrationOff ? (
        <p>{t("auth.register_disabled")}</p>
      ) : sent ? (
        <p role="status">{t("auth.register_sent")}</p>
      ) : (
        <form onSubmit={(e) => void onSubmit(e)} noValidate>
          <ErrorAlert message={alert.message} seq={alert.seq} />
          <TextField
            label={t("auth.register_email_label")}
            value={email}
            onChange={setEmail}
            autoComplete="email"
            inputRef={emailRef}
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
            reveal={{ label: t("auth.show_password"), shown, onToggle: () => setShown((v) => !v) }}
          />
          <button type="submit" disabled={pending}>
            {t("auth.register_submit")}
          </button>
        </form>
      )}
      <Link to="/login">{t("auth.register_back_to_login")}</Link>
    </section>
  );
}
