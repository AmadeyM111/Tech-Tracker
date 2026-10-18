// Projects and members endpoints (T82). Every call goes through the shared
// application client and rejects with ApiError; requests never carry the
// background header (FR-59).
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { Page, PageParams } from "../admin/api";

export type ProjectListItem = components["schemas"]["ProjectListItem"];
export type ProjectDetail = components["schemas"]["ProjectDetail"];
export type ProjectMember = components["schemas"]["ProjectMember"];
export interface ProjectCreate {
  name: string;
  description?: string;
}
export type ProjectPatch = components["schemas"]["ProjectPatch"];

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

function pageQuery(p: PageParams): { page: number; page_size?: number } {
  const query: { page: number; page_size?: number } = { page: p.page };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  return query;
}

export async function listProjects(p: PageParams): Promise<Page<ProjectListItem>> {
  const { data } = await getAppClient().GET("/api/v1/projects", { params: { query: pageQuery(p) } });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function createProject(body: ProjectCreate): Promise<ProjectDetail> {
  // An omitted description is the server default (empty).
  const payload = { name: body.name, description: body.description ?? "" };
  const { data } = await getAppClient().POST("/api/v1/projects", { body: payload });
  if (data === undefined) throw invalidBody(201);
  return data;
}

export async function getProject(id: string): Promise<ProjectDetail> {
  const { data } = await getAppClient().GET("/api/v1/projects/{project_id}", {
    params: { path: { project_id: id } },
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function updateProject(id: string, body: ProjectPatch): Promise<ProjectDetail> {
  const { data } = await getAppClient().PATCH("/api/v1/projects/{project_id}", {
    params: { path: { project_id: id } },
    body,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function deleteProject(id: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/projects/{project_id}", {
    params: { path: { project_id: id } },
  });
}

export async function changeOwner(id: string, userId: string): Promise<ProjectDetail> {
  const { data } = await getAppClient().PUT("/api/v1/projects/{project_id}/owner", {
    params: { path: { project_id: id } },
    body: { user_id: userId },
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function listMembers(id: string, p: PageParams): Promise<Page<ProjectMember>> {
  const { data } = await getAppClient().GET("/api/v1/projects/{project_id}/members", {
    params: { path: { project_id: id }, query: pageQuery(p) },
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function addMember(id: string, userId: string): Promise<void> {
  await getAppClient().POST("/api/v1/projects/{project_id}/members", {
    params: { path: { project_id: id } },
    body: { user_id: userId },
  });
}

export async function removeMember(id: string, userId: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/projects/{project_id}/members/{user_id}", {
    params: { path: { project_id: id, user_id: userId } },
  });
}

/** Проект, в котором текущий пользователь может создавать задачи (004/FR-9). */
export interface CreatableProject {
  id: string;
  name: string;
}

/** Размер страницы при полном чтении списка: предел сервера (core/pagination.py, MAX_PAGE_SIZE). */
export const CREATABLE_PAGE_SIZE = 100;

/**
 * 004/FR-9: все страницы GET /projects (пока has_next), затем GET /projects/{id} для каждого
 * проекта параллельно; остаются проекты с permissions.create_task в порядке списка сервера.
 * Любая ошибка — reject ApiError, без частичного результата.
 */
export async function listCreatableProjects(): Promise<CreatableProject[]> {
  const items: ProjectListItem[] = [];
  for (let page = 1; ; page += 1) {
    const res = await listProjects({ page, pageSize: CREATABLE_PAGE_SIZE });
    items.push(...res.items);
    if (!res.has_next) break;
  }
  const cards = await Promise.all(items.map((item) => getProject(item.id)));
  return cards
    .filter((card) => card.permissions.create_task === true)
    .map((card) => ({ id: card.id, name: card.name }));
}
