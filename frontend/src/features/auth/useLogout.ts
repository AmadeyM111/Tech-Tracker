import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage } from "../../shared/i18n";
import type { AlertState } from "../../shared/ui/ErrorAlert";
import { logout } from "./api";

/** Logout action shared by the screens that stay available without a role/password. */
export function useLogout(alert: AlertState) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const busy = useRef(false);
  const [pending, setPending] = useState(false);

  async function run(): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await logout();
    } catch (e) {
      // 401: the session is already gone, leaving the screen is the right outcome.
      if (!(e instanceof ApiError && e.status === 401)) {
        busy.current = false;
        setPending(false);
        alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
        return;
      }
    }
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  return { run, pending };
}
