// 019/R8-T19: own profile screen /profile (FR-3c, AC-34). The signed-in user edits the own first and last name;
// the login is shown as text only. The profile comes from the router (GET /me of the session guard).
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { updateMyName, type SetNameRequest } from "./api";
import type { MeResponse } from "./session";

// The session guards of router.tsx read this key; the saved answer replaces the cached profile.
const SESSION_KEY = ["auth", "me"] as const;

export function ProfilePage({ profile }: { profile: MeResponse }) {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const [firstName, setFirstName] = useState(profile.first_name ?? "");
  const [lastName, setLastName] = useState(profile.last_name ?? "");
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    const body: SetNameRequest = { first_name: firstName.trim(), last_name: lastName.trim() };
    busy.current = true;
    setPending(true);
    setSaved(false);
    alert.clear();
    try {
      const updated = await updateMyName(body);
      queryClient.setQueryData(SESSION_KEY, updated);
      setSaved(true);
    } catch (e) {
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return (
    <section className="ui-form">
      <h1>{t("profile.title")}</h1>
      <dl>
        <dt>{t("profile.login_label")}</dt>
        <dd>{profile.login}</dd>
      </dl>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <ErrorAlert message={alert.message} seq={alert.seq} />
        <TextField
          label={t("profile.first_name_label")}
          value={firstName}
          onChange={setFirstName}
          autoComplete="given-name"
          disabled={pending}
        />
        <TextField
          label={t("profile.last_name_label")}
          value={lastName}
          onChange={setLastName}
          autoComplete="family-name"
          disabled={pending}
        />
        <button type="submit" disabled={pending}>
          {t("profile.save")}
        </button>
        {saved ? <p role="status">{t("profile.saved")}</p> : null}
      </form>
    </section>
  );
}
