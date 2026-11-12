import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { GTrackLogo } from "../../shared/ui/GTrackLogo";
import { Icon } from "../../shared/ui/Icon";
import { TextField } from "../../shared/ui/TextField";
import { login, passwordResetStatus } from "./api";
import { FOCUS_HEADING_STATE } from "./session";
import "./auth-screens.css";

type LoginField = "login" | "password";

// Help block list (spec 005 v0.3, design brief section 3): the dictionary keys in document order.
const HELP_ITEM_KEYS = [
  "auth.help_item_1",
  "auth.help_item_2",
  "auth.help_item_3",
  "auth.help_item_4",
] as const;

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Back to an OAuth consent request after the login (spec 028 FR-6): only this path, never an arbitrary address.
  const next = searchParams.get("next");
  const consentNext = next !== null && next.startsWith("/oauth/authorize?") ? next : null;
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const loginRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [loginValue, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [shown, setShown] = useState(false);
  // Fields that were empty on the last submit; each shows its text under it (cleared on the next submit).
  const [emptyKeys, setEmptyKeys] = useState<LoginField[]>([]);

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
    // Spaces at the ends of the login count as empty. The first empty field takes focus; the general alert does not.
    const missing: LoginField[] = [];
    if (loginValue.trim() === "") missing.push("login");
    if (password === "") missing.push("password");
    setEmptyKeys(missing);
    if (missing.length > 0) {
      alert.show(errorMessage("validation_error"));
      (missing[0] === "login" ? loginRef : passwordRef).current?.focus();
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
      } else if (consentNext !== null) {
        navigate(consentNext, { replace: true });
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
      {consentNext !== null ? <p className="login-context">{t("oauth.login_context")}</p> : null}
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <TextField
          label={t("auth.login_label")}
          value={loginValue}
          onChange={setLogin}
          autoComplete="username"
          inputRef={loginRef}
          error={emptyKeys.includes("login") ? t("auth.login_required_login") : null}
          disabled={pending}
        />
        <TextField
          label={t("auth.password_label")}
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          inputRef={passwordRef}
          error={emptyKeys.includes("password") ? t("auth.login_required_password") : null}
          disabled={pending}
          reveal={{
            label: shown ? t("auth.hide_password") : t("auth.show_password"),
            shown,
            onToggle: () => setShown((v) => !v),
          }}
        />
        {/* Error sits directly above the submit button (design, login-error state). */}
        <ErrorAlert message={alert.message} seq={alert.seq} focus={emptyKeys.length === 0} />
        <button type="submit" className="login-submit" disabled={pending}>
          {pending && <Icon name="spinner" className="login-spin" />}
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
        <ol>
          {HELP_ITEM_KEYS.map((key) => (
            <li key={key}>{t(key)}</li>
          ))}
        </ol>
        {resetStatus.data?.enabled === true && <p>{t("auth.help_p2_registration")}</p>}
      </section>
    </section>
  );
}
