import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t, type MessageKey } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { UserPicker } from "../../shared/ui/UserPicker";
import {
  addMember,
  changeOwner,
  deleteProject,
  getProject,
  listMembers,
  removeMember,
  updateProject,
  type ProjectDetail,
  type ProjectMember,
} from "./api";
import { ProjectFields } from "./ProjectsPage";

type TabId = "board" | "tasks" | "members";
const TABS: readonly TabId[] = ["board", "tasks", "members"];

const TAB_LABELS: Record<TabId, MessageKey> = {
  board: "projects.tab_board",
  tasks: "projects.tab_tasks",
  members: "projects.tab_members",
};

const MEMBERS_PAGE_SIZE = 100;

/** All members of the project: the pages are read one after another by `has_next`. */
async function listAllMembers(projectId: string): Promise<ProjectMember[]> {
  const all: ProjectMember[] = [];
  for (let page = 1; ; page += 1) {
    const chunk = await listMembers(projectId, { page, pageSize: MEMBERS_PAGE_SIZE });
    all.push(...chunk.items);
    if (!chunk.has_next) return all;
  }
}

const codeOf = (e: unknown): string => (e instanceof ApiError ? e.code : "unknown");

/** An id that is not a uuid is answered with 422: for the user it is "no such project". */
const loadCodeOf = (e: unknown): string => (e instanceof ApiError && e.status === 422 ? "not_found" : codeOf(e));

/** Roles that may own a project (FR-14a). */
const OWNER_ROLES: ReadonlyArray<ProjectMember["role"]> = ["business_admin", "mixed"];

function roleText(role: ProjectMember["role"]): string {
  return t(role === null ? "admin.role.none" : (`admin.role.${role}` as MessageKey));
}

export function ProjectPage({ currentUserId }: { currentUserId: string }) {
  const { projectId = "" } = useParams();
  const project = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
    retry: false,
  });
  if (project.data !== undefined) {
    return <ProjectCard key={project.data.id} project={project.data} currentUserId={currentUserId} />;
  }
  return (
    <section className="ui-wide">
      <h1>{t("projects.project_title")}</h1>
      {project.isError ? (
        <ErrorAlert message={errorMessage(loadCodeOf(project.error))} />
      ) : (
        <p role="status">{t("admin.loading")}</p>
      )}
    </section>
  );
}

type Confirmation = "delete" | "leave";

function ProjectCard({ project, currentUserId }: { project: ProjectDetail; currentUserId: string }) {
  const baseId = useId();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const alert = useAlertState();
  const busy = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});
  const [pending, setPending] = useState(false);
  const [tab, setTab] = useState<TabId>("board");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [search, setSearch] = useState("");

  // The card is a new screen: the focus goes to its heading (not left on <body>).
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const projectKey = ["projects", project.id] as const;
  const membersKey = ["projects", project.id, "members"] as const;
  const members = useQuery({
    queryKey: membersKey,
    queryFn: () => listAllMembers(project.id),
    retry: false,
  });
  const { permissions } = project;

  /** One action at a time; the error (if any) goes to the single alert region. */
  async function run(task: () => Promise<void>): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      await task();
    } catch (e) {
      alert.show(errorMessage(codeOf(e)));
    }
    setConfirmation(null);
    busy.current = false;
    setPending(false);
  }

  /** Re-reads the card (rights, is_member) and the members: the key is their common prefix. */
  const reload = () => queryClient.invalidateQueries({ queryKey: projectKey });
  const focusHeading = () => headingRef.current?.focus();

  /** Leaves the screen of a project the user no longer has (deleted / left). */
  function leaveScreen(): void {
    queryClient.removeQueries({ queryKey: projectKey });
    navigate("/projects");
  }

  function onSave(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const title = name.trim();
    if (title === "") {
      alert.show(errorMessage("validation_error"));
      return;
    }
    void run(async () => {
      const updated = await updateProject(project.id, { name: title, description });
      queryClient.setQueryData(projectKey, updated);
      setName(updated.name);
      setDescription(updated.description);
    });
  }

  function onTransfer(userId: string): void {
    void run(async () => {
      // Rights and fields come from the answer, not from the old card.
      const updated = await changeOwner(project.id, userId);
      queryClient.setQueryData(projectKey, updated);
      await queryClient.invalidateQueries({ queryKey: membersKey });
      focusHeading();
    });
  }

  function onRemove(userId: string): void {
    if (userId === currentUserId) {
      // Own row: same consequence as "leave", same confirmation (FR-15a).
      setConfirmation("leave");
      return;
    }
    void run(async () => {
      await removeMember(project.id, userId);
      await reload();
      focusHeading();
    });
  }

  function onConfirm(): void {
    if (confirmation === "delete") {
      void run(async () => {
        await deleteProject(project.id);
        leaveScreen();
      });
    } else if (confirmation === "leave") {
      void run(async () => {
        await removeMember(project.id, currentUserId);
        leaveScreen();
      });
    }
  }

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const last = TABS.length - 1;
    let next: number;
    if (event.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else return;
    event.preventDefault();
    const target = TABS[next];
    if (target === undefined) return;
    setTab(target);
    tabRefs.current[target]?.focus();
  }

  const all = members.data ?? [];
  const needle = search.trim().toLowerCase();
  const candidates = all.filter(
    (m) =>
      m.user.id !== project.owner.id &&
      !m.is_blocked &&
      OWNER_ROLES.includes(m.role) &&
      m.user.login.toLowerCase().includes(needle),
  );
  const membersError = members.isError ? errorMessage(codeOf(members.error)) : null;
  const tabId = (id: TabId) => `${baseId}-tab-${id}`;
  const panelId = `${baseId}-panel`;
  // A panel with nothing to focus is itself reachable by keyboard.
  const panelHasFocusable = tab === "members" && (permissions.manage_members || permissions.remove_self);

  return (
    <section className="ui-wide">
      <h1 ref={headingRef} tabIndex={-1}>{project.name}</h1>
      <ErrorAlert message={alert.message ?? membersError} seq={alert.seq} />
      <p>
        <strong>{t("projects.owner_label")}</strong>: <span data-field="project-owner">{project.owner.login}</span>
      </p>
      <p data-field="description" className="ui-pre">
        {project.description === "" ? t("projects.description_none") : project.description}
      </p>

      {permissions.manage ? (
        <section aria-labelledby={`${baseId}-edit`}>
          <h2 id={`${baseId}-edit`}>{t("projects.edit_title")}</h2>
          <form data-form="edit-project" onSubmit={onSave} noValidate>
            <ProjectFields name={name} description={description} onName={setName} onDescription={setDescription} />
            <button type="submit">{t("projects.save")}</button>
          </form>
          <p>
            <button type="button" data-action="delete-project" onClick={() => setConfirmation("delete")}>
              {t("projects.delete")}
            </button>
          </p>
        </section>
      ) : null}

      {permissions.manage ? (
        <section data-section="owner" aria-labelledby={`${baseId}-owner`}>
          <h2 id={`${baseId}-owner`}>{t("projects.owner_title")}</h2>
          <div className="ui-field">
            <label htmlFor={`${baseId}-owner-search`}>{t("projects.owner_search_label")}</label>
            <input
              id={`${baseId}-owner-search`}
              type="search"
              name="owner_search"
              autoComplete="off"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {members.isPending ? (
            <p role="status">{t("admin.loading")}</p>
          ) : candidates.length === 0 ? (
            <p>{t("projects.owner_none")}</p>
          ) : (
            <ul className="ui-list">
              {candidates.map((m) => (
                <li key={m.user.id} data-owner-candidate={m.user.id}>
                  <span>{m.user.login}</span>
                  <button
                    type="button"
                    data-action="transfer-owner"
                    aria-label={t("projects.owner_transfer_aria", { login: m.user.login })}
                    onClick={() => onTransfer(m.user.id)}
                  >
                    {t("projects.owner_transfer")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      <div role="tablist" aria-label={t("projects.tabs_label")} className="ui-tabs">
        {TABS.map((id, i) => (
          <button
            key={id}
            id={tabId(id)}
            ref={(el) => {
              tabRefs.current[id] = el;
            }}
            type="button"
            role="tab"
            data-tab={id}
            aria-selected={tab === id ? "true" : "false"}
            aria-controls={panelId}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(e) => onTabKey(e, i)}
          >
            {t(TAB_LABELS[id])}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={panelId} aria-labelledby={tabId(tab)} tabIndex={panelHasFocusable ? undefined : 0}>
        <h2>{t(TAB_LABELS[tab])}</h2>
        {tab === "members" ? (
          <>
            {permissions.manage_members ? (
              <UserPicker
                label={t("projects.member_add_label")}
                busy={pending}
                quietError
                onSelect={(user) =>
                  void run(async () => {
                    await addMember(project.id, user.id);
                    await reload();
                  })
                }
              />
            ) : null}
            {members.isPending ? (
              <p role="status">{t("admin.loading")}</p>
            ) : all.length === 0 ? (
              <p>{t("projects.members_empty")}</p>
            ) : (
              <table className="ui-table" aria-label={t("projects.members_list_label")}>
                <thead>
                  <tr>
                    <th scope="col">{t("projects.col_login")}</th>
                    <th scope="col">{t("projects.col_role")}</th>
                    <th scope="col">{t("projects.col_owner")}</th>
                    <th scope="col">{t("projects.col_blocked")}</th>
                    {permissions.manage_members ? <th scope="col">{t("projects.col_actions")}</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {all.map((m) => (
                    <tr key={m.user.id} data-user-id={m.user.id}>
                      <td data-field="login">{m.user.login}</td>
                      <td data-field="role">{roleText(m.role)}</td>
                      <td data-field="owner">{m.is_owner ? t("projects.member_owner") : null}</td>
                      <td data-field="blocked">{m.is_blocked ? t("projects.member_blocked") : null}</td>
                      {permissions.manage_members ? (
                        <td>
                          <button
                            type="button"
                            data-action="remove-member"
                            aria-label={t("projects.member_remove_aria", { login: m.user.login })}
                            onClick={() => onRemove(m.user.id)}
                          >
                            {t("projects.member_remove")}
                          </button>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {permissions.remove_self ? (
              <p>
                <button type="button" data-action="leave-project" onClick={() => setConfirmation("leave")}>
                  {t("projects.leave")}
                </button>
              </p>
            ) : null}
          </>
        ) : null}
      </div>

      {confirmation === null ? null : (
        <ConfirmDialog
          title={t(confirmation === "delete" ? "projects.delete_title" : "projects.leave_title")}
          message={t(confirmation === "delete" ? "projects.delete_message" : "projects.leave_message", {
            name: project.name,
          })}
          pending={pending}
          onConfirm={onConfirm}
          onCancel={() => setConfirmation(null)}
        />
      )}
    </section>
  );
}
