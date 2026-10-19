// T23: смена пароля и экран «нет роли». AC: FR-55, FR-66, NFR-7, NFR-6, FR-57.
// Решение владельца 2026-10-16: добровольной смены пароля в интерфейсе нет, только принудительная (FR-55).
// T103: форма смены пароля - модальное окно (role=dialog), все прежние проверки перенесены на него.
// ChangePasswordPage сам не ходит в /me: редирект не-принудительного пользователя - дело роутера.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { ChangePasswordPage } from "../../../src/features/auth/ChangePasswordPage";
import { NoRolePage } from "../../../src/features/auth/NoRolePage";
import * as api from "../../../src/features/auth/api";
import { ApiError } from "../../../src/shared/api/client";
import { PASSWORD_MIN_LENGTH, errorMessage, t } from "../../../src/shared/i18n";
import { deferred, field, plainButtons, renderAt, submitButton } from "./helpers";

vi.mock("../../../src/features/auth/api", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn(),
}));

const OLD = "One-Time-Pass-123";
const NEW = "Brand-New-Passw0rd!";

function fill(c: HTMLElement, cur = OLD, next = NEW, confirm = NEW) {
  fireEvent.change(field(c, "current-password"), { target: { value: cur } });
  fireEvent.change(field(c, "new-password", 0), { target: { value: next } });
  fireEvent.change(field(c, "new-password", 1), { target: { value: confirm } });
}

beforeEach(() => {
  vi.mocked(api.changePassword).mockReset();
  vi.mocked(api.logout).mockReset();
});

describe("ChangePasswordPage (T23)", () => {
  it("fr56_success_sends_both_passwords_and_navigates_home", async () => {
    vi.mocked(api.changePassword).mockResolvedValue(undefined as never);
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fill(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
    expect(api.changePassword).toHaveBeenCalledTimes(1);
    expect(api.changePassword).toHaveBeenCalledWith({ current_password: OLD, new_password: NEW });
  });

  it("hint_min_length_comes_from_password_min_length", () => {
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    expect(PASSWORD_MIN_LENGTH).toBe(12);
    expect(container.textContent).toContain(t("auth.password_min_length_hint", { min: PASSWORD_MIN_LENGTH }));
    expect(container.textContent).toContain("Не менее 12 символов");
  });

  it("client_check_too_short_new_password_blocks_request", async () => {
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    const short = "a".repeat(PASSWORD_MIN_LENGTH - 1);
    fill(container, OLD, short, short);
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent?.trim()).not.toBe("");
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it("client_check_exact_min_length_is_accepted", async () => {
    vi.mocked(api.changePassword).mockResolvedValue(undefined as never);
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    const ok = "a1".repeat(PASSWORD_MIN_LENGTH / 2);
    fill(container, OLD, ok, ok);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(api.changePassword).toHaveBeenCalledTimes(1));
  });

  it("client_check_confirmation_mismatch_blocks_request", async () => {
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fill(container, OLD, NEW, NEW + "x");
    fireEvent.click(submitButton(container));
    expect((await screen.findByRole("alert")).textContent?.trim()).not.toBe("");
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it.each([
    [422, "invalid_current_password"],
    [422, "password_too_short"],
    [422, "password_too_common"],
    [422, "password_reused"],
    [422, "validation_error"],
    [429, "too_many_requests"],
    [0, "network_error"],
    [500, "internal_error"],
    [418, "some_future_code"],
  ])("error_%s_%s_is_shown_via_dictionary_without_raw_json", async (status, code) => {
    const detail = code === "validation_error" ? [{ loc: ["body", "new_password"], msg: "Too short", type: "x" }] : "raw server text";
    vi.mocked(api.changePassword).mockRejectedValue(new ApiError(status, code, detail));
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fill(container);
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(errorMessage(code));
    expect(alert.textContent).not.toMatch(/[{}[\]]|Too short|raw server text|ApiError/);
    expect(screen.queryByTestId("where")).toBeNull();
  });

  it("nfr7_labels_autocomplete_and_masking", () => {
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    const inputs = [field(container, "current-password"), field(container, "new-password", 0), field(container, "new-password", 1)];
    for (const el of inputs) {
      expect(el.type).toBe("password");
      expect((el.labels?.[0]?.textContent ?? "").trim()).not.toBe("");
    }
    expect(submitButton(container).textContent?.trim()).not.toBe("");
  });

  it("nfr7_first_field_focused_and_form_submit_works", async () => {
    vi.mocked(api.changePassword).mockResolvedValue(undefined as never);
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    expect(document.activeElement).toBe(field(container, "current-password"));
    fill(container);
    const form = field(container, "current-password").form;
    expect(form).not.toBeNull();
    expect(submitButton(container).form).toBe(form);
    fireEvent.submit(form!);
    await waitFor(() => expect(api.changePassword).toHaveBeenCalledTimes(1));
  });

  it("nfr7_validation_error_focus_moves_to_alert_or_invalid_field", async () => {
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fill(container, OLD, NEW, NEW + "x");
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    await waitFor(() => {
      const a = document.activeElement as HTMLElement;
      expect(alert.contains(a) || a === alert || a.getAttribute("aria-invalid") === "true").toBe(true);
    });
  });

  it("double_submit_is_blocked_while_pending", async () => {
    const d = deferred<undefined>();
    vi.mocked(api.changePassword).mockReturnValue(d.promise as never);
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fill(container);
    fireEvent.click(submitButton(container));
    fireEvent.submit(field(container, "current-password").form!);
    fireEvent.click(submitButton(container));
    expect(api.changePassword).toHaveBeenCalledTimes(1);
    const b = submitButton(container);
    expect(b.disabled || b.getAttribute("aria-disabled") === "true").toBe(true);
    d.resolve(undefined);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
  });

  it("fr55_only_change_password_and_logout_are_available_no_links", () => {
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    expect(container.querySelectorAll("a[href]").length).toBe(0);
    expect(plainButtons(container).length).toBe(1); // выход
  });

  it("fr55_logout_button_calls_logout_and_goes_to_login", async () => {
    vi.mocked(api.logout).mockResolvedValue(undefined as never);
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fireEvent.click(plainButtons(container)[0]!);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/login"));
    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it("fr57_passwords_never_in_url_console_or_dom_text", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    vi.mocked(api.changePassword).mockRejectedValue(new ApiError(422, "password_reused", "x"));
    renderAt("/change-password", <ChangePasswordPage />);
    const container = screen.getByRole("dialog");
    fill(container);
    fireEvent.click(submitButton(container));
    await screen.findByRole("alert");
    for (const p of [OLD, NEW]) {
      expect(window.location.href).not.toContain(p);
      expect(container.textContent).not.toContain(p);
      for (const s of spies) expect(JSON.stringify(s.mock.calls)).not.toContain(p);
    }
  });

  it("route_change_password_via_app_routes", async () => {
    // T103: the route renders the form as a modal dialog (forced change: /me answers 403).
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "x", code: "password_change_required" }), { status: 403, headers: { "Content-Type": "application/json" } })),
    );
    renderAt("/change-password", <AppRoutes />, "*");
    const dialog = await screen.findByRole("dialog");
    expect(field(dialog, "new-password", 1)).toBeTruthy();
    vi.unstubAllGlobals();
  });
});

describe("NoRolePage (T23, FR-66)", () => {
  it("shows_no_role_message_and_logout", async () => {
    vi.mocked(api.logout).mockResolvedValue(undefined as never);
    const { container } = renderAt("/no-role", <NoRolePage />);
    expect(container.textContent).toContain(errorMessage("no_role"));
    expect(container.querySelectorAll("a[href]").length).toBe(0);
    const buttons = Array.from(container.querySelectorAll("button"));
    expect(buttons.length).toBe(1);
    expect(buttons[0]!.textContent?.trim()).not.toBe("");
    fireEvent.click(buttons[0]!);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/login"));
    expect(api.logout).toHaveBeenCalledTimes(1);
  });

  it("route_no_role_via_app_routes", () => {
    const { container } = renderAt("/no-role", <AppRoutes />, "*");
    expect(container.textContent).toContain(errorMessage("no_role"));
  });
});

// Spec 005-login-help, AC-6 (FR-7): the help block exists only on /login.
describe("login help block is absent elsewhere (spec 005, AC-6)", () => {
  const P1_PART = "трекер задач для команды";
  const P2_PART = "выдаёт технический администратор";

  function expectNoHelp() {
    expect(screen.queryByRole("region", { name: "О системе" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "О системе" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "О системе" })).toBeNull();
    expect(document.body.textContent).not.toContain(P1_PART);
    expect(document.body.textContent).not.toContain(P2_PART);
    expect(document.body.textContent).not.toContain("GOSTracker — ");
  }

  it("ac6_change_password_page_has_no_help_block", () => {
    renderAt("/change-password", <ChangePasswordPage />);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expectNoHelp();
  });

  it("ac6_no_role_page_has_no_help_block", () => {
    const { container } = renderAt("/no-role", <NoRolePage />);
    expect(container.textContent).toContain(errorMessage("no_role"));
    expectNoHelp();
  });

  it("ac6_routes_change_password_and_no_role_have_no_help_block", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "x", code: "password_change_required" }), { status: 403, headers: { "Content-Type": "application/json" } })),
    );
    try {
      renderAt("/change-password", <AppRoutes />, "*");
      await screen.findByRole("dialog");
      expectNoHelp();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
