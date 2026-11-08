import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";

export interface EmailDialogProps {
  login: string;
  /** Current address of the user, or null. */
  email: string | null;
  /** Saves the address (empty field -> null); rejects with ApiError on failure. */
  onSave: (email: string | null) => Promise<void>;
  onClose: () => void;
}

/** Modal dialog: change or clear a user's email (FR-2). Focus returns to the opener. */
export function EmailDialog(props: EmailDialogProps) {
  const { login, email, onSave, onClose } = props;
  const id = useId();
  const alert = useAlertState();
  const [value, setValue] = useState(email ?? "");
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const saveRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement;
    inputRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    alert.clear();
    const trimmed = value.trim();
    try {
      await onSave(trimmed === "" ? null : trimmed);
      onClose();
    } catch (e) {
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
      setPending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!pending) onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const order = [inputRef.current, saveRef.current, cancelRef.current].filter(
      (el): el is HTMLInputElement | HTMLButtonElement => el !== null && !el.disabled,
    );
    const first = order[0];
    const last = order[order.length - 1];
    if (first === undefined || last === undefined) return;
    const active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    } else if (!order.some((el) => el === active)) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="ui-overlay">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className="ui-dialog"
        onKeyDown={onKeyDown}
      >
        <h2 id={`${id}-title`}>{t("admin.users.email_dialog_title", { login })}</h2>
        <form onSubmit={(e) => void submit(e)} noValidate>
          <TextField
            label={t("admin.users.email_label")}
            name="email"
            value={value}
            onChange={setValue}
            autoComplete="email"
            inputRef={inputRef}
            hint={t("admin.users.email_dialog_hint")}
            disabled={pending}
          />
          <ErrorAlert message={alert.message} seq={alert.seq} />
          <button type="submit" data-action="save" ref={saveRef} disabled={pending}>
            {t("admin.users.email_save")}
          </button>{" "}
          <button type="button" className="ui-btn-secondary" data-action="cancel" ref={cancelRef} disabled={pending} onClick={onClose}>
            {t("admin.users.email_cancel")}
          </button>
        </form>
      </div>
    </div>
  );
}
