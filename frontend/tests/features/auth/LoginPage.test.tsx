// T23: экран входа. AC: UF-2, FR-55, FR-66, NFR-7, NFR-6, FR-57.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { LoginPage } from "../../../src/features/auth/LoginPage";
import * as api from "../../../src/features/auth/api";
import { ApiError } from "../../../src/shared/api/client";
import { errorMessage } from "../../../src/shared/i18n";
import { deferred, field, plainButtons, renderAt, submitButton } from "./helpers";

vi.mock("../../../src/features/auth/api", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn(),
}));

const PASSWORD = "Correct-Horse-Battery-9";
const user = (over: Record<string, unknown> = {}) => ({
  user: { id: "11111111-1111-4111-8111-111111111111", login: "ivanov", role: "user", must_change_password: false, ...over },
});

function fill(c: HTMLElement, login = "ivanov", password = PASSWORD) {
  fireEvent.change(field(c, "username"), { target: { value: login } });
  fireEvent.change(field(c, "current-password"), { target: { value: password } });
}

beforeEach(() => {
  vi.mocked(api.login).mockReset();
});

describe("LoginPage (T23)", () => {
  it("uf2_success_navigates_home_and_sends_credentials", async () => {
    vi.mocked(api.login).mockResolvedValue(user() as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
    expect(api.login).toHaveBeenCalledTimes(1);
    expect(api.login).toHaveBeenCalledWith({ login: "ivanov", password: PASSWORD });
  });

  it("fr55_must_change_password_redirects_to_change_password", async () => {
    vi.mocked(api.login).mockResolvedValue(user({ must_change_password: true }) as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/change-password"));
  });

  it("fr66_no_role_redirects_to_no_role_screen", async () => {
    vi.mocked(api.login).mockResolvedValue(user({ role: null }) as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/no-role"));
  });

  it.each([
    [401, "invalid_credentials"],
    [429, "too_many_requests"],
    [403, "forbidden"],
    [0, "network_error"],
    [422, "validation_error"],
    [500, "internal_error"],
    [418, "some_future_code"],
  ])("error_%s_%s_is_shown_via_dictionary_without_raw_json", async (status, code) => {
    const detail = status === 422 ? [{ loc: ["body", "login"], msg: "Field required", type: "missing" }] : "raw server text";
    vi.mocked(api.login).mockRejectedValue(new ApiError(status, code, detail));
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(errorMessage(code));
    expect(alert.textContent).not.toMatch(/[{}[\]]|Field required|raw server text|ApiError/);
    expect(screen.queryByTestId("where")).toBeNull(); // остались на экране входа
  });

  it("nfr7_fields_have_labels_and_password_is_masked", () => {
    const { container } = renderAt("/login", <LoginPage />);
    const login = field(container, "username");
    const pwd = field(container, "current-password");
    expect(pwd.type).toBe("password");
    for (const el of [login, pwd]) {
      expect(el.labels?.length, "label").toBeGreaterThan(0);
      expect((el.labels?.[0]?.textContent ?? "").trim()).not.toBe("");
    }
    expect(submitButton(container).textContent?.trim()).not.toBe("");
  });

  it("nfr7_first_field_is_focused_on_mount", () => {
    const { container } = renderAt("/login", <LoginPage />);
    expect(document.activeElement).toBe(field(container, "username"));
  });

  it("nfr7_keyboard_submit_form_wraps_fields_and_submit_event_logs_in", async () => {
    vi.mocked(api.login).mockResolvedValue(user() as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    const form = field(container, "username").form;
    expect(form).not.toBeNull();
    expect(field(container, "current-password").form).toBe(form);
    expect(submitButton(container).form).toBe(form);
    fireEvent.submit(form!);
    await waitFor(() => expect(api.login).toHaveBeenCalledTimes(1));
  });

  it("nfr7_error_is_announced_and_focus_moves_to_it_or_invalid_field", async () => {
    vi.mocked(api.login).mockRejectedValue(new ApiError(401, "invalid_credentials", "x"));
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    await waitFor(() => {
      const a = document.activeElement as HTMLElement;
      expect(alert.contains(a) || a.getAttribute("aria-invalid") === "true" || a === alert).toBe(true);
    });
  });

  it("double_submit_is_blocked_while_request_is_pending", async () => {
    const d = deferred<ReturnType<typeof user>>();
    vi.mocked(api.login).mockReturnValue(d.promise as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    fireEvent.submit(field(container, "username").form!);
    fireEvent.click(submitButton(container));
    expect(api.login).toHaveBeenCalledTimes(1);
    expect(submitButton(container).disabled || submitButton(container).getAttribute("aria-disabled") === "true").toBe(true);
    d.resolve(user());
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
  });

  it("empty_fields_do_not_call_api", () => {
    const { container } = renderAt("/login", <LoginPage />);
    fireEvent.click(submitButton(container));
    expect(api.login).not.toHaveBeenCalled();
  });

  it("fr57_password_never_in_url_or_console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    vi.mocked(api.login).mockRejectedValue(new ApiError(401, "invalid_credentials", "x"));
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    fireEvent.click(submitButton(container));
    await screen.findByRole("alert");
    expect(window.location.href).not.toContain(PASSWORD);
    for (const s of spies) expect(JSON.stringify(s.mock.calls)).not.toContain(PASSWORD);
    expect(container.textContent).not.toContain(PASSWORD);
    expect(plainButtons(container).length).toBe(0);
  });

  it("route_login_renders_login_page_via_app_routes", () => {
    const { container } = renderAt("/login", <AppRoutes />, "*");
    expect(field(container, "username")).toBeTruthy();
    expect(field(container, "current-password").type).toBe("password");
  });
});
