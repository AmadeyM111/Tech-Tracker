import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { AuditPage } from "../features/admin/AuditPage";
import { UsersPage } from "../features/admin/UsersPage";
import { ChangePasswordPage } from "../features/auth/ChangePasswordPage";
import { LoginPage } from "../features/auth/LoginPage";
import { NoRolePage } from "../features/auth/NoRolePage";
import { MyTasksPage } from "../features/tasks/TaskList";
import { TaskPage } from "../features/tasks/TaskPage";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { focusHeadingState, me, type MeResponse } from "../features/auth/session";
import { useLogout } from "../features/auth/useLogout";
import { ApiError, setNavigationHandlers } from "../shared/api/client";
import { errorMessage, t } from "../shared/i18n";
import { ErrorAlert, useAlertState } from "../shared/ui/ErrorAlert";
import { Icon } from "../shared/ui/Icon";

// Session check shared by the guards (not a polled query: key is its own).
const SESSION_KEY = ["auth", "me"] as const;

// A profile this young is not asked for again when the next screen mounts: the redirect from "/" to the
// start screen must not cost a second `GET /me` (003/AC-36). Freshness is counted from `dataUpdatedAt` of the
// last successful answer; a query that has only an error (no data) is never fresh and is re-asked on mount.
const SESSION_FRESH_MS = 5_000;

function useSession(staleTime: number = SESSION_FRESH_MS) {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => me(),
    // A 401/403 is an answer, not a failure to retry; a session check must not
    // extend the session by itself on every window focus.
    retry: false,
    refetchOnWindowFocus: false,
    staleTime,
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

type Capability = MeResponse["capabilities"][number];

/**
 * Start screens (003/FR-3). `/no-role` is not returned here: a profile without a role
 * answers 403 `no_role`, and `redirectFor` leads there.
 */
export type StartPath = "/change-password" | "/projects" | "/admin/users" | "/admin/audit";

/** 003/FR-3 (items 1, 3-6) by the `GET /me` profile. Pure function, no requests. */
export function startPath(profile: Pick<MeResponse, "must_change_password" | "capabilities">): StartPath {
  const has = (capability: Capability) => profile.capabilities.includes(capability);
  if (profile.must_change_password) return "/change-password";
  if (has("business_access")) return "/projects";
  if (has("manage_accounts")) return "/admin/users";
  if (has("view_audit")) return "/admin/audit";
  return "/admin/users";
}

// Inside the App shell the <main> already exists, so a plain wrapper is used.
// `shell` adds the two-column layout (left navigation panel, T90); the markup order stays the same.
function Landmark({
  insideMain,
  shell = false,
  children,
}: {
  insideMain: boolean;
  shell?: boolean;
  children: ReactNode;
}) {
  const className = shell ? "ui-shell" : undefined;
  return insideMain ? <div className={className}>{children}</div> : <main className={className}>{children}</main>;
}

/**
 * Session guard of the application screens: decides by the result of the `me`
 * request (not only by the client callbacks, which fire once per series).
 */
function SessionGate({
  insideMain,
  children,
}: {
  insideMain: boolean;
  children: (profile: MeResponse) => ReactNode;
}) {
  const session = useSession();
  const { state } = useLocation();
  if (session.isPending) {
    // Not a landmark: the page content has not arrived yet.
    return <p role="status">{t("app.loading")}</p>;
  }
  if (session.isError) {
    const target = redirectFor(session.error);
    if (target !== null) return <Navigate to={target} replace state={focusHeadingState(state)} />;
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
  return <>{children(session.data)}</>;
}

/** Menu items by capabilities (FR-10); the server checks access itself. */
function MenuItems({ profile }: { profile: MeResponse }) {
  const has = (capability: MeResponse["capabilities"][number]) => profile.capabilities.includes(capability);
  return (
    <>
      {has("business_access") ? (
        <>
          <p>
            <NavLink to="/projects" end>
              <Icon name="projects" />
              {t("nav.projects")}
            </NavLink>
          </p>
          <p>
            <NavLink to="/my-tasks">
              <Icon name="tasks" />
              {t("nav.my_tasks")}
            </NavLink>
          </p>
        </>
      ) : null}
      {has("manage_accounts") ? (
        <p>
          <NavLink to="/admin/users">
            <Icon name="users" />
            {t("admin.home_users_link")}
          </NavLink>
        </p>
      ) : null}
      {has("view_audit") ? (
        <p>
          <NavLink to="/admin/audit">
            <Icon name="audit" />
            {t("admin.home_audit_link")}
          </NavLink>
        </p>
      ) : null}
    </>
  );
}

/** Sidebar (003/FR-10): items by capabilities, "Logout" at the bottom; makes no network requests itself. */
function Sidebar({ profile }: { profile: MeResponse }) {
  const alert = useAlertState();
  const logout = useLogout(alert);
  return (
    <div className="ui-sidebar">
      <nav aria-label={t("app.menu_label")}>
        <MenuItems profile={profile} />
      </nav>
      <button type="button" data-action="logout" disabled={logout.pending} onClick={() => void logout.run()}>
        <Icon name="logout" />
        {t("auth.logout")}
      </button>
      <ErrorAlert message={alert.message} seq={alert.seq} />
    </div>
  );
}

/**
 * `/` and any path without a screen (003/FR-1, FR-6...FR-9): only the session check and a
 * replacing redirect to the start screen. A failed check redirects as usual (`SessionGate`).
 */
function StartRedirect({ insideMain }: { insideMain: boolean }) {
  const { state } = useLocation();
  return (
    <SessionGate insideMain={insideMain}>
      {(profile) => <Navigate to={startPath(profile)} replace state={focusHeadingState(state)} />}
    </SessionGate>
  );
}

/**
 * Screen with a role (003/FR-10, FR-11, FR-14): the session guard, the shell with the Sidebar,
 * then the content or a refusal. Without the capability no section data is requested.
 */
function RoleScreen({
  insideMain,
  capability,
  children,
}: {
  insideMain: boolean;
  capability: Capability;
  children: (profile: MeResponse) => ReactNode;
}) {
  return (
    <SessionGate insideMain={insideMain}>
      {(profile) => (
        <Landmark insideMain={insideMain} shell>
          <Sidebar profile={profile} />
          {profile.capabilities.includes(capability) ? (
            children(profile)
          ) : (
            <ErrorAlert message={errorMessage("forbidden")} />
          )}
        </Landmark>
      )}
    </SessionGate>
  );
}

/**
 * no-role stays reachable with any session state but 401: the page is shown at
 * once, the check only redirects to the login page.
 */
function NeedsSession({ children }: { children: ReactNode }) {
  const session = useSession();
  if (session.error instanceof ApiError && session.error.status === 401) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

/**
 * Forced password change (T103): a modal window over a blank substrate.
 * Only a user who must change the password sees it; everybody else goes to their start screen.
 */
function ForcedPasswordChange() {
  const session = useSession(0);
  const { state } = useLocation();
  // A cached answer may be stale (e.g. "no role" from before the redirect here): decide on the fresh one.
  const [fresh, setFresh] = useState(false);
  if (!fresh && !session.isFetching) setFresh(true);
  if (session.isPending || !fresh) return <p role="status">{t("app.loading")}</p>;
  if (session.isError) {
    const error = session.error;
    if (error instanceof ApiError && error.status === 403 && error.code === "password_change_required") {
      return <PasswordModal />;
    }
    return <Navigate to={redirectFor(error) ?? "/"} replace state={focusHeadingState(state)} />;
  }
  if (!session.data.must_change_password) {
    return <Navigate to={startPath(session.data)} replace state={focusHeadingState(state)} />;
  }
  return <PasswordModal />;
}

function PasswordModal() {
  return (
    <>
      <div className="ui-shell" aria-hidden="true" />
      <ChangePasswordPage />
    </>
  );
}

function GuestOnly({ children }: { children: ReactNode }) {
  const session = useSession();
  const { state } = useLocation();
  if (session.data !== undefined) {
    return <Navigate to={startPath(session.data)} replace state={focusHeadingState(state)} />;
  }
  return <>{children}</>;
}

// The one place where the shared client learns how to navigate and drop the cache.
function useClientHandlers(): void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pathname, state } = useLocation();
  const pathRef = useRef(pathname);
  const stateRef = useRef<unknown>(state);
  useEffect(() => {
    pathRef.current = pathname;
    stateRef.current = state;
  }, [pathname, state]);

  useEffect(
    () =>
      setNavigationHandlers({
        onUnauthenticated: () => {
          // On the login page there is no session data to drop and nothing to leave.
          if (pathRef.current === "/login") return;
          queryClient.clear();
          navigate("/login", { replace: true, state: focusHeadingState(stateRef.current) });
        },
        onPasswordChangeRequired: () => {
          // Already in the modal: a repeated 403 must not add a history step.
          if (pathRef.current === "/change-password") return;
          navigate("/change-password", { replace: true });
        },
        onNoRole: () => {
          // A 403 no_role inside the password modal (a forced user without a role) keeps the modal on screen.
          if (pathRef.current === "/change-password" || pathRef.current === "/no-role") return;
          navigate("/no-role", { replace: true, state: focusHeadingState(stateRef.current) });
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
          <ForcedPasswordChange />
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
      <Route path="/" element={<StartRedirect insideMain={insideMain} />} />
      <Route
        path="/admin/users"
        element={
          <RoleScreen insideMain={insideMain} capability="manage_accounts">
            {(profile) => <UsersPage canAssignRoles={profile.capabilities.includes("assign_roles")} />}
          </RoleScreen>
        }
      />
      <Route
        path="/admin/audit"
        element={
          <RoleScreen insideMain={insideMain} capability="view_audit">
            {() => <AuditPage />}
          </RoleScreen>
        }
      />
      <Route
        path="/projects"
        element={
          <RoleScreen insideMain={insideMain} capability="business_access">
            {(profile) => <ProjectsPage canCreate={profile.capabilities.includes("project_create")} />}
          </RoleScreen>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <RoleScreen insideMain={insideMain} capability="business_access">
            {(profile) => <ProjectPage currentUserId={profile.id} currentRole={profile.role} />}
          </RoleScreen>
        }
      />
      <Route
        path="/tasks/:taskId"
        element={
          <RoleScreen insideMain={insideMain} capability="business_access">
            {() => <TaskPage />}
          </RoleScreen>
        }
      />
      <Route
        path="/my-tasks"
        element={
          <RoleScreen insideMain={insideMain} capability="business_access">
            {() => <MyTasksPage />}
          </RoleScreen>
        }
      />
      <Route path="*" element={<StartRedirect insideMain={insideMain} />} />
    </Routes>
  );
}
