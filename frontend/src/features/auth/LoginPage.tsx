import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { GTrackLogo } from "../../shared/ui/GTrackLogo";
import { TextField } from "../../shared/ui/TextField";
import { login, passwordResetStatus } from "./api";
import { FOCUS_HEADING_STATE } from "./session";
import "./auth-screens.css";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const loginRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [loginValue, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [shown, setShown] = useState(false);

  const resetStatus = useQuery({
    queryKey: ["auth", "password-reset-status"],
    queryFn: () => passwordResetStatus(),
    retry: false,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    loginRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setShown(false);
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
        navigate("/", { replace: true, state: FOCUS_HEADING_STATE });
      }
    } catch (e) {
      busy.current = false;
      setPending(false);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
  }

  return (
    <section className="ui-form login-card">
      <div className="ui-brand">
        <GTrackLogo />
        <h1>{t("auth.login_title")}</h1>
      </div>
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
          reveal={{
            label: shown ? t("auth.hide_password") : t("auth.show_password"),
            shown,
            onToggle: () => setShown((v) => !v),
          }}
        />
        <button type="submit" className="login-submit" disabled={pending}>
          {t("auth.login_submit")}
        </button>
      </form>
      {/* Registration is enabled by the same flag as password reset (RG-13). */}
      {resetStatus.data?.enabled === true && (
        <div className="login-links">
          <Link to="/password-reset">{t("auth.forgot_password")}</Link>
          <Link to="/register">{t("auth.register_link")}</Link>
        </div>
      )}
      <section className="ui-login-help" aria-labelledby="login-help-title">
        <h2 id="login-help-title">{t("auth.help_title")}</h2>
        <p>{t("auth.help_p1")}</p>
        {resetStatus.data?.enabled === true && <p>{t("auth.help_p2_registration")}</p>}
      </section>
    </section>
  );
}
