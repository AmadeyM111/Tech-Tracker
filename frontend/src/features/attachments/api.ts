// Attachment endpoints (011). Upload sends the raw file as the request body (plan PA-1):
// the body is passed as is, not serialized to JSON. Every call rejects with ApiError.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { ReadOptions } from "../tasks/api";

export type Attachment = components["schemas"]["AttachmentOut"];

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function listAttachments(taskId: string, options: ReadOptions = {}): Promise<Attachment[]> {
  const { data } = await getAppClient().GET("/api/v1/tasks/{task_id}/attachments", {
    params: { path: { task_id: taskId } },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data.items;
}

export async function uploadAttachment(taskId: string, file: File): Promise<Attachment> {
  const { data } = await getAppClient().POST("/api/v1/tasks/{task_id}/attachments", {
    params: { path: { task_id: taskId }, query: { name: file.name } },
    body: file as unknown as string,
    bodySerializer: (body: unknown) => body as BodyInit,
    headers: { "Content-Type": "application/octet-stream" },
  });
  if (data === undefined) throw invalidBody(201);
  return data;
}

export async function deleteAttachment(id: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/attachments/{attachment_id}", {
    params: { path: { attachment_id: id } },
  });
}

/** Same-origin link: the session cookie authorizes the download (FR-6). */
export function contentUrl(id: string): string {
  return `/api/v1/attachments/${id}/content`;
}
