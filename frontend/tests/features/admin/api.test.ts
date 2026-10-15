// T24: features/admin/api.ts поверх общего клиента: пути, методы, query, тела, ApiError.
import { describe, expect, it, vi } from "vitest";

import {
  blockUser,
  createUser,
  listAudit,
  listUsers,
  resetPassword,
  revokeSessions,
  setRole,
  unblockUser,
} from "../../../src/features/admin/api";
import { ApiError } from "../../../src/shared/api/client";
import { ID_IVANOV, U_IVANOV, j, page } from "./helpers";

function stub(resp: () => Response) {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => (calls.push(r), resp())),
  );
  return calls;
}
const path = (r: Request) => new URL(r.url).pathname;
const q = (r: Request) => new URL(r.url).searchParams;
const none = () => new Response(null, { status: 204 });

describe("admin api (T24)", () => {
  it("list_users_gets_page_and_optional_page_size", async () => {
    const calls = stub(() => j(200, page([U_IVANOV], 2, true, 20)));
    const res = await listUsers({ page: 2 });
    expect(res.items[0]?.login).toBe("ivanov");
    expect(res.has_next).toBe(true);
    expect(path(calls[0]!)).toBe("/api/v1/admin/users");
    expect(calls[0]!.method).toBe("GET");
    expect(q(calls[0]!).get("page")).toBe("2");
    expect(q(calls[0]!).has("page_size")).toBe(false);
    await listUsers({ page: 1, pageSize: 20 });
    expect(q(calls[1]!).get("page_size")).toBe("20");
  });

  it("create_user_posts_exact_body_and_returns_user", async () => {
    const calls = stub(() => j(201, U_IVANOV));
    const res = await createUser({ login: "ivanov", one_time_password: "Qw3rty-uiop-9" });
    expect(res.id).toBe(ID_IVANOV);
    expect(path(calls[0]!)).toBe("/api/v1/admin/users");
    expect(calls[0]!.method).toBe("POST");
    expect(await calls[0]!.json()).toEqual({ login: "ivanov", one_time_password: "Qw3rty-uiop-9" });
    expect(calls[0]!.url).not.toContain("Qw3rty");
  });

  it("block_unblock_revoke_post_to_action_paths_without_body_fields", async () => {
    const calls = stub(none);
    await blockUser(ID_IVANOV);
    await unblockUser(ID_IVANOV);
    await revokeSessions(ID_IVANOV);
    const base = `/api/v1/admin/users/${ID_IVANOV}`;
    expect(calls.map(path)).toEqual([`${base}/block`, `${base}/unblock`, `${base}/revoke-sessions`]);
    for (const c of calls) expect(c.method).toBe("POST");
  });

  it("reset_password_posts_one_time_password", async () => {
    const calls = stub(none);
    await resetPassword(ID_IVANOV, { one_time_password: "Qw3rty-uiop-9" });
    expect(path(calls[0]!)).toBe(`/api/v1/admin/users/${ID_IVANOV}/reset-password`);
    expect(calls[0]!.method).toBe("POST");
    expect(await calls[0]!.json()).toEqual({ one_time_password: "Qw3rty-uiop-9" });
  });

  it("set_role_puts_role_and_null_removes", async () => {
    const calls = stub(() => j(200, { ...U_IVANOV, role: "user" }));
    const res = await setRole(ID_IVANOV, "user");
    expect(res.role).toBe("user");
    await setRole(ID_IVANOV, null);
    expect(path(calls[0]!)).toBe(`/api/v1/admin/users/${ID_IVANOV}/role`);
    expect(calls[0]!.method).toBe("PUT");
    expect(await calls[0]!.json()).toEqual({ role: "user" });
    expect(await calls[1]!.json()).toEqual({ role: null });
  });

  it("list_audit_sends_only_given_filters", async () => {
    const calls = stub(() => j(200, page([])));
    await listAudit({ page: 3 });
    expect(path(calls[0]!)).toBe("/api/v1/admin/audit");
    expect(q(calls[0]!).get("page")).toBe("3");
    expect(q(calls[0]!).has("entity_type")).toBe(false);
    expect(q(calls[0]!).has("actor_id")).toBe(false);
    await listAudit({ page: 1, entityType: "deal", actorId: ID_IVANOV });
    expect(q(calls[1]!).get("entity_type")).toBe("deal");
    expect(q(calls[1]!).get("actor_id")).toBe(ID_IVANOV);
  });

  it("errors_reject_with_api_error_code_and_status", async () => {
    stub(() => j(422, { detail: "x", code: "last_account_admin" }));
    await expect(setRole(ID_IVANOV, null)).rejects.toBeInstanceOf(ApiError);
    await expect(setRole(ID_IVANOV, null)).rejects.toMatchObject({
      code: "last_account_admin",
      status: 422,
    });
    await expect(blockUser(ID_IVANOV)).rejects.toMatchObject({ code: "last_account_admin" });
  });
});
