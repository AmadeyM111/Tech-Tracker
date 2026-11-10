// 019/R8-T19: own profile screen /profile (FR-3c, AC-34). The signed-in user edits the own first and last name;
// the login is shown as text only. The profile comes from the router (GET /me of the session guard).
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { updateMyName, type SetNameRequest } from "./api";
import type { MeResponse } from "./session";

// The session guards of router.tsx read this key; the saved answer replaces the cached profile.
const SESSION_KEY = ["auth", "me"] as const;

type NameField = "first" | "last";

// Text under an empty name field (P2 of the PR #29 design review).
const EMPTY_TEXT: Record<NameField, MessageKey> = {
  first: "profile.first_name_required",
  last: "profile.last_name_required",
};

// Server codes that refer to one name field: the text goes under that field, not into the general block.
const FIELD_CODES: Record<string, NameField | undefined> = {
  first_name_invalid: "first",
  last_name_invalid: "last",
};

export function ProfilePage({ profile }: { profile: MeResponse }) {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const busy = useRef(false);
  const firstRef = useRef<HTMLInputElement>(null);
  const lastRef = useRef<HTMLInputElement>(null);
  const [firstName, setFirstName] = useState(profile.first_name ?? "");
  const [lastName, setLastName] = useState(profile.last_name ?? "");
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  // Fields that were empty on the last submit (cleared on the next submit).
  const [emptyKeys, setEmptyKeys] = useState<NameField[]>([]);
  // A server error that refers to one field; its text goes under that field.
  const [fieldError, setFieldError] = useState<{ field: NameField; message: string } | null>(null);

  // The field of a server error takes focus once the form is enabled again (the inputs are disabled while pending).
  useEffect(() => {
    if (fieldError !== null) (fieldError.field === "first" ? firstRef : lastRef).current?.focus();
  }, [fieldError]);

  function errorFor(key: NameField): string | null {
    if (emptyKeys.includes(key)) return t(EMPTY_TEXT[key]);
    return fieldError?.field === key ? fieldError.message : null;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    setFieldError(null);
    setSaved(false);
    alert.clear();
    const trimmedFirst = firstName.trim();
    const trimmedLast = lastName.trim();
    // Empty names (spaces count as empty) are refused before any request. The first empty field takes focus.
    const missing: NameField[] = [];
    if (trimmedFirst === "") missing.push("first");
    if (trimmedLast === "") missing.push("last");
    setEmptyKeys(missing);
    if (missing.length > 0) {
      alert.show(errorMessage("validation_error"));
      (missing[0] === "first" ? firstRef : lastRef).current?.focus();
      return;
    }
    const body: SetNameRequest = { first_name: trimmedFirst, last_name: trimmedLast };
    busy.current = true;
    setPending(true);
    try {
      const updated = await updateMyName(body);
      queryClient.setQueryData(SESSION_KEY, updated);
      setSaved(true);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "unknown";
      const field = Object.hasOwn(FIELD_CODES, code) ? FIELD_CODES[code] : undefined;
      if (field === undefined) {
        alert.show(errorMessage(code));
      } else {
        setFieldError({ field, message: errorMessage(code) });
      }
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
        <ErrorAlert message={alert.message} seq={alert.seq} focus={emptyKeys.length === 0} />
        <TextField
          label={t("profile.first_name_label")}
          value={firstName}
          onChange={setFirstName}
          autoComplete="given-name"
          inputRef={firstRef}
          error={errorFor("first")}
          disabled={pending}
        />
        <TextField
          label={t("profile.last_name_label")}
          value={lastName}
          onChange={setLastName}
          autoComplete="family-name"
          inputRef={lastRef}
          error={errorFor("last")}
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
