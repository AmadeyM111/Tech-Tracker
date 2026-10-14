import { useEffect, useId, useRef, type KeyboardEvent } from "react";

import { t } from "../i18n";

export interface ConfirmDialogProps {
  title: string;
  message: string;
  /** True while the confirmed action is in flight: both buttons are disabled. */
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmation of a destructive action (NFR-7): alertdialog, focus moves inside
 * (on the safe button), Tab stays inside, Escape cancels, focus returns to the
 * control that opened it.
 */
export function ConfirmDialog(props: ConfirmDialogProps) {
  const { title, message, pending, onConfirm, onCancel } = props;
  const id = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement;
    cancelRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!pending) onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    // Only two controls: cycle between them.
    const first = cancelRef.current;
    const last = confirmRef.current;
    if (first === null || last === null) return;
    const active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    } else if (active !== first && active !== last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="ui-overlay">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-message`}
        className="ui-dialog"
        onKeyDown={onKeyDown}
      >
        <h2 id={`${id}-title`}>{title}</h2>
        <p id={`${id}-message`}>{message}</p>
        <button type="button" data-action="cancel" ref={cancelRef} disabled={pending} onClick={onCancel}>
          {t("admin.cancel")}
        </button>{" "}
        <button type="button" data-action="confirm" ref={confirmRef} disabled={pending} onClick={onConfirm}>
          {t("admin.confirm")}
        </button>
      </div>
    </div>
  );
}
