import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { login } from "./api";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const loginRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [loginValue, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    loginRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    if (loginValue.trim() === "" || password === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      const { user } = await login({ login: loginValue.trim(), password });
      // Nothing of the previous user may stay in the cache.
      queryClient.clear();
      if (user.must_change_password) {
        navigate("/change-password", { replace: true });
      } else if (user.role === null) {
        navigate("/no-role", { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    } catch (e) {
      busy.current = false;
      setPending(false);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
  }

  return (
    <section className="ui-form">
      <h1>{t("auth.login_title")}</h1>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <ErrorAlert message={alert.message} seq={alert.seq} />
        <TextField
          label={t("auth.login_label")}
          value={loginValue}
          onChange={setLogin}
          autoComplete="username"
          inputRef={loginRef}
          disabled={pending}
        />
        <TextField
          label={t("auth.password_label")}
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          disabled={pending}
        />
        <button type="submit" disabled={pending}>
          {t("auth.login_submit")}
        </button>
      </form>
    </section>
  );
}
