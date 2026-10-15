// Admin endpoints (T24). Every call goes through the shared application client
// and rejects with ApiError; requests never carry the background header (FR-59).
// Request bodies carry passwords: nothing here logs or stores them.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type AdminUser = components["schemas"]["AdminUser"];
export type AuditEntry = components["schemas"]["AuditEntry"];
export type Role = components["schemas"]["Role"];
export type EntityType = components["schemas"]["EntityType"];
export type CreateUserRequest = components["schemas"]["CreateUserRequest"];
export type ResetPasswordRequest = components["schemas"]["ResetPasswordRequest"];

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface PageParams {
  page: number;
  pageSize?: number;
}

export interface AuditParams extends PageParams {
  entityType?: EntityType;
  actorId?: string;
}

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function listUsers(p: PageParams): Promise<Page<AdminUser>> {
  const query: { page: number; page_size?: number } = { page: p.page };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  const { data } = await getAppClient().GET("/api/v1/admin/users", { params: { query } });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function createUser(body: CreateUserRequest): Promise<AdminUser> {
  const { data } = await getAppClient().POST("/api/v1/admin/users", { body });
  if (data === undefined) throw invalidBody(201);
  return data;
}

export async function blockUser(id: string): Promise<void> {
  await getAppClient().POST("/api/v1/admin/users/{user_id}/block", {
    params: { path: { user_id: id } },
  });
}

export async function unblockUser(id: string): Promise<void> {
  await getAppClient().POST("/api/v1/admin/users/{user_id}/unblock", {
    params: { path: { user_id: id } },
  });
}

export async function revokeSessions(id: string): Promise<void> {
  await getAppClient().POST("/api/v1/admin/users/{user_id}/revoke-sessions", {
    params: { path: { user_id: id } },
  });
}

export async function resetPassword(id: string, body: ResetPasswordRequest): Promise<void> {
  await getAppClient().POST("/api/v1/admin/users/{user_id}/reset-password", {
    params: { path: { user_id: id } },
    body,
  });
}

/** `null` removes the role (FR-12, FR-66). */
export async function setRole(id: string, role: Role | null): Promise<AdminUser> {
  const { data } = await getAppClient().PUT("/api/v1/admin/users/{user_id}/role", {
    params: { path: { user_id: id } },
    body: { role },
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function listAudit(p: AuditParams): Promise<Page<AuditEntry>> {
  const query: { page: number; page_size?: number; entity_type?: EntityType; actor_id?: string } = {
    page: p.page,
  };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  if (p.entityType !== undefined) query.entity_type = p.entityType;
  if (p.actorId !== undefined) query.actor_id = p.actorId;
  const { data } = await getAppClient().GET("/api/v1/admin/audit", { params: { query } });
  if (data === undefined) throw invalidBody(200);
  return data;
}
