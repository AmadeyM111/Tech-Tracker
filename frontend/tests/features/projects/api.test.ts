// T82: клиент API проектов (контракт - в шапке helpers.tsx).
import { describe, expect, it } from "vitest";

import {
  addMember,
  changeOwner,
  createProject,
  deleteProject,
  getProject,
  listMembers,
  listProjects,
  removeMember,
  updateProject,
} from "../../../src/features/projects/api";
import {
  ADD,
  CREATE,
  DEL,
  LIST,
  MEMBERS,
  NO_CONTENT,
  ONE,
  OWNER,
  PATCH,
  PID,
  REMOVE,
  ID_PETROV,
  M_OWNER,
  detail,
  err,
  installFetch,
  j,
  listItem,
  page,
} from "./helpers";

const body = async (r: Request) => (await r.clone().json()) as unknown;

describe("projects api (T82)", () => {
  it("list_projects_sends_page_and_optional_page_size_without_background_header", async () => {
    const f = installFetch({ [LIST]: () => j(200, page([listItem(PID, "A")])) });
    const res = await listProjects({ page: 2, pageSize: 20 });
    expect(res.items[0]!.name).toBe("A");
    const q = f.query(f.last(LIST));
    expect(q.get("page")).toBe("2");
    expect(q.get("page_size")).toBe("20");
    expect(f.last(LIST).headers.get("X-GT-Background")).toBeNull();
    await listProjects({ page: 1 });
    expect(f.query(f.last(LIST)).has("page_size")).toBe(false);
  });

  it("create_get_update_delete_use_expected_methods_and_bodies", async () => {
    const f = installFetch({
      [CREATE]: () => j(201, detail()),
      [ONE]: () => j(200, detail()),
      [PATCH]: () => j(200, detail({ name: "B" })),
      [DEL]: NO_CONTENT,
    });
    expect((await createProject({ name: "A", description: "d" })).id).toBe(PID);
    expect(await body(f.last(CREATE))).toEqual({ name: "A", description: "d" });
    expect((await getProject(PID)).id).toBe(PID);
    expect((await updateProject(PID, { name: "B" })).name).toBe("B");
    expect(await body(f.last(PATCH))).toEqual({ name: "B" });
    await deleteProject(PID);
    expect(f.count(DEL)).toBe(1);
  });

  it("owner_and_members_calls", async () => {
    const f = installFetch({
      [OWNER]: () => j(200, detail()),
      [MEMBERS]: () => j(200, page([M_OWNER])),
      [ADD]: NO_CONTENT,
      [REMOVE(ID_PETROV)]: NO_CONTENT,
    });
    await changeOwner(PID, ID_PETROV);
    expect(await body(f.last(OWNER))).toEqual({ user_id: ID_PETROV });
    const res = await listMembers(PID, { page: 3, pageSize: 100 });
    expect(res.items.length).toBe(1);
    expect(f.query(f.last(MEMBERS)).get("page")).toBe("3");
    expect(f.query(f.last(MEMBERS)).get("page_size")).toBe("100");
    await addMember(PID, ID_PETROV);
    expect(await body(f.last(ADD))).toEqual({ user_id: ID_PETROV });
    await removeMember(PID, ID_PETROV);
    expect(f.count(REMOVE(ID_PETROV))).toBe(1);
  });

  it("errors_reject_with_api_error_and_code", async () => {
    installFetch({ [OWNER]: () => err(422, "recipient_wrong_role"), [ONE]: () => err(404, "not_found") });
    await expect(changeOwner(PID, ID_PETROV)).rejects.toMatchObject({ status: 422, code: "recipient_wrong_role" });
    await expect(getProject(PID)).rejects.toMatchObject({ status: 404, code: "not_found" });
  });
});
