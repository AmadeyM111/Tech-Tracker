// Provider buttons under the login form (spec 029 FR-12; design gtrack-login-029). Only enabled providers
// are shown. Logos are the official brand files, unchanged (see brand/README.md for sources and rules).
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { t, type MessageKey } from "../../shared/i18n";
import googleG from "./brand/google-g.png";
import yandexButton from "./brand/login-with-yandex-14.svg";
import { useLegalStatus } from "../legal/api";
import { PdnConsentField } from "../legal/PdnConsentField";
import { listProviders, loginStartUrl, type ProviderName } from "./externalApi";
import "./external.css";

const LABELS: Record<ProviderName, MessageKey> = {
  yandex: "auth.external_yandex",
  vk: "auth.external_vk",
  google: "auth.external_google",
};

const ERROR_CODES = [
  "login_failed",
  "cancelled",
  "provider_unavailable",
  "state_invalid",
  "pdn_consent_required", // spec 021
] as const;

/** Text for ?external_error=<code> on /login; an unknown code gives nothing (the value is never printed). */
export function externalErrorText(
  code: string | null,
  provider: string | null = null,
): string | null {
  if (code === null || !(ERROR_CODES as readonly string[]).includes(code))
    return null;
  // The provider name comes from a fixed list, never from the address text.
  const name =
    provider !== null && provider in LABELS
      ? t(`profile.methods_provider.${provider}` as MessageKey)
      : t("auth.external_generic_name");
  return t(`auth.external_error.${code}` as MessageKey, { provider: name });
}

/** Provider button. Yandex: the official button file as it is (its colours and text must not change). */
function ProviderButton({
  name,
  href,
}: {
  name: ProviderName;
  /** null: the consent box is not ticked yet (spec 021) - the button stays visible but is inert. */
  href: string | null;
}) {
  const label = t(LABELS[name]);
  // Without an address the link is inert (no navigation) and announced as disabled; the brand files stay as they are.
  const link = href === null ? { role: "link", "aria-disabled": true } : { href };
  if (name === "yandex") {
    // The image text is part of the official file; the link name comes from alt.
    return (
      <a className="ext-btn ext-btn-yandex" {...link}>
        <img src={yandexButton} alt={label} height={44} />
      </a>
    );
  }
  if (name === "google") {
    // «Sign in with Google», dark theme: the unchanged G mark beside the translated text.
    return (
      <a className="ext-btn ext-btn-google" {...link}>
        <img src={googleG} alt="" aria-hidden="true" width={20} height={20} />
        <span>{label}</span>
      </a>
    );
  }
  return (
    <a className="ext-btn ext-btn-plain" {...link}>
      {label}
    </a>
  );
}

/**
 * Spec 021: while the consent is required the buttons stay disabled until the box is ticked. The page that has its own
 * box (/register) passes the state in `consent`; otherwise the box is drawn here (/login).
 */
export function ExternalLogin({ remember, consent }: { remember: boolean; consent?: { agreed: boolean } }) {
  const providers = useQuery({
    queryKey: ["auth", "external-providers"],
    queryFn: () => listProviders(),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const names = providers.data ?? [];
  const legal = useLegalStatus(names.length > 0);
  const [ownAgreed, setOwnAgreed] = useState(false);
  const consentOn = legal.data?.enabled === true;
  const agreed = consent?.agreed ?? ownAgreed;
  const version = consentOn ? (legal.data?.version ?? null) : null;
  if (names.length === 0) return null;
  return (
    <div className="ext-login">
      <div className="ext-or">{t("auth.external_or")}</div>
      <p className="ext-hint">{t("auth.external_with")}</p>
      {consentOn && consent === undefined ? (
        <PdnConsentField checked={ownAgreed} onChange={setOwnAgreed} />
      ) : null}
      <div className="ext-list">
        {names.map((name) => (
          <ProviderButton
            key={name}
            name={name}
            href={consentOn && !agreed ? null : loginStartUrl(name, remember, version)}
          />
        ))}
      </div>
      {consentOn && !agreed ? <p className="ext-hint">{t("legal.providers_need_consent")}</p> : null}
    </div>
  );
}
