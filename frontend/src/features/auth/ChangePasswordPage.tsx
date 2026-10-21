import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { PASSWORD_MIN_LENGTH, errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { changePassword } from "./api";
import { useLogout } from "./useLogout";

export function ChangePasswordPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const id = useId();
  const alert = useAlertState();
  const logout = useLogout(alert);
  const currentRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNext, setShowNext] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  useEffect(() => {
    currentRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setShowCurrent(false);
    setShowNext(false);
    setShowConfirm(false);
    if (busy.current) return;
    if (current === "" || next === "" || confirm === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    if (next.length < PASSWORD_MIN_LENGTH) {
      alert.show(errorMessage("password_too_short"));
      return;
    }
    if (next !== confirm) {
      alert.show(t("auth.password_mismatch"));
      return;
    }
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await changePassword({ current_password: current, new_password: next });
      // The profile changed (flag, maybe role): "/" re-checks it through /me.
      queryClient.clear();
      navigate("/", { replace: true, state: { focusHeading: true } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        queryClient.clear();
        navigate("/login", { replace: true });
        return;
      }
      busy.current = false;
      setPending(false);
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
  }

  // Modal that cannot be dismissed (T103): no Escape, no overlay click, Tab stays inside.
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== "Tab") return;
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('input, button, select, textarea, a[href], [tabindex]:not([tabindex="-1"])'),
    ).filter((el) => !(el as HTMLButtonElement).disabled);
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    const active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    } else if (active instanceof HTMLElement && !event.currentTarget.contains(active)) {
      event.preventDefault();
      first.focus();
    }
  }

  const busyAny = pending || logout.pending;
  return (
    <div className="ui-overlay">
      <div role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-hint`} className="ui-dialog ui-form" onKeyDown={onKeyDown}>
        <h2 id={`${id}-title`}>{t("app.welcome_title")}</h2>
        <p id={`${id}-hint`}>{t("app.welcome_hint")}</p>
        <form onSubmit={(e) => void onSubmit(e)} noValidate>
          <ErrorAlert message={alert.message} seq={alert.seq} />
          <TextField
            label={t("auth.current_password_label")}
            type="password"
            value={current}
            onChange={setCurrent}
            autoComplete="current-password"
            inputRef={currentRef}
            disabled={busyAny}
            reveal={{ label: t("auth.show_current_password"), shown: showCurrent, onToggle: () => setShowCurrent((v) => !v) }}
          />
          <TextField
            label={t("auth.new_password_label")}
            type="password"
            value={next}
            onChange={setNext}
            autoComplete="new-password"
            hint={t("auth.password_min_length_hint", { min: PASSWORD_MIN_LENGTH })}
            disabled={busyAny}
            reveal={{ label: t("auth.show_new_password"), shown: showNext, onToggle: () => setShowNext((v) => !v) }}
          />
          <TextField
            label={t("auth.confirm_password_label")}
            type="password"
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
            disabled={busyAny}
            reveal={{ label: t("auth.show_confirm_password"), shown: showConfirm, onToggle: () => setShowConfirm((v) => !v) }}
          />
          <button type="submit" disabled={busyAny}>
            {t("auth.change_password_submit")}
          </button>
          <button type="button" disabled={busyAny} onClick={() => void logout.run()}>
            {t("auth.logout")}
          </button>
        </form>
      </div>
    </div>
  );
}
