// "Добавить участника": one field, a login or an e-mail typed exactly (spec 027 FR-4, mockup members-*).
// Errors are shown under the field (aria-invalid), success in a status line below the form.
import { useId, useState, type FormEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { addMemberByKey } from "./api";

export function MemberAdd({ projectId, onAdded }: { projectId: string; onAdded: () => Promise<unknown> }) {
  const id = useId();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const key = value.trim();
    if (key === "" || pending) {
      if (key === "") setError(errorMessage("validation_error"));
      return;
    }
    setPending(true);
    setError(null);
    setDone(false);
    try {
      await addMemberByKey(projectId, key.includes("@") ? { email: key } : { login: key });
      setValue("");
      setDone(true);
      await onAdded();
    } catch (e) {
      setError(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
    setPending(false);
  }

  return (
    <form className="member-add" data-form="add-member" onSubmit={(e) => void onSubmit(e)} noValidate>
      <div className="ui-field">
        <label htmlFor={`${id}-key`}>{t("projects.member_add_key_label")}</label>
        <input
          id={`${id}-key`}
          name="member_key"
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={value}
          disabled={pending}
          aria-invalid={error === null ? undefined : true}
          aria-describedby={`${id}-hint`}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
            setDone(false);
          }}
        />
        <p id={`${id}-hint`} className={error === null ? "member-hint" : "ui-error"} role={error === null ? undefined : "alert"}>
          {error ?? t("projects.member_add_key_hint")}
        </p>
      </div>
      <button type="submit" disabled={pending}>
        {t("projects.member_add_submit")}
      </button>
      {done ? <p role="status">{t("projects.member_added")}</p> : null}
    </form>
  );
}
