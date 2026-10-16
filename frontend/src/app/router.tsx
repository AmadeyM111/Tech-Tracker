import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { AuditPage } from "../features/admin/AuditPage";
import { UsersPage } from "../features/admin/UsersPage";
import { ChangePasswordPage } from "../features/auth/ChangePasswordPage";
import { LoginPage } from "../features/auth/LoginPage";
import { NoRolePage } from "../features/auth/NoRolePage";
import { MyTasksPage } from "../features/tasks/TaskList";
import { TaskPage } from "../features/tasks/TaskPage";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { me, type MeResponse } from "../features/auth/session";
import { useLogout } from "../features/auth/useLogout";
import { ApiError, setNavigationHandlers } from "../shared/api/client";
import { errorMessage, t } from "../shared/i18n";
import { ErrorAlert, useAlertState } from "../shared/ui/ErrorAlert";
import { Icon } from "../shared/ui/Icon";

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

function Home({ profile }: { profile: MeResponse }) {
  const alert = useAlertState();
  const logout = useLogout(alert);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeading = (useLocation().state as { focusHeading?: boolean } | null)?.focusHeading === true;
  useEffect(() => {
    // After the forced password change the modal is gone: keep focus in the page, not on <body>.
    if (focusHeading) headingRef.current?.focus();
  }, [focusHeading]);
  return (
    <>
      <h1 ref={headingRef} tabIndex={-1}>
        {t("app.home_title")}
      </h1>
      <ErrorAlert message={alert.message} seq={alert.seq} />
      <div className="ui-sidebar">
        <nav>
          <MenuItems profile={profile} />
        </nav>
        <button type="button" disabled={logout.pending} onClick={() => void logout.run()}>
          <Icon name="logout" />
          {t("auth.logout")}
        </button>
      </div>
    </>
  );
}

function Root({ insideMain }: { insideMain: boolean }) {
  return (
    <SessionGate insideMain={insideMain}>
      {(profile) => (
        <Landmark insideMain={insideMain} shell>
          <Home profile={profile} />
        </Landmark>
      )}
    </SessionGate>
  );
}

/** Admin screen: the session guard plus a capability; without it no request is made. */
function HomeLink() {
  return (
    <p>
      <Link to="/" className="ui-home-link">
        <Icon name="home" />
        {t("app.home_link")}
      </Link>
    </p>
  );
}

function AdminScreen({
  insideMain,
  capability,
  shell = false,
  children,
}: {
  insideMain: boolean;
  capability: MeResponse["capabilities"][number];
  shell?: boolean;
  children: (profile: MeResponse) => ReactNode;
}) {
  return (
    <SessionGate insideMain={insideMain}>
      {(profile) =>
        profile.capabilities.includes(capability) ? (
          <Landmark insideMain={insideMain} shell={shell}>
            <HomeLink />
            {children(profile)}
          </Landmark>
        ) : (
          <Landmark insideMain={insideMain}>
            <HomeLink />
            <ErrorAlert message={errorMessage("forbidden")} />
          </Landmark>
        )
      }
    </SessionGate>
  );
}

// Business screen (T82-T84 replaced the stub bodies); needs business_access.
function BusinessScreen({
  insideMain,
  children,
}: {
  insideMain: boolean;
  children: (profile: MeResponse) => ReactNode;
}) {
  return (
    <AdminScreen insideMain={insideMain} capability="business_access" shell>
      {(profile) => (
        <>
          <nav className="ui-sidebar">
            <MenuItems profile={profile} />
          </nav>
          {children(profile)}
        </>
      )}
    </AdminScreen>
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
 * Forced password change (T103): a modal window over a blank home substrate.
 * Only a user who must change the password sees it; everybody else goes to "/".
 */
function ForcedPasswordChange() {
  const session = useSession();
  // A cached answer may be stale (e.g. "no role" from before the redirect here): decide on the fresh one.
  const [fresh, setFresh] = useState(false);
  if (!fresh && !session.isFetching) setFresh(true);
  if (session.isPending || !fresh) return <p role="status">{t("app.loading")}</p>;
  if (session.isError) {
    const error = session.error;
    if (error instanceof ApiError && error.status === 403 && error.code === "password_change_required") {
      return <PasswordModal />;
    }
    return <Navigate to={redirectFor(error) ?? "/"} replace />;
  }
  if (!session.data.must_change_password) return <Navigate to="/" replace />;
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
        onPasswordChangeRequired: () => {
          // Already in the modal: a repeated 403 must not add a history step.
          if (pathRef.current === "/change-password") return;
          navigate("/change-password", { replace: true });
        },
        onNoRole: () => {
          // A 403 no_role inside the password modal (a forced user without a role) keeps the modal on screen.
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
      <Route path="/" element={<Root insideMain={insideMain} />} />
      <Route
        path="/admin/users"
        element={
          <AdminScreen insideMain={insideMain} capability="manage_accounts">
            {(profile) => <UsersPage canAssignRoles={profile.capabilities.includes("assign_roles")} />}
          </AdminScreen>
        }
      />
      <Route
        path="/admin/audit"
        element={
          <AdminScreen insideMain={insideMain} capability="view_audit">
            {() => <AuditPage />}
          </AdminScreen>
        }
      />
      <Route
        path="/projects"
        element={
          <BusinessScreen insideMain={insideMain}>
            {(profile) => <ProjectsPage canCreate={profile.capabilities.includes("project_create")} />}
          </BusinessScreen>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <BusinessScreen insideMain={insideMain}>
            {(profile) => <ProjectPage currentUserId={profile.id} currentRole={profile.role} />}
          </BusinessScreen>
        }
      />
      <Route
        path="/tasks/:taskId"
        element={
          <BusinessScreen insideMain={insideMain}>
            {() => <TaskPage />}
          </BusinessScreen>
        }
      />
      <Route
        path="/my-tasks"
        element={
          <BusinessScreen insideMain={insideMain}>
            {() => <MyTasksPage />}
          </BusinessScreen>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
