// T23: смена пароля и экран «нет роли». AC: FR-55, FR-66, NFR-7, NFR-6, FR-57.
// Решение владельца 2026-10-16: добровольной смены пароля в интерфейсе нет, только принудительная (FR-55).
// T103: форма смены пароля - модальное окно (role=dialog), все прежние проверки перенесены на него.
// ChangePasswordPage сам не ходит в /me: редирект не-принудительного пользователя - дело роутера.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { ChangePasswordPage } from "../../../src/features/auth/ChangePasswordPage";
import { LoginPage } from "../../../src/features/auth/LoginPage";
import { NoRolePage } from "../../../src/features/auth/NoRolePage";
import * as api from "../../../src/features/auth/api";
import { ApiError } from "../../../src/shared/api/client";
import { PASSWORD_MIN_LENGTH, errorMessage, ru, t } from "../../../src/shared/i18n";
import { deferred, field, plainButtons, pressKey, renderAt, revealButtons, submitButton } from "./helpers";

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
    // 006/AC-2: три кнопки показа и выход (точное перечисление).
    expect(plainButtons(container).map((b) => b.getAttribute("aria-label") ?? b.textContent?.trim())).toEqual([
      (ru as Record<string, string>)["auth.show_current_password"],
      (ru as Record<string, string>)["auth.show_new_password"],
      (ru as Record<string, string>)["auth.show_confirm_password"],
      ru["auth.logout"],
    ]);
  });

  it("fr55_logout_button_calls_logout_and_goes_to_login", async () => {
    vi.mocked(api.logout).mockResolvedValue(undefined as never);
    renderAt("/change-password", <ChangePasswordPage />);
    fireEvent.click(screen.getByRole("button", { name: ru["auth.logout"] }));
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

// 006-bugreport-ch1, R6-T02: «глазки» в окне смены пароля (AC-2, AC-3, AC-4, AC-6, AC-7, AC-8, AC-9, AC-10).
const NAMES = [
  ["auth.show_current_password", "Показать текущий пароль"],
  ["auth.show_new_password", "Показать новый пароль"],
  ["auth.show_confirm_password", "Показать повтор нового пароля"],
] as const;
const inputs = (c: HTMLElement) => [field(c, "current-password"), field(c, "new-password", 0), field(c, "new-password", 1)];
const eyes = (c: HTMLElement) => revealButtons(c);

function open() {
  renderAt("/change-password", <ChangePasswordPage />);
  return screen.getByRole("dialog");
}

describe("ChangePasswordPage password reveal (006)", () => {
  it("ac2_dictionary_values", () => {
    for (const [k, v] of NAMES) expect((ru as Record<string, string>)[k]).toBe(v);
  });

  it("ac2_three_reveal_buttons_with_distinct_dictionary_names_all_hidden", () => {
    const dialog = open();
    const bs = eyes(dialog);
    expect(bs).toHaveLength(3);
    expect(bs.map((b) => b.getAttribute("aria-label"))).toEqual(NAMES.map(([, v]) => v));
    expect(new Set(bs.map((b) => b.getAttribute("aria-label"))).size).toBe(3);
    for (const b of bs) {
      expect(b.getAttribute("type")).toBe("button");
      expect(b.getAttribute("aria-pressed")).toBe("false");
    }
    inputs(dialog).forEach((el, i) => {
      expect(el.type).toBe("password");
      expect(el.nextElementSibling).toBe(bs[i]);
    });
  });

  it("ac4_only_the_new_password_field_is_shown", () => {
    const dialog = open();
    fill(dialog);
    fireEvent.click(screen.getByRole("button", { name: "Показать новый пароль" }));
    const [cur, nxt, conf] = inputs(dialog);
    expect([cur!.type, nxt!.type, conf!.type]).toEqual(["password", "text", "password"]);
    expect(eyes(dialog).map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
    expect(nxt!.value).toBe(NEW);
  });

  it.each([[0], [1], [2]])("ac3_field_%i_mouse_enter_space_toggle_keep_value_focus_and_name", (i) => {
    const dialog = open();
    fill(dialog);
    const b = eyes(dialog)[i]!;
    const el = inputs(dialog)[i]!;
    const value = el.value;
    const name = b.getAttribute("aria-label");
    b.focus();
    fireEvent.click(b);
    expect(el.type).toBe("text");
    expect(el.value).toBe(value);
    expect(b.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(b);
    expect(b.getAttribute("aria-label")).toBe(name);
    pressKey(b, "Enter");
    expect(el.type).toBe("password");
    pressKey(b, " ");
    expect(el.type).toBe("text");
    pressKey(b, " ");
    expect(el.type).toBe("password");
    expect(b.getAttribute("aria-pressed")).toBe("false");
  });

  it("ac3_reveal_presses_do_not_send_the_form", () => {
    const dialog = open();
    fill(dialog);
    for (const b of eyes(dialog)) {
      fireEvent.click(b);
      pressKey(b, "Enter");
      pressKey(b, " ");
    }
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it("ac6_tab_order_is_field_eye_pairs_then_submit_then_logout_and_icons_are_aria_hidden", () => {
    const dialog = open();
    const items = Array.from(dialog.querySelectorAll<HTMLElement>("input, button")).filter((e) => !(e as HTMLButtonElement).disabled);
    const [c, n, f] = inputs(dialog);
    const [b1, b2, b3] = eyes(dialog);
    expect(items).toEqual([c, b1, n, b2, f, b3, submitButton(dialog), screen.getByRole("button", { name: ru["auth.logout"] })]);
    for (const b of eyes(dialog)) {
      expect(b.firstElementChild?.tagName.toLowerCase()).toBe("svg");
      expect(b.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
    }
    const before = b2!.firstElementChild!.innerHTML;
    fireEvent.click(b2!);
    expect(b2!.firstElementChild!.innerHTML).not.toBe(before);
  });

  it("ac6_focus_trap_full_circle_and_shift_tab", () => {
    const dialog = open();
    const logoutBtn = screen.getByRole("button", { name: ru["auth.logout"] });
    const first = field(dialog, "current-password");
    logoutBtn.focus();
    fireEvent.keyDown(logoutBtn, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(logoutBtn);
  });

  it.each([["invalid_current_password"], ["password_too_common"]])(
    "ac7_422_%s_hides_all_fields_keeps_values_and_shows_message",
    async (code) => {
      vi.mocked(api.changePassword).mockRejectedValue(new ApiError(422, code, "x"));
      const dialog = open();
      fill(dialog);
      for (const b of eyes(dialog)) fireEvent.click(b);
      expect(inputs(dialog).map((e) => e.type)).toEqual(["text", "text", "text"]);
      fireEvent.click(submitButton(dialog));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain(errorMessage(code));
      expect(inputs(dialog).map((e) => e.type)).toEqual(["password", "password", "password"]);
      expect(eyes(dialog).map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "false", "false"]);
      expect(inputs(dialog).map((e) => e.value)).toEqual([OLD, NEW, NEW]);
    },
  );

  it("ac7_client_validation_failure_also_hides_all_fields", () => {
    const dialog = open();
    fill(dialog, OLD, NEW, NEW + "x");
    for (const b of eyes(dialog)) fireEvent.click(b);
    fireEvent.click(submitButton(dialog));
    expect(api.changePassword).not.toHaveBeenCalled();
    expect(inputs(dialog).map((e) => e.type)).toEqual(["password", "password", "password"]);
    expect(inputs(dialog).map((e) => e.value)).toEqual([OLD, NEW, NEW + "x"]);
  });

  it("ac8_fields_are_hidden_at_submit_and_after_success_login_screen_starts_hidden", async () => {
    const d = deferred<undefined>();
    vi.mocked(api.changePassword).mockReturnValue(d.promise as never);
    const first = renderAt("/change-password", <ChangePasswordPage />);
    const dialog = screen.getByRole("dialog");
    fill(dialog);
    for (const b of eyes(dialog)) fireEvent.click(b);
    fireEvent.click(submitButton(dialog));
    expect(inputs(dialog).map((e) => e.type)).toEqual(["password", "password", "password"]);
    d.resolve(undefined);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
    first.unmount();
    const second = renderAt("/login", <LoginPage />);
    expect(field(second.container, "current-password").type).toBe("password");
    expect(revealButtons(second.container)[0]!.getAttribute("aria-pressed")).toBe("false");
  });

  it("ac9_reveal_buttons_are_disabled_while_change_is_pending", async () => {
    const d = deferred<undefined>();
    vi.mocked(api.changePassword).mockReturnValue(d.promise as never);
    const dialog = open();
    fill(dialog);
    expect(eyes(dialog).every((b) => !b.disabled)).toBe(true);
    fireEvent.click(submitButton(dialog));
    expect(eyes(dialog)).toHaveLength(3);
    expect(eyes(dialog).every((b) => b.disabled)).toBe(true);
    expect(inputs(dialog).every((e) => e.disabled)).toBe(true);
    d.resolve(undefined);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
  });

  it("ac9_reveal_buttons_are_disabled_while_logout_is_pending", async () => {
    const d = deferred<undefined>();
    vi.mocked(api.logout).mockReturnValue(d.promise as never);
    const dialog = open();
    fireEvent.click(screen.getByRole("button", { name: ru["auth.logout"] }));
    expect(eyes(dialog)).toHaveLength(3);
    expect(eyes(dialog).every((b) => b.disabled)).toBe(true);
    d.resolve(undefined);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/login"));
  });

  it("ac10_shown_fields_keep_attributes_hint_and_make_no_requests", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    try {
      const dialog = open();
      fill(dialog);
      for (const b of eyes(dialog)) fireEvent.click(b);
      const [cur, nxt, conf] = inputs(dialog);
      expect([cur!.type, nxt!.type, conf!.type]).toEqual(["text", "text", "text"]);
      expect(cur!.getAttribute("autocomplete")).toBe("current-password");
      expect(nxt!.getAttribute("autocomplete")).toBe("new-password");
      expect(conf!.getAttribute("autocomplete")).toBe("new-password");
      for (const el of [cur!, nxt!, conf!]) {
        expect(el.getAttribute("spellcheck")).toBe("false");
        expect(el.getAttribute("autocapitalize")).toBe("off");
      }
      expect(dialog.textContent).toContain("Не менее 12 символов");
      expect(document.getElementById(nxt!.getAttribute("aria-describedby")!)?.textContent).toBe("Не менее 12 символов");
      expect(fetchMock).not.toHaveBeenCalled();
      expect(api.changePassword).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
