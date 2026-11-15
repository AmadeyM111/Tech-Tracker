// «Способы входа» in the profile (spec 029 FR-18, FR-19; design gtrack-login-029): password, linked providers.
// Linking and unlinking only from the open session and only after a confirmation dialog.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import googleG from "./brand/google-g.png";
import yandexIcon from "./brand/login-with-yandex-8-1.svg";
import {
  LOGIN_METHODS_KEY,
  getLoginMethods,
  setInitialPassword,
  startLink,
  unlinkMethod,
  type LinkedIdentity,
  type ProviderName,
} from "./externalApi";
import "./external.css";

type Pending =
  | { kind: "link"; provider: ProviderName }
  | { kind: "unlink"; identity: LinkedIdentity };

// Official brand files, decorative: the provider name next to the icon is the accessible name.
function ProviderTitle({ provider }: { provider: string }) {
  const icon =
    provider === "yandex" ? yandexIcon : provider === "google" ? googleG : null;
  return (
    <strong className="methods-name">
      {icon !== null ? (
        <img
          className="methods-icon"
          src={icon}
          alt=""
          aria-hidden="true"
          width={24}
          height={24}
        />
      ) : null}
      {providerName(provider)}
    </strong>
  );
}

const providerName = (p: string) =>
  t(`profile.methods_provider.${p}` as MessageKey);
const formatDate = (iso: string) => new Date(iso).toLocaleDateString("ru-RU");

export function LoginMethods() {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const [searchParams] = useSearchParams();
  const [pending, setPending] = useState<Pending | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [passwordSaved, setPasswordSaved] = useState(false);
  const methods = useQuery({
    queryKey: LOGIN_METHODS_KEY,
    queryFn: () => getLoginMethods(),
    retry: false,
    refetchOnWindowFocus: false,
  });

  const unlink = useMutation({
    mutationFn: (id: string) => unlinkMethod(id),
    onSuccess: async () => {
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: LOGIN_METHODS_KEY });
    },
    onError: (e) => {
      setPending(null);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    },
  });
  const link = useMutation({
    mutationFn: (provider: ProviderName) => startLink(provider),
    onSuccess: (url) => window.location.assign(url),
    onError: (e) => {
      setPending(null);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    },
  });
  const password = useMutation({
    mutationFn: (value: string) => setInitialPassword(value),
    onSuccess: async () => {
      setPasswordOpen(false);
      setNewPassword("");
      setPasswordSaved(true);
      await queryClient.invalidateQueries({ queryKey: LOGIN_METHODS_KEY });
    },
    onError: (e) =>
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown")),
  });

  if (methods.data === undefined) return null;
  const { has_password: hasPassword, linked, available } = methods.data;
  const returned = searchParams.get("external");
  const returnedError = searchParams.get("external_error");

  function submitPassword(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    alert.clear();
    password.mutate(newPassword);
  }

  return (
    <section className="methods" aria-labelledby="methods-title">
      <h2 id="methods-title">{t("profile.methods_title")}</h2>
      <ErrorAlert message={alert.message} seq={alert.seq} />
      {returned === "linked" ? (
        <p role="status">{t("profile.methods_linked_ok")}</p>
      ) : null}
      {returnedError === "already_linked" ? (
        <p role="alert">{t("profile.methods_already_linked")}</p>
      ) : null}
      {passwordSaved ? (
        <p role="status">{t("profile.methods_password_saved")}</p>
      ) : null}

      <div className="methods-row">
        <div>
          <strong>{t("profile.methods_password")}</strong>
          <p className="methods-meta">
            {hasPassword
              ? t("profile.methods_password_set")
              : t("profile.methods_password_missing")}
          </p>
        </div>
        {hasPassword ? null : (
          <button type="button" onClick={() => setPasswordOpen((v) => !v)}>
            {t("profile.methods_password_set_button")}
          </button>
        )}
      </div>
      {passwordOpen && !hasPassword ? (
        <form className="methods-dialog" onSubmit={submitPassword} noValidate>
          <TextField
            label={t("profile.methods_password_new")}
            type="password"
            value={newPassword}
            onChange={setNewPassword}
            autoComplete="new-password"
            disabled={password.isPending}
          />
          <div className="methods-actions">
            <button type="submit" disabled={password.isPending}>
              {t("profile.methods_password_save")}
            </button>
          </div>
        </form>
      ) : null}

      {linked.map((identity) => (
        <div className="methods-row" key={identity.id}>
          <div>
            <ProviderTitle provider={identity.provider} />
            <p className="methods-meta">
              {t("profile.methods_linked", {
                date: formatDate(identity.linked_at),
              })}
            </p>
          </div>
          <button
            type="button"
            disabled={!identity.can_unlink}
            onClick={() => setPending({ kind: "unlink", identity })}
          >
            {t("profile.methods_unlink")}
          </button>
        </div>
      ))}
      {available.map((provider) => (
        <div className="methods-row" key={provider}>
          <div>
            <ProviderTitle provider={provider} />
            <p className="methods-meta">{t("profile.methods_not_linked")}</p>
          </div>
          <button
            type="button"
            onClick={() => setPending({ kind: "link", provider })}
          >
            {t("profile.methods_link")}
          </button>
        </div>
      ))}
      {linked.length > 0 && linked.every((i) => !i.can_unlink) ? (
        <p className="methods-hint">{t("profile.methods_last")}</p>
      ) : null}

      {pending !== null ? (
        <div
          className="methods-dialog"
          role="alertdialog"
          aria-labelledby="methods-dialog-title"
        >
          <h3 id="methods-dialog-title">
            {pending.kind === "link"
              ? t("profile.methods_link_title", {
                  provider: providerName(pending.provider),
                })
              : t("profile.methods_unlink_title", {
                  provider: providerName(pending.identity.provider),
                })}
          </h3>
          <p>
            {pending.kind === "link"
              ? t("profile.methods_link_text", {
                  provider: providerName(pending.provider),
                })
              : t("profile.methods_unlink_text", {
                  provider: providerName(pending.identity.provider),
                })}
          </p>
          <div className="methods-actions">
            <button type="button" onClick={() => setPending(null)}>
              {t("profile.methods_cancel")}
            </button>
            <button
              type="button"
              disabled={link.isPending || unlink.isPending}
              onClick={() =>
                pending.kind === "link"
                  ? link.mutate(pending.provider)
                  : unlink.mutate(pending.identity.id)
              }
            >
              {pending.kind === "link"
                ? t("profile.methods_link_confirm")
                : t("profile.methods_unlink")}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
