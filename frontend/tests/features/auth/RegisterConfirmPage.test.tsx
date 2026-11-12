// 019 / R8-T17: the /register/confirm screen (RG-15, RG-14). AC: AC-16 (success, login link, no session),
// AC-9 and AC-10 (token invalid), AC-28 (login taken: the server picks the next suffix), FR-8 (one button press sends the token). Texts come from
// the ru dictionary; requests are recorded by the fetch stub.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterConfirmPage } from "../../../src/features/auth/RegisterConfirmPage";
import { errorMessage, t } from "../../../src/shared/i18n";
import { renderApp, where } from "../admin/helpers";
import { renderAt, submitButton } from "./helpers";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const CONFIRM = "POST /api/v1/auth/registration/confirm";
// v0.5: the server answers 200 with the login it created (here the first candidate for Anna Petrova-Ivanova).
const GENERATED = "petrova-ivanova.anna";
const confirmed = (login: string = GENERATED) => json(200, { login });
const LOGIN = "POST /api/v1/auth/login";
const ME = "GET /api/v1/me";
const ME_BODY = {
  id: "11111111-1111-4111-8111-111111111111",
  login: "ivanov",
  role: "user",
  must_change_password: false,
  capabilities: ["business_access"],
};

type Reply = (r: Request) => Response | Promise<Response>;
const keyOf = (r: Request) => `${r.method} ${new URL(r.url).pathname}`;

/** fetch stub: replies keyed by "METHOD /path"; an unknown path gets 404 not_found. Returns the request log. */
function stubNet(routes: Record<string, Reply> = {}): Request[] {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => {
      calls.push(r.clone());
      const reply = routes[keyOf(r)];
      if (reply) return reply(r);
      if (keyOf(r) === ME) return json(401, { detail: "x", code: "unauthenticated" });
      return json(404, { detail: "x", code: "not_found" });
    }),
  );
  return calls;
}

const confirmCalls = (calls: Request[]) => calls.filter((c) => keyOf(c) === CONFIRM);

/** The address bar (jsdom) carries the fragment before the page mounts; the page reads it once. */
function open(hash = "#token=abc") {
  window.history.replaceState(null, "", "/register/confirm" + hash);
  return renderAt("/register/confirm", <RegisterConfirmPage />, "/register/confirm");
}

const clickConfirm = (container: HTMLElement) => fireEvent.click(submitButton(container));

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => vi.unstubAllGlobals());

describe("RegisterConfirmPage (019/R8-T17)", () => {
  it("019_ac16_fragment_is_removed_from_address_bar_and_form_is_shown", async () => {
    stubNet();
    const { container } = open();
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.register_confirm_title") })).toBeTruthy();
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname).toBe("/register/confirm");
    expect(submitButton(container).textContent).toBe(t("auth.register_confirm_submit"));
    expect(container.querySelector("input")).toBeNull();
  });

  it("019_ac16_nothing_is_sent_before_the_button_press", async () => {
    const calls = stubNet();
    open();
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(calls).toHaveLength(0);
  });

  it("019_ac16_button_sends_token_in_body_only", async () => {
    const calls = stubNet({ [CONFIRM]: () => confirmed() });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    await waitFor(() => expect(confirmCalls(calls)).toHaveLength(1));
    const [request] = confirmCalls(calls);
    if (!request) throw new Error("confirm request was not sent");
    expect(await request.json()).toEqual({ token: "abc" });
    expect(request.url).not.toContain("abc");
  });

  it("019_ac16_second_press_while_in_flight_sends_nothing", async () => {
    let release!: () => void;
    const gate = new Promise<void>((res) => (release = res));
    const calls = stubNet({
      [CONFIRM]: async () => {
        await gate;
        return confirmed();
      },
    });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    const btn = submitButton(container);
    fireEvent.click(btn);
    await waitFor(() => expect(confirmCalls(calls)).toHaveLength(1));
    fireEvent.click(btn);
    fireEvent.submit(container.querySelector("form")!);
    expect(confirmCalls(calls)).toHaveLength(1);
    release();
    await screen.findByText(t("auth.register_confirmed"));
  });

  it("019_v05_success_shows_login_copy_button_and_login_link_without_login_request", async () => {
    const calls = stubNet({ [CONFIRM]: () => confirmed() });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    const status = await screen.findByText(t("auth.register_confirmed"));
    expect(status.closest('[role="status"]')).not.toBeNull();
    expect(screen.getByText(t("auth.register_your_login"))).toBeTruthy();
    expect(screen.getByText("Запишите логин — он понадобится для входа.")).toBeTruthy();
    expect(screen.getByText(GENERATED).tagName).toBe("CODE");
    const copy = screen.getByRole("button", { name: t("auth.register_copy") });
    expect(copy.classList.contains("ui-btn-secondary")).toBe(true);
    expect(screen.getByRole("link", { name: t("auth.register_login_link") }).getAttribute("href")).toBe("/login");
    expect(calls.some((c) => keyOf(c) === LOGIN)).toBe(false);
    expect(container.querySelector("form")).toBeNull();
    expect(container.querySelector("input")).toBeNull();
  });

  it("019_v05_copy_button_writes_the_login_to_clipboard", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    stubNet({ [CONFIRM]: () => confirmed() });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    fireEvent.click(await screen.findByRole("button", { name: t("auth.register_copy") }));
    expect(writeText).toHaveBeenCalledWith(GENERATED);
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("019_v05_copy_failure_is_reported_and_login_stays_on_screen", async () => {
    const writeText = vi.fn(async () => {
      throw new Error("denied");
    });
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    stubNet({ [CONFIRM]: () => confirmed() });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    fireEvent.click(await screen.findByRole("button", { name: t("auth.register_copy") }));
    expect((await screen.findByRole("alert")).textContent).toContain(t("auth.register_copy_failed"));
    expect(screen.getByText(GENERATED)).toBeTruthy();
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("019_ac9_ac10_token_invalid_shows_dictionary_text_and_link_to_register", async () => {
    stubNet({ [CONFIRM]: () => json(400, { detail: "x", code: "registration_token_invalid" }) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    expect((await screen.findByRole("alert")).textContent).toContain(errorMessage("registration_token_invalid"));
    expect(screen.getByRole("link", { name: t("auth.register_again") }).getAttribute("href")).toBe("/register");
    expect(screen.queryByText(t("auth.register_confirmed"))).toBeNull();
  });

  it("019_ac28_taken_login_gets_next_suffix_and_the_page_shows_the_server_login", async () => {
    // Login taken between request and confirm: the server picks .2 and answers 200; no login_taken on this screen.
    stubNet({ [CONFIRM]: () => confirmed(`${GENERATED}.2`) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    expect(await screen.findByText(`${GENERATED}.2`)).toBeTruthy();
    expect(screen.queryByText(errorMessage("login_taken"))).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("019_rg_rate_limited_shows_dictionary_text_without_register_link", async () => {
    stubNet({ [CONFIRM]: () => json(429, { detail: "x", code: "rate_limited" }) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    expect((await screen.findByRole("alert")).textContent).toContain(errorMessage("rate_limited"));
    expect(screen.queryByRole("link", { name: t("auth.register_again") })).toBeNull();
    expect(submitButton(container)).toBeTruthy();
  });

  it("019_ac1_feature_disabled_shows_register_disabled_text", async () => {
    stubNet({ [CONFIRM]: () => json(404, { detail: "x", code: "feature_disabled" }) });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    clickConfirm(container);
    expect((await screen.findByRole("alert")).textContent).toContain(t("auth.register_disabled"));
  });

  it.each(["", "#token="])("019_ac16_without_token_%j_shows_link_invalid_and_no_request", async (hash) => {
    const calls = stubNet();
    const { container } = open(hash);
    expect(await screen.findByText(t("auth.register_link_invalid"))).toBeTruthy();
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector('button[type="submit"]')).toBeNull();
    expect(screen.getByRole("link", { name: t("auth.register_again") }).getAttribute("href")).toBe("/register");
    expect(calls).toHaveLength(0);
  });
});

describe("/register/confirm in AppRoutes (019/R8-T17, RG-14)", () => {
  it("019_rg14_signed_in_user_stays_on_confirm_page", async () => {
    stubNet({ [ME]: () => json(200, ME_BODY) });
    window.history.replaceState(null, "", "/register/confirm#token=abc");
    renderApp("/register/confirm");
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.register_confirm_title") })).toBeTruthy();
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(where()).toBe("/register/confirm");
  });
});
