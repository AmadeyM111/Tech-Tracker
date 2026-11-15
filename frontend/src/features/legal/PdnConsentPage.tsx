// Spec 021 FR-5: «Подтвердите согласие» for a signed-in user who has not given the current consent yet.
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { useLogout } from "../auth/useLogout";
import { safeConsentNext } from "../oauth/next";
import { acceptPdnConsent, useLegalStatus } from "./api";
import { PdnConsentField } from "./PdnConsentField";
import "../auth/auth-screens.css";

export function PdnConsentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  // Back to the OAuth consent request the user came from (as after the forced password change).
  const consentNext = safeConsentNext(searchParams.get("next"));
  const alert = useAlertState();
  const logout = useLogout(alert);
  const status = useLegalStatus();
  const busy = useRef(false);
  const [agreed, setAgreed] = useState(false);
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    if (!agreed) {
      setMissing(true);
      return;
    }
    const version = status.data?.version;
    if (version === undefined) {
      alert.show(errorMessage("unknown"));
      return;
    }
    busy.current = true;
    setPending(true);
    setMissing(false);
    alert.clear();
    try {
      await acceptPdnConsent(version);
      queryClient.clear();
      if (consentNext !== null) navigate(consentNext, { replace: true });
      else navigate("/", { replace: true, state: { focusHeading: true } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        queryClient.clear();
        navigate("/login", { replace: true });
        return;
      }
      const code = e instanceof ApiError ? e.code : "unknown";
      // The text was updated while the screen was open: take the new version, the user ticks again.
      if (code === "pdn_consent_version_mismatch") void status.refetch();
      busy.current = false;
      setPending(false);
      alert.show(errorMessage(code));
    }
  }

  const busyAny = pending || logout.pending;
  return (
    <section className="ui-form login-card">
      <h1>{t("legal.confirm_title")}</h1>
      <p>{t("legal.confirm_hint")}</p>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <PdnConsentField
          checked={agreed}
          onChange={(v) => {
            setAgreed(v);
            if (v) setMissing(false);
          }}
          error={missing ? t("legal.consent_required") : null}
          disabled={busyAny}
        />
        <ErrorAlert message={alert.message} seq={alert.seq} />
        <button type="submit" className="login-submit" disabled={busyAny}>
          {t("legal.confirm_submit")}
        </button>
        <button
          type="button"
          className="pdn-consent-logout"
          disabled={busyAny}
          onClick={() => void logout.run()}
        >
          {t("auth.logout")}
        </button>
      </form>
    </section>
  );
}
