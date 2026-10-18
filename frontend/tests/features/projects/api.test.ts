// T82: клиент API проектов (контракт - в шапке helpers.tsx).
import { describe, expect, it } from "vitest";

import {
  CREATABLE_PAGE_SIZE,
  addMember,
  changeOwner,
  createProject,
  deleteProject,
  getProject,
  listCreatableProjects,
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
  PERM_READ,
  PID,
  PID2,
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

// 004 / R5-T01: listCreatableProjects (FR-9). Фикстуры spec 004, раздел 5: P1 «Альфа», P2 «Бета», P3 «Гамма».
const P1 = PID;
const P2 = PID2;
const P3 = "99999999-0000-4999-8999-999999999993";
const NO_CREATE = { manage: false, manage_members: false, create_task: false, remove_self: false };
const card = (id: string, name: string, createTask: boolean) =>
  detail({ id, name, permissions: createTask ? PERM_READ : NO_CREATE });
const CARD = (id: string) => `GET /api/v1/projects/${id}`;

describe("listCreatableProjects (004 R5-T01)", () => {
  it("004_ac16_keeps_only_create_task_projects_in_list_order", async () => {
    const f = installFetch({
      [LIST]: () => j(200, page([listItem(P1, "Альфа"), listItem(P2, "Бета"), listItem(P3, "Гамма")])),
      [CARD(P1)]: () => j(200, card(P1, "Альфа", true)),
      [CARD(P2)]: () => j(200, card(P2, "Бета", false)),
      [CARD(P3)]: () => j(200, card(P3, "Гамма", true)),
    });
    const res = await listCreatableProjects();
    expect(res).toEqual([
      { id: P1, name: "Альфа" },
      { id: P3, name: "Гамма" },
    ]);
    expect(f.count(CARD(P2))).toBe(1);
    expect(f.last(LIST).headers.get("X-GT-Background")).toBeNull();
  });

  it("004_ac17_reads_all_pages_with_page_size_100_in_server_order", async () => {
    expect(CREATABLE_PAGE_SIZE).toBe(100);
    const f = installFetch({
      [LIST]: (r) =>
        new URL(r.url).searchParams.get("page") === "1"
          ? j(200, page([listItem(P3, "Гамма"), listItem(P2, "Бета")], 1, true, 100))
          : j(200, page([listItem(P1, "Альфа")], 2, false, 100)),
      [CARD(P1)]: () => j(200, card(P1, "Альфа", true)),
      [CARD(P2)]: () => j(200, card(P2, "Бета", true)),
      [CARD(P3)]: () => j(200, card(P3, "Гамма", true)),
    });
    const res = await listCreatableProjects();
    expect(res.map((x) => x.id)).toEqual([P3, P2, P1]);
    const lists = f.calls.filter((c) => `${c.method} ${new URL(c.url).pathname}` === LIST);
    expect(lists.map((c) => f.query(c).get("page"))).toEqual(["1", "2"]);
    expect(lists.map((c) => f.query(c).get("page_size"))).toEqual(["100", "100"]);
  });

  it("004_ac16_empty_list_returns_empty_without_card_requests", async () => {
    const f = installFetch({ [LIST]: () => j(200, page([])) });
    expect(await listCreatableProjects()).toEqual([]);
    expect(f.calls.length).toBe(1);
  });

  it("004_ac16_no_creatable_projects_returns_empty", async () => {
    installFetch({
      [LIST]: () => j(200, page([listItem(P2, "Бета")])),
      [CARD(P2)]: () => j(200, card(P2, "Бета", false)),
    });
    expect(await listCreatableProjects()).toEqual([]);
  });

  it.each([
    [500, "internal_error"],
    [503, "service_unavailable"],
  ])("004_ac18_list_status_%i_rejects_with_code", async (status, code) => {
    installFetch({ [LIST]: () => err(status, code) });
    await expect(listCreatableProjects()).rejects.toMatchObject({ status, code });
  });

  it.each([
    [500, "internal_error"],
    [503, "service_unavailable"],
  ])("004_ac18_one_card_status_%i_rejects_without_partial_result", async (status, code) => {
    installFetch({
      [LIST]: () => j(200, page([listItem(P1, "Альфа"), listItem(P3, "Гамма")])),
      [CARD(P1)]: () => j(200, card(P1, "Альфа", true)),
      [CARD(P3)]: () => err(status, code),
    });
    await expect(listCreatableProjects()).rejects.toMatchObject({ status, code });
  });

  it("004_ac18_network_failure_on_list_rejects_network_error", async () => {
    installFetch({
      [LIST]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await expect(listCreatableProjects()).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("004_ac18_network_failure_on_one_card_rejects_network_error", async () => {
    installFetch({
      [LIST]: () => j(200, page([listItem(P1, "Альфа"), listItem(P3, "Гамма")])),
      [CARD(P1)]: () => j(200, card(P1, "Альфа", true)),
      [CARD(P3)]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await expect(listCreatableProjects()).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});
