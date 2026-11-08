// 019 / R8-T16: the /register screen and its route in AppRoutes. AC: AC-1 (registration disabled), AC-2 (fields,
// button, request, errors), AC-3 (a signed-in user goes to the start screen). Texts come from the ru dictionary;
// requests are recorded by the fetch stub.
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RegisterPage } from "../../../src/features/auth/RegisterPage";
import { errorMessage, PASSWORD_MIN_LENGTH, t } from "../../../src/shared/i18n";
import { renderApp, where } from "../admin/helpers";
import { field, renderAt, revealButtons, submitButton } from "./helpers";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const STATUS = "GET /api/v1/auth/password-reset/status";
const REQUEST = "POST /api/v1/auth/registration/request";
const ME = "GET /api/v1/me";
const STATUS_ON = { [STATUS]: () => json(200, { enabled: true }) };
const PASSWORD = "Correct-Horse-Battery-9";
const ME_BODY = {
  id: "11111111-1111-4111-8111-111111111111",
  login: "ivanov",
  role: "user",
  must_change_password: false,
  capabilities: ["business_access"],
};

// Field values keyed by autocomplete; spaces around email, first name, last name and login must be trimmed in the request.
const VALUES: Record<string, string> = {
  email: " New@Example.RU ",
  "given-name": " Ivan ",
  "family-name": " Petrov ",
  username: " ivanov ",
  "new-password": PASSWORD,
};

type Reply = (r: Request) => Response | Promise<Response>;
const keyOf = (r: Request) => `${r.method} ${new URL(r.url).pathname}`;

/** fetch stub: replies keyed by "METHOD /path"; an unknown path gets 404 not_found. Returns the request log. */
function stubNet(routes: Record<string, Reply>): Request[] {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => {
      calls.push(r.clone());
      const reply = routes[keyOf(r)];
      return reply ? reply(r) : json(404, { detail: "x", code: "not_found" });
    }),
  );
  return calls;
}

const sent = (calls: Request[]) => calls.filter((c) => keyOf(c) === REQUEST);

function fill(c: HTMLElement, values: Record<string, string> = VALUES) {
  for (const [autocomplete, value] of Object.entries(values)) {
    fireEvent.change(field(c, autocomplete), { target: { value } });
  }
}

const open = () => renderAt("/register", <RegisterPage />, "/register");

afterEach(() => vi.unstubAllGlobals());

describe("RegisterPage (019/R8-T16)", () => {
  it("019_ac2_renders_five_fields_and_one_submit_button", async () => {
    stubNet(STATUS_ON);
    const { container } = open();
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.register_title") })).toBeTruthy();
    expect(container.querySelectorAll("input")).toHaveLength(5);
    const labels: [string, string][] = [
      ["email", t("auth.register_email_label")],
      ["given-name", t("auth.register_first_name_label")],
      ["family-name", t("auth.register_last_name_label")],
      ["username", t("auth.register_login_label")],
      ["new-password", t("auth.register_password_label")],
    ];
    for (const [autocomplete, label] of labels) {
      expect(screen.getByLabelText(label)).toBe(field(container, autocomplete));
    }
    // Besides the submit button there is only the reveal toggle of the password field (006/D-6).
    const buttons = Array.from(container.querySelectorAll("button"));
    expect(buttons).toHaveLength(2);
    expect(revealButtons(container)).toHaveLength(1);
    expect(submitButton(container).textContent).toBe(t("auth.register_submit"));
    expect(screen.getByText(t("auth.password_min_length_hint", { min: PASSWORD_MIN_LENGTH }))).toBeTruthy();
    expect(screen.getByRole("link", { name: t("auth.register_back_to_login") }).getAttribute("href")).toBe("/login");
  });

  it("019_ac2_email_field_is_focused_on_mount", async () => {
    stubNet(STATUS_ON);
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    expect(document.activeElement).toBe(field(container, "email"));
  });

  it.each(["email", "given-name", "family-name", "username", "new-password"])(
    "019_ac2_empty_%s_is_rejected_without_request",
    async (autocomplete) => {
      const calls = stubNet(STATUS_ON);
      const { container } = open();
      await screen.findByRole("heading", { level: 1 });
      fill(container, { ...VALUES, [autocomplete]: "" });
      fireEvent.click(submitButton(container));
      expect(await screen.findByText(errorMessage("validation_error"))).toBeTruthy();
      expect(sent(calls)).toHaveLength(0);
    },
  );

  it("019_ac2_request_body_matches_schema_and_is_trimmed", async () => {
    const calls = stubNet({ ...STATUS_ON, [REQUEST]: () => json(200, { detail: "x" }) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(sent(calls)).toHaveLength(1));
    const [request] = sent(calls);
    if (!request) throw new Error("registration request was not sent");
    expect(await request.json()).toEqual({
      email: "New@Example.RU",
      first_name: "Ivan",
      last_name: "Petrov",
      login: "ivanov",
      password: PASSWORD,
    });
    expect(request.url).not.toContain(PASSWORD);
  });

  it("019_ac2_success_shows_role_status_and_hides_form", async () => {
    const calls = stubNet({ ...STATUS_ON, [REQUEST]: () => json(200, { detail: "x" }) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    fireEvent.click(submitButton(container));
    const status = await screen.findByText(t("auth.register_sent"));
    expect(status.closest('[role="status"]')).not.toBeNull();
    expect(sent(calls)).toHaveLength(1);
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("form")).toBeNull();
    expect(container.querySelector('button[type="submit"]')).toBeNull();
  });

  it("019_ac2_submit_is_blocked_while_request_in_flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>((res) => (release = res));
    const calls = stubNet({
      ...STATUS_ON,
      [REQUEST]: async () => {
        await gate;
        return json(200, { detail: "x" });
      },
    });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    const btn = submitButton(container);
    fireEvent.click(btn);
    await waitFor(() => expect(sent(calls)).toHaveLength(1));
    fireEvent.click(btn);
    fireEvent.submit(container.querySelector("form")!);
    expect(sent(calls)).toHaveLength(1);
    release();
    await screen.findByText(t("auth.register_sent"));
  });

  it.each([
    ["login_taken", 422],
    ["email_invalid", 422],
    ["rate_limited", 429],
    ["feature_disabled", 404],
  ])("019_ac2_error_%s_shows_dictionary_text_and_keeps_form", async (code, status) => {
    stubNet({ ...STATUS_ON, [REQUEST]: () => json(status, { detail: "x", code }) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    fireEvent.click(submitButton(container));
    const expected = code === "feature_disabled" ? t("auth.register_disabled") : errorMessage(code);
    expect(await screen.findByText(expected)).toBeTruthy();
    expect(container.querySelector('input[autocomplete="email"]')).not.toBeNull();
    expect(screen.queryByText(t("auth.register_sent"))).toBeNull();
  });

  it("019_ac1_disabled_registration_shows_register_disabled_instead_of_form", async () => {
    const calls = stubNet({ [STATUS]: () => json(200, { enabled: false }) });
    const { container } = open();
    expect(await screen.findByText(t("auth.register_disabled"))).toBeTruthy();
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("form")).toBeNull();
    expect(sent(calls)).toHaveLength(0);
  });
});

describe("/register in AppRoutes (019/R8-T16)", () => {
  it("019_ac3_signed_in_user_is_sent_to_start_screen", async () => {
    stubNet({ ...STATUS_ON, [ME]: () => json(200, ME_BODY) });
    renderApp("/register");
    await waitFor(() => expect(where()).toBe("/projects"));
  });

  it("019_ac2_anonymous_user_stays_on_register_form", async () => {
    stubNet({ ...STATUS_ON, [ME]: () => json(401, { detail: "x", code: "not_authenticated" }) });
    const { qc } = renderApp("/register");
    // The session check has answered 401; the client's unauthenticated handler has run before the query turns into an error.
    await waitFor(() => expect(qc.getQueryState(["auth", "me"])?.status).toBe("error"));
    await act(async () => {});
    expect(where()).toBe("/register");
    expect(screen.getByRole("heading", { level: 1, name: t("auth.register_title") })).toBeTruthy();
  });
});
