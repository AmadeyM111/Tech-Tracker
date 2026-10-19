import { useRef } from "react";

import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { useFocusHeadingOnArrival } from "./session";
import { useLogout } from "./useLogout";

export function NoRolePage() {
  const alert = useAlertState();
  const logout = useLogout(alert);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useFocusHeadingOnArrival(headingRef);
  return (
    <section className="ui-form">
      <h1 ref={headingRef} tabIndex={-1}>
        {t("auth.no_role_title")}
      </h1>
      <p>{errorMessage("no_role")}</p>
      <ErrorAlert message={alert.message} seq={alert.seq} />
      <button type="button" disabled={logout.pending} onClick={() => void logout.run()}>
        {t("auth.logout")}
      </button>
    </section>
  );
}
