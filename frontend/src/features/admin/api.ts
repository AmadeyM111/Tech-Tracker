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
export type SetNameRequest = components["schemas"]["SetNameRequest"];
export type UnassignedAccount = components["schemas"]["UnassignedAccountOut"];

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
  actorLogin?: string;
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
  const payload: CreateUserRequest =
    body.email === undefined
      ? body
      : { ...body, email: body.email === null || body.email.trim() === "" ? null : body.email.trim() };
  const { data } = await getAppClient().POST("/api/v1/admin/users", { body: payload });
  if (data === undefined) throw invalidBody(201);
  return data;
}

/** An empty address removes the email (FR-2). */
export async function setUserEmail(id: string, email: string | null): Promise<AdminUser> {
  const value = email === null || email.trim() === "" ? null : email.trim();
  const { data } = await getAppClient().PUT("/api/v1/admin/users/{user_id}/email", {
    params: { path: { user_id: id } },
    body: { email: value },
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

/** Sets both names (AC-35); the server checks the length and rejects with first_name_invalid / last_name_invalid. */
export async function setUserName(id: string, body: SetNameRequest): Promise<AdminUser> {
  const { data } = await getAppClient().PUT("/api/v1/admin/users/{user_id}/name", {
    params: { path: { user_id: id } },
    body,
  });
  if (data === undefined) throw invalidBody(200);
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

/** Accounts without a role in the business admin's space (019/AC-30). The page carries no email. */
export async function listUnassigned(p: PageParams): Promise<Page<UnassignedAccount>> {
  const query: { page: number; page_size?: number } = { page: p.page };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  const { data } = await getAppClient().GET("/api/v1/unassigned-accounts", { params: { query } });
  if (data === undefined) throw invalidBody(200);
  return data;
}

/** The business admin may assign only the role "user" (019/FR-13a); the server refuses anything else with 403. */
export async function assignUserRole(id: string): Promise<void> {
  const body: components["schemas"]["SetRoleRequest"] = { role: "user" };
  await getAppClient().PUT("/api/v1/unassigned-accounts/{user_id}/role", {
    params: { path: { user_id: id } },
    body,
  });
}

export async function listAudit(p: AuditParams): Promise<Page<AuditEntry>> {
  const query: { page: number; page_size?: number; entity_type?: EntityType; actor_login?: string } = {
    page: p.page,
  };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  if (p.entityType !== undefined) query.entity_type = p.entityType;
  if (p.actorLogin !== undefined) query.actor_login = p.actorLogin;
  const { data } = await getAppClient().GET("/api/v1/admin/audit", { params: { query } });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export type BackupStatus = components["schemas"]["BackupStatusOut"];

/** Backup state for the tech admin banner (009/FR-6); metadata only. */
export async function getBackupStatus(): Promise<BackupStatus> {
  const { data } = await getAppClient().GET("/api/v1/admin/system/backup");
  if (data === undefined) throw invalidBody(200);
  return data;
}
