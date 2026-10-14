import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { ChangePasswordPage } from "../features/auth/ChangePasswordPage";
import { LoginPage } from "../features/auth/LoginPage";
import { NoRolePage } from "../features/auth/NoRolePage";
import { me } from "../features/auth/api";
import { ApiError, setNavigationHandlers } from "../shared/api/client";
import { errorMessage, t } from "../shared/i18n";
import { ErrorAlert } from "../shared/ui/ErrorAlert";

// Session check shared by the guards (not a polled query: key is its own).
const SESSION_KEY = ["auth", "me"] as const;

function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => me(),
    // A 401/403 is an answer, not a failure to retry; a session check must not
    // extend the session by itself on every window focus.
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** Where a failed session check sends the user; null if it is not a redirect. */
function redirectFor(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 401) return "/login";
  if (error.status === 403 && error.code === "password_change_required") return "/change-password";
  if (error.status === 403 && error.code === "no_role") return "/no-role";
  return null;
}

// "/" has no section screens until T24+: a landmark with a heading is the stub.
// Inside the App shell the <main> already exists, so a plain wrapper is used.
function Landmark({ insideMain, children }: { insideMain: boolean; children: ReactNode }) {
  return insideMain ? <div>{children}</div> : <main>{children}</main>;
}

function Root({ insideMain }: { insideMain: boolean }) {
  const session = useSession();
  if (session.isPending) {
    // Not a landmark: the page content has not arrived yet.
    return <p role="status">{t("app.loading")}</p>;
  }
  if (session.isError) {
    const target = redirectFor(session.error);
    if (target !== null) return <Navigate to={target} replace />;
    const code = session.error instanceof ApiError ? session.error.code : "unknown";
    return (
      <Landmark insideMain={insideMain}>
        <ErrorAlert message={errorMessage(code)} />
        <button type="button" onClick={() => void session.refetch()}>
          {t("app.retry")}
        </button>
      </Landmark>
    );
  }
  return (
    <Landmark insideMain={insideMain}>
      <h1>{t("app.home_title")}</h1>
    </Landmark>
  );
}

/**
 * change-password and no-role stay reachable with any session state but 401:
 * the form is shown at once, the check only redirects to the login page.
 */
function NeedsSession({ children }: { children: ReactNode }) {
  const session = useSession();
  if (session.error instanceof ApiError && session.error.status === 401) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function GuestOnly({ children }: { children: ReactNode }) {
  const session = useSession();
  if (session.data !== undefined) return <Navigate to="/" replace />;
  return <>{children}</>;
}

// The one place where the shared client learns how to navigate and drop the cache.
function useClientHandlers(): void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const pathRef = useRef(pathname);
  useEffect(() => {
    pathRef.current = pathname;
  }, [pathname]);

  useEffect(
    () =>
      setNavigationHandlers({
        onUnauthenticated: () => {
          // On the login page there is no session data to drop and nothing to leave.
          if (pathRef.current === "/login") return;
          queryClient.clear();
          navigate("/login", { replace: true });
        },
        onPasswordChangeRequired: () => navigate("/change-password", { replace: true }),
        onNoRole: () => {
          // A user without a role may still change the password voluntarily (FR-56).
          if (pathRef.current === "/change-password" || pathRef.current === "/no-role") return;
          navigate("/no-role", { replace: true });
        },
      }),
    [navigate, queryClient],
  );
}

// Only <Routes>: the Router itself lives in providers.tsx.
export function AppRoutes({ insideMain = false }: { insideMain?: boolean }) {
  useClientHandlers();
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <GuestOnly>
            <LoginPage />
          </GuestOnly>
        }
      />
      <Route
        path="/change-password"
        element={
          <NeedsSession>
            <ChangePasswordPage />
          </NeedsSession>
        }
      />
      <Route
        path="/no-role"
        element={
          <NeedsSession>
            <NoRolePage />
          </NeedsSession>
        }
      />
      <Route path="/" element={<Root insideMain={insideMain} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
