import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert, FieldError, useAlertState } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { createProject, listProjects } from "./api";

export const PROJECT_NAME_MAX = 255;

export interface ProjectFieldsProps {
  name: string;
  description: string;
  onName: (value: string) => void;
  onDescription: (value: string) => void;
  /** Текст ошибки под полем «Название» (пустое название при создании). */
  nameError?: string | null;
}

/** Name and description inputs shared by the create and the edit forms. */
export function ProjectFields({
  name,
  description,
  onName,
  onDescription,
  nameError = null,
}: ProjectFieldsProps) {
  const id = useId();
  const nameErrorId = `${id}-name-error`;
  return (
    <>
      <div className="ui-field">
        <label htmlFor={`${id}-name`}>
          {t("projects.name_label")}
          <span className="ui-required" aria-hidden="true">
            {t("tasks.required_mark")}
          </span>
        </label>
        <input
          id={`${id}-name`}
          name="name"
          type="text"
          maxLength={PROJECT_NAME_MAX}
          autoComplete="off"
          aria-required={true}
          aria-invalid={nameError === null ? undefined : "true"}
          aria-describedby={nameError === null ? undefined : nameErrorId}
          value={name}
          onChange={(e) => onName(e.target.value)}
        />
        <FieldError id={nameErrorId} message={nameError} />
      </div>
      <div className="ui-field">
        <label htmlFor={`${id}-description`}>{t("projects.description_label")}</label>
        <textarea
          id={`${id}-description`}
          name="description"
          rows={4}
          value={description}
          onChange={(e) => onDescription(e.target.value)}
        />
      </div>
    </>
  );
}

const LIST_KEY = ["projects", "list"] as const;

export function ProjectsPage({ canCreate }: { canCreate: boolean }) {
  const navigate = useNavigate();
  const alert = useAlertState();
  const busy = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [page, setPage] = useState(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const headingBase = useId();

  // Entering the screen (also after leaving a project) puts the focus on the heading.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const projects = useQuery({
    queryKey: [...LIST_KEY, page],
    queryFn: () => listProjects({ page }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  async function onCreate(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    const title = name.trim();
    if (title === "") {
      setNameError(t("projects.error_name_required"));
      return;
    }
    busy.current = true;
    alert.clear();
    try {
      // The list is stale by default and reloads when the screen is shown again.
      const created = await createProject({ name: title, description });
      navigate(`/projects/${created.id}`);
    } catch (e) {
      alert.show(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
    busy.current = false;
  }

  const listError =
    projects.isError && alert.message === null
      ? errorMessage(projects.error instanceof ApiError ? projects.error.code : "unknown")
      : null;
  const data = projects.data;

  return (
    <section className="ui-wide">
      <h1 ref={headingRef} tabIndex={-1}>
        {t("projects.title")}
      </h1>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />

      {canCreate ? (
        <section aria-labelledby={`${headingBase}-create`}>
          <h2 id={`${headingBase}-create`}>{t("projects.create_heading")}</h2>
          <form data-form="create-project" onSubmit={(e) => void onCreate(e)} noValidate aria-label={t("projects.create_heading")}>
            <ProjectFields
              name={name}
              description={description}
              onName={(value) => {
                setName(value);
                setNameError(null);
              }}
              onDescription={setDescription}
              nameError={nameError}
            />
            <button type="submit">{t("projects.create_submit")}</button>
          </form>
        </section>
      ) : null}

      <h2 id={`${headingBase}-list`}>{t("projects.list_heading")}</h2>

      {data === undefined ? (
        projects.isPending ? (
          <p role="status">{t("admin.loading")}</p>
        ) : null
      ) : data.items.length === 0 ? (
        <p role="status">{t("projects.empty")}</p>
      ) : (
        <table className="ui-table" aria-label={t("projects.list_label")}>
          <thead>
            <tr>
              <th scope="col">{t("projects.col_name")}</th>
              <th scope="col">{t("projects.col_owner")}</th>
              <th scope="col">{t("projects.col_tasks")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((p) => (
              <tr key={p.id} data-project-id={p.id}>
                <td data-field="name">
                  <Link to={`/projects/${p.id}`}>{p.name}</Link>
                </td>
                <td data-field="owner">{p.owner.login}</td>
                <td data-field="task_count">{p.task_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Аудит #9: пустая первая страница - без пагинации; со страницы > 1 остаётся, чтобы вернуться назад. */}
      {page > 1 || ((data?.items.length ?? 0) > 0 && data?.has_next === true) ? (
        <Pagination
          page={page}
          hasNext={data?.has_next ?? false}
          busy={projects.isPlaceholderData}
          onPage={(next) => {
            alert.clear();
            setPage(next);
          }}
        />
      ) : null}
    </section>
  );
}
