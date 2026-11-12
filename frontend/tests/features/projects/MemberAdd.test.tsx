// 027 этап 2b: «Добавить участника» у владельца-«Пользователя»: логин или email, ошибки под полем.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { ADMIN_ID, err, j, meWith, page, renderApp } from "../admin/helpers";
import { installFetch } from "../admin/helpers";

const PID = "44444444-4444-4444-8444-444444444444";
const OWNER = { id: ADMIN_ID, login: "owner.user" };
const ADD = `POST /api/v1/projects/${PID}/members`;

function setup(add: (r: Request) => Response | Promise<Response>) {
  const detail = {
    id: PID,
    name: "Личный",
    description: "",
    owner: OWNER,
    is_member: true,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    permissions: { manage: true, manage_members: true, create_task: true, remove_self: false },
  };
  const member = { user: OWNER, role: "user", is_blocked: false, is_owner: true };
  return installFetch({
    "GET /api/v1/me": () => j(200, meWith(["business_access", "project_create"], "user")),
    [`GET /api/v1/projects/${PID}`]: () => j(200, detail),
    [`GET /api/v1/projects/${PID}/members`]: () => j(200, page([member])),
    [`GET /api/v1/projects/${PID}/tasks`]: () => j(200, page([])),
    [`GET /api/v1/projects/${PID}/board`]: () => j(200, { project: { id: PID, name: "Личный" }, columns: [] }),
    [ADD]: add,
  });
}

async function openForm() {
  renderApp(`/projects/${PID}`);
  fireEvent.click(await screen.findByRole("tab", { name: ru["projects.tab_members"] }));
  return (await screen.findByLabelText(ru["projects.member_add_key_label"])) as HTMLInputElement;
}

describe("MemberAdd (027)", () => {
  it("is a text field with a hint instead of the directory picker for the User role", async () => {
    setup(() => new Response(null, { status: 204 }));
    const input = await openForm();
    expect(input.type).toBe("text");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText(ru["projects.member_add_key_hint"])).toBeTruthy();
  });

  it("sends a login, or an email when the text has @, and shows the status", async () => {
    const bodies: unknown[] = [];
    setup(async (r) => {
      bodies.push(await r.json());
      return new Response(null, { status: 204 });
    });
    const input = await openForm();
    const add = screen.getByRole("button", { name: ru["projects.member_add_submit"] });
    fireEvent.change(input, { target: { value: " anna.k " } });
    fireEvent.click(add);
    expect(await screen.findByRole("status")).toBeTruthy();
    fireEvent.change(input, { target: { value: "boris@example.test" } });
    fireEvent.click(add);
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies).toEqual([{ login: "anna.k" }, { email: "boris@example.test" }]);
    expect(screen.getByText(ru["projects.member_added"])).toBeTruthy();
  });

  it.each([
    ["recipient_not_found", 422],
    ["member_already_added", 422],
  ])("shows %s under the field with aria-invalid", async (code, status) => {
    setup(() => err(status, code));
    const input = await openForm();
    fireEvent.change(input, { target: { value: "someone" } });
    fireEvent.click(screen.getByRole("button", { name: ru["projects.member_add_submit"] }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe(alert.id);
    fireEvent.change(input, { target: { value: "other" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("rate limit says what happened and when to retry (minutes from Retry-After, else an hour)", async () => {
    let retry: string | null = "1500";
    setup(
      () =>
        new Response(JSON.stringify({ detail: "x", code: "rate_limited" }), {
          status: 429,
          headers: { "Content-Type": "application/json", ...(retry === null ? {} : { "Retry-After": retry }) },
        }),
    );
    const input = await openForm();
    fireEvent.change(input, { target: { value: "someone" } });
    fireEvent.click(screen.getByRole("button", { name: ru["projects.member_add_submit"] }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Вы добавили слишком много участников за последний час. Попробуйте через 25 мин.",
    );
    retry = null;
    fireEvent.change(input, { target: { value: "again" } });
    fireEvent.click(screen.getByRole("button", { name: ru["projects.member_add_submit"] }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        "Вы добавили слишком много участников за последний час. Попробуйте через час.",
      ),
    );
  });

  it("an empty value is not sent", async () => {
    let calls = 0;
    setup(() => {
      calls += 1;
      return new Response(null, { status: 204 });
    });
    await openForm();
    fireEvent.click(screen.getByRole("button", { name: ru["projects.member_add_submit"] }));
    await screen.findByRole("alert");
    expect(calls).toBe(0);
  });
});
