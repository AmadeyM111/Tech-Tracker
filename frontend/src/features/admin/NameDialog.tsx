import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";

export interface NameDialogProps {
  login: string;
  /** Current first name; an empty string means "not set". */
  firstName: string;
  /** Current last name; an empty string means "not set". */
  lastName: string;
  /** Saves both names (trimmed here); rejects with ApiError on failure. */
  onSave: (firstName: string, lastName: string) => Promise<void>;
  onClose: () => void;
}

/** Modal dialog: change a user's first and last name (AC-35). Focus returns to the opener. */
export function NameDialog(props: NameDialogProps) {
  const { login, firstName, lastName, onSave, onClose } = props;
  const id = useId();
  const alert = useAlertState();
  const [first, setFirst] = useState(firstName);
  const [last, setLast] = useState(lastName);
  const [pending, setPending] = useState(false);
  const firstRef = useRef<HTMLInputElement>(null);
  const lastRef = useRef<HTMLInputElement>(null);
  const saveRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement;
    firstRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (pending) return;
    alert.clear();
    const trimmedFirst = first.trim();
    const trimmedLast = last.trim();
    // Empty names are refused here, before any request (same rules as the server, RG-3).
    if (trimmedFirst === "") {
      alert.show(errorMessage("first_name_invalid"));
      return;
    }
    if (trimmedLast === "") {
      alert.show(errorMessage("last_name_invalid"));
      return;
    }
    setPending(true);
    try {
      await onSave(trimmedFirst, trimmedLast);
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
    const order = [firstRef.current, lastRef.current, saveRef.current, cancelRef.current].filter(
      (el): el is HTMLInputElement | HTMLButtonElement => el !== null && !el.disabled,
    );
    const head = order[0];
    const tail = order[order.length - 1];
    if (head === undefined || tail === undefined) return;
    const active = document.activeElement;
    if (event.shiftKey && active === head) {
      event.preventDefault();
      tail.focus();
    } else if (!event.shiftKey && active === tail) {
      event.preventDefault();
      head.focus();
    } else if (!order.some((el) => el === active)) {
      event.preventDefault();
      head.focus();
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
        <h2 id={`${id}-title`}>{t("admin.users.name_dialog_title", { login })}</h2>
        <form onSubmit={(e) => void submit(e)} noValidate>
          <TextField
            label={t("admin.users.first_name_label")}
            name="first_name"
            value={first}
            onChange={setFirst}
            autoComplete="given-name"
            inputRef={firstRef}
            disabled={pending}
          />
          <TextField
            label={t("admin.users.last_name_label")}
            name="last_name"
            value={last}
            onChange={setLast}
            autoComplete="family-name"
            inputRef={lastRef}
            disabled={pending}
          />
          <ErrorAlert message={alert.message} seq={alert.seq} />
          <button type="submit" data-action="save" ref={saveRef} disabled={pending}>
            {t("admin.users.name_save")}
          </button>{" "}
          <button type="button" data-action="cancel" ref={cancelRef} disabled={pending} onClick={onClose}>
            {t("admin.users.name_cancel")}
          </button>
        </form>
      </div>
    </div>
  );
}
