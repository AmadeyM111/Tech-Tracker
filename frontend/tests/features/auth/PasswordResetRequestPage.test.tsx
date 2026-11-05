// 007/R7-T17: экран запроса сброса пароля /password-reset. AC: AC-3, FR-5, FR-6, FR-17, AC-15, NFR-3.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { errorMessage, t } from "../../../src/shared/i18n";
import { renderAt } from "./helpers";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const ME = {
  id: "11111111-1111-4111-8111-111111111111",
  login: "ivanov",
  role: "user",
  must_change_password: false,
  capabilities: ["business_access"],
};

/** Сеть: /me по `signedIn`, запрос сброса — `onRequest`. Возвращает журнал запросов. */
function stubNet(signedIn: boolean, onRequest: (r: Request) => Response | Promise<Response> = () => new Response(null, { status: 204 })) {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => {
      calls.push(r.clone());
      const p = new URL(r.url).pathname;
      if (p === "/api/v1/me") return signedIn ? json(200, ME) : json(401, { detail: "x", code: "unauthenticated" });
      if (p === "/api/v1/auth/password-reset/request") return onRequest(r);
      return json(404, { detail: "x", code: "not_found" });
    }),
  );
  return calls;
}

const resetCalls = (calls: Request[]) => calls.filter((c) => new URL(c.url).pathname === "/api/v1/auth/password-reset/request");
const open = (path = "/password-reset") => renderAt(path, <AppRoutes />, "*");
const emailInput = (c: HTMLElement) => c.querySelector<HTMLInputElement>("input")!;

afterEach(() => vi.unstubAllGlobals());

describe("PasswordResetRequestPage (007/R7-T17)", () => {
  it("007_renders_title_single_email_field_and_submit_button", async () => {
    stubNet(false);
    const { container } = open();
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.reset_request_title") })).toBeTruthy();
    expect(container.querySelectorAll("input")).toHaveLength(1);
    expect(screen.getByLabelText(t("auth.reset_email_label"))).toBe(emailInput(container));
    expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')?.textContent).toBe(t("auth.reset_request_submit"));
    expect(screen.getByRole("link", { name: t("auth.reset_back_to_login") }).getAttribute("href")).toBe("/login");
  });

  it("007_email_field_is_focused_on_mount", async () => {
    stubNet(false);
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    expect(document.activeElement).toBe(emailInput(container));
  });

  it("007_submit_posts_email_and_shows_fr6_text", async () => {
    const calls = stubNet(false);
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(emailInput(container), { target: { value: "ivanov@example.com" } });
    fireEvent.click(container.querySelector<HTMLButtonElement>('button[type="submit"]')!);
    const status = await screen.findByText(t("auth.reset_request_sent"));
    expect(status.closest('[role="status"]')).not.toBeNull();
    const sent = resetCalls(calls);
    expect(sent).toHaveLength(1);
    const [request] = sent;
    if (!request) throw new Error("reset request was not sent");
    expect(request.method).toBe("POST");
    expect(await request.json()).toEqual({ email: "ivanov@example.com" });
  });

  it("007_form_is_hidden_after_success_and_only_fr6_status_remains", async () => {
    stubNet(false);
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(emailInput(container), { target: { value: "ivanov@example.com" } });
    fireEvent.click(container.querySelector<HTMLButtonElement>('button[type="submit"]')!);
    const status = await screen.findByText(t("auth.reset_request_sent"));
    expect(status.closest('[role="status"]')).not.toBeNull();
    expect(container.querySelector("input")).toBeNull();
    expect(screen.queryByLabelText(t("auth.reset_email_label"))).toBeNull();
    expect(screen.queryByRole("button", { name: t("auth.reset_request_submit") })).toBeNull();
  });

  it("007_submit_is_blocked_while_request_in_flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>((res) => (release = res));
    const calls = stubNet(false, async () => {
      await gate;
      return new Response(null, { status: 204 });
    });
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(emailInput(container), { target: { value: "a@example.com" } });
    const btn = container.querySelector<HTMLButtonElement>('button[type="submit"]')!;
    fireEvent.click(btn);
    await waitFor(() => expect(resetCalls(calls)).toHaveLength(1));
    fireEvent.click(btn);
    fireEvent.submit(container.querySelector("form")!);
    expect(resetCalls(calls)).toHaveLength(1);
    release();
    await screen.findByText(t("auth.reset_request_sent"));
  });

  it("007_feature_disabled_404_shows_error_not_fr6_text", async () => {
    stubNet(false, () => json(404, { detail: "x", code: "feature_disabled" }));
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(emailInput(container), { target: { value: "a@example.com" } });
    fireEvent.click(container.querySelector<HTMLButtonElement>('button[type="submit"]')!);
    expect(await screen.findByText(errorMessage("feature_disabled"))).toBeTruthy();
    expect(screen.queryByText(t("auth.reset_request_sent"))).toBeNull();
  });

  it("007_route_without_session_does_not_call_me_nor_redirect", async () => {
    const calls = stubNet(false);
    open();
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.reset_request_title") })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(t("auth.login_title"))).toBeNull();
    expect(calls.some((c) => new URL(c.url).pathname === "/api/v1/me")).toBe(false);
  });

  it("007_route_is_available_with_session_without_guest_redirect_and_sidebar", async () => {
    stubNet(true);
    const { container } = open();
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.reset_request_title") })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(t("auth.reset_request_title"));
    expect(screen.queryByText(t("auth.login_title"))).toBeNull();
    expect(container.querySelector("nav")).toBeNull();
    expect(container.querySelector(".ui-sidebar")).toBeNull();
  });

  it("007_screen_source_has_no_cyrillic_outside_dictionary", () => {
    const src = readFileSync("src/features/auth/PasswordResetRequestPage.tsx", "utf8");
    expect(src).not.toMatch(/[А-Яа-яЁё]/);
  });
});
