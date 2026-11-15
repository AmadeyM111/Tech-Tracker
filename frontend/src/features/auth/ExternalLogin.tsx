// Provider buttons under the login form (spec 029 FR-12; design gtrack-login-029). Only enabled providers
// are shown. Logos are the official brand files, unchanged (see brand/README.md for sources and rules).
import { useQuery } from "@tanstack/react-query";

import { t, type MessageKey } from "../../shared/i18n";
import googleG from "./brand/google-g.png";
import yandexButton from "./brand/login-with-yandex-14.svg";
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
  remember,
}: {
  name: ProviderName;
  remember: boolean;
}) {
  const label = t(LABELS[name]);
  const href = loginStartUrl(name, remember);
  if (name === "yandex") {
    // The image text is part of the official file; the link name comes from alt.
    return (
      <a className="ext-btn ext-btn-yandex" href={href}>
        <img src={yandexButton} alt={label} height={44} />
      </a>
    );
  }
  if (name === "google") {
    // «Sign in with Google», dark theme: the unchanged G mark beside the translated text.
    return (
      <a className="ext-btn ext-btn-google" href={href}>
        <img src={googleG} alt="" aria-hidden="true" width={20} height={20} />
        <span>{label}</span>
      </a>
    );
  }
  return (
    <a className="ext-btn ext-btn-plain" href={href}>
      {label}
    </a>
  );
}

export function ExternalLogin({ remember }: { remember: boolean }) {
  const providers = useQuery({
    queryKey: ["auth", "external-providers"],
    queryFn: () => listProviders(),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const names = providers.data ?? [];
  if (names.length === 0) return null;
  return (
    <div className="ext-login">
      <div className="ext-or">{t("auth.external_or")}</div>
      <p className="ext-hint">{t("auth.external_with")}</p>
      <div className="ext-list">
        {names.map((name) => (
          <ProviderButton key={name} name={name} remember={remember} />
        ))}
      </div>
    </div>
  );
}
