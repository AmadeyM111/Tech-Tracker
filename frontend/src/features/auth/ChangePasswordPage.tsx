import { useEffect, useRef, useState, type FormEvent } from "react";
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
  const alert = useAlertState();
  const logout = useLogout(alert);
  const currentRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    currentRef.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
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
      navigate("/", { replace: true });
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

  const busyAny = pending || logout.pending;
  return (
    <section className="ui-form">
      <h1>{t("auth.change_password_title")}</h1>
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
        />
        <TextField
          label={t("auth.new_password_label")}
          type="password"
          value={next}
          onChange={setNext}
          autoComplete="new-password"
          hint={t("auth.password_min_length_hint", { min: PASSWORD_MIN_LENGTH })}
          disabled={busyAny}
        />
        <TextField
          label={t("auth.confirm_password_label")}
          type="password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
          disabled={busyAny}
        />
        <button type="submit" disabled={busyAny}>
          {t("auth.change_password_submit")}
        </button>
        <button type="button" disabled={busyAny} onClick={() => void logout.run()}>
          {t("auth.logout")}
        </button>
      </form>
    </section>
  );
}
