// T23: экран входа. AC: UF-2, FR-55, FR-66, NFR-7, NFR-6, FR-57.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { LoginPage } from "../../../src/features/auth/LoginPage";
import * as api from "../../../src/features/auth/api";
import { ApiError } from "../../../src/shared/api/client";
import { errorMessage, ru, t } from "../../../src/shared/i18n";
import { deferred, field, plainButtons, pressKey, renderAt, revealButtons, submitButton } from "./helpers";

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
    // 006/AC-1: единственная кнопка type=button на экране входа - кнопка показа пароля.
    expect(plainButtons(container).map((b) => b.getAttribute("aria-label"))).toEqual([(ru as Record<string, string>)["auth.show_password"]]);
  });

  it("route_login_renders_login_page_via_app_routes", () => {
    const { container } = renderAt("/login", <AppRoutes />, "*");
    expect(field(container, "username")).toBeTruthy();
    expect(field(container, "current-password").type).toBe("password");
  });
});

// Spec 005-login-help. Dictionary keys fixed by this test: auth.help_title, auth.help_p1, auth.help_p2.
const HELP_KEYS = ["auth.help_title", "auth.help_p1", "auth.help_p2"] as const;
const HELP_TITLE = "О системе";
const HELP_P1 =
  "GOSTracker — трекер задач для команды. Проекты, задачи с подзадачами и комментариями, список и канбан-доска.";
const HELP_P2 =
  "Учётную запись и первый пароль выдаёт технический администратор. После первого входа пароль нужно сменить.";
const dict = ru as Record<string, string>;

function helpBlock(): HTMLElement {
  return helpBlocks()[0] ?? screen.getByRole("region", { name: HELP_TITLE });
}

// section[aria-labelledby] is role=region, aside is role=complementary.
function helpBlocks(): HTMLElement[] {
  return [
    ...screen.queryAllByRole("region", { name: HELP_TITLE }),
    ...screen.queryAllByRole("complementary", { name: HELP_TITLE }),
  ];
}

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("LoginPage help block (spec 005)", () => {
  it("ac2_dictionary_values_equal_fr2_strings", () => {
    expect(dict["auth.help_title"]).toBe(HELP_TITLE);
    expect(dict["auth.help_p1"]).toBe(HELP_P1);
    expect(dict["auth.help_p2"]).toBe(HELP_P2);
    for (const k of HELP_KEYS) expect(t(k as never)).toBe(dict[k]);
  });

  it("ac1_single_landmark_named_by_h2_after_form_and_single_h1", () => {
    const { container } = renderAt("/login", <LoginPage />);
    const block = helpBlock();
    expect(["SECTION", "ASIDE"]).toContain(block.tagName);
    expect(helpBlocks().length).toBe(1);
    const labelledby = block.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    const heading = container.ownerDocument.getElementById(labelledby!);
    expect(heading?.tagName).toBe("H2");
    expect(heading?.textContent).toBe(HELP_TITLE);
    expect(block.contains(heading)).toBe(true);

    const form = container.querySelector("form")!;
    expect(form.contains(block)).toBe(false);
    expect(block.contains(form)).toBe(false);
    expect(form.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const h1 = container.querySelectorAll("h1");
    expect(h1.length).toBe(1);
    expect(h1[0]!.textContent).toBe("Вход в систему");
  });

  it("ac2_block_has_exactly_one_h2_and_two_paragraphs_with_exact_text", () => {
    renderAt("/login", <LoginPage />);
    const block = helpBlock();
    expect(block.querySelectorAll("h2").length).toBe(1);
    const ps = Array.from(block.querySelectorAll("p"));
    expect(ps.map((p) => p.textContent)).toEqual([HELP_P1, HELP_P2]);
    expect(within(block).getByRole("heading", { level: 2 }).textContent).toBe(HELP_TITLE);
  });

  it("ac3_no_interactive_elements_and_text_is_exactly_the_three_strings", () => {
    renderAt("/login", <LoginPage />);
    const block = helpBlock();
    expect(block.querySelectorAll("a, button, input, select, textarea, [tabindex]").length).toBe(0);
    expect(block.textContent).toBe(HELP_TITLE + HELP_P1 + HELP_P2);
  });

  it("ac4_standalone_login_page_makes_no_network_requests", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderAt("/login", <LoginPage />);
      expect(helpBlock()).toBeTruthy();
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("ac4_route_login_with_401_me_only_requests_me_and_shows_block", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(401, { detail: "x", code: "not_authenticated" }));
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderAt("/login", <AppRoutes />, "*");
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      await new Promise((r) => setTimeout(r, 50));
      expect(helpBlock()).toBeTruthy();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0] as unknown as [string | URL | Request, RequestInit | undefined];
      const u = typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      expect(u).toMatch(/\/me(\?|$)/);
      expect((init?.method ?? "GET").toUpperCase()).toBe("GET");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("ac4_block_is_visible_while_me_response_is_pending", async () => {
    const d = deferred<Response>();
    const fetchMock = vi.fn(() => d.promise);
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderAt("/login", <AppRoutes />, "*");
      expect(helpBlock()).toBeTruthy();
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Вход в систему");
      d.resolve(jsonResponse(401, { detail: "x", code: "not_authenticated" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      expect(helpBlock()).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("ac5_focus_on_login_and_tab_order_is_login_password_submit", () => {
    const { container } = renderAt("/login", <LoginPage />);
    expect(document.activeElement).toBe(field(container, "username"));
    const focusable = Array.from(
      container.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !(el as HTMLButtonElement).disabled);
    // 006/AC-6: между «Пароль» и «Войти» появилась кнопка показа пароля.
    expect(focusable).toEqual([
      field(container, "username"),
      field(container, "current-password"),
      revealButtons(container)[0],
      submitButton(container),
    ]);
    expect(revealButtons(container)).toHaveLength(1);
    expect(focusable.some((el) => helpBlock().contains(el))).toBe(false);
  });
});

// 006-bugreport-ch1, R6-T02: «глазок» на экране входа (AC-1, AC-3, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10).
const SECRET = "Secret-Pass-123";
const SHOW = "Показать пароль";
const pwd = (c: HTMLElement) => field(c, "current-password");
const eye = (c: HTMLElement) => {
  const b = revealButtons(c)[0];
  if (!b) throw new Error("no reveal button");
  return b;
};

describe("LoginPage password reveal (006)", () => {
  beforeEach(() => {
    vi.mocked(api.login).mockReset();
  });

  it("ac1_dictionary_has_show_password_key", () => {
    expect((ru as Record<string, string>)["auth.show_password"]).toBe(SHOW);
  });

  it("ac1_exactly_one_reveal_button_next_to_password_and_two_buttons_total", () => {
    const { container } = renderAt("/login", <LoginPage />);
    const buttons = revealButtons(container);
    expect(buttons).toHaveLength(1);
    const b = buttons[0]!;
    expect(b.getAttribute("type")).toBe("button");
    expect(b.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: SHOW })).toBe(b);
    expect(pwd(container).type).toBe("password");
    expect(pwd(container).nextElementSibling).toBe(b);
    // у «Логин» кнопки нет
    expect(field(container, "username").parentElement?.querySelector("button")).toBeNull();
    // на экране ровно две кнопки: «Войти» и показ пароля
    const all = Array.from(container.querySelectorAll("button"));
    expect(all).toHaveLength(2);
    expect(all).toContain(submitButton(container));
    expect(all).toContain(b);
  });

  it("ac3_mouse_toggles_type_keeps_value_focus_and_name", () => {
    const { container } = renderAt("/login", <LoginPage />);
    fireEvent.change(pwd(container), { target: { value: SECRET } });
    const b = eye(container);
    b.focus();
    fireEvent.click(b);
    expect(pwd(container).type).toBe("text");
    expect(pwd(container).value).toBe(SECRET);
    expect(b.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(b);
    expect(screen.getByRole("button", { name: SHOW })).toBe(b);
    fireEvent.click(b);
    expect(pwd(container).type).toBe("password");
    expect(b.getAttribute("aria-pressed")).toBe("false");
    expect(pwd(container).value).toBe(SECRET);
  });

  it.each([["Enter" as const], [" " as const]])("ac3_key_%j_toggles", (key) => {
    const { container } = renderAt("/login", <LoginPage />);
    fireEvent.change(pwd(container), { target: { value: SECRET } });
    const b = eye(container);
    b.focus();
    pressKey(b, key);
    expect(pwd(container).type).toBe("text");
    expect(b.getAttribute("aria-pressed")).toBe("true");
    pressKey(b, key);
    expect(pwd(container).type).toBe("password");
    expect(b.getAttribute("aria-pressed")).toBe("false");
  });

  it("ac5_reveal_presses_do_not_submit_and_enter_in_field_sends_exactly_one_request", async () => {
    vi.mocked(api.login).mockResolvedValue(user() as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container, "ivanov", SECRET);
    const b = eye(container);
    fireEvent.click(b);
    pressKey(b, "Enter");
    pressKey(b, " ");
    expect(api.login).not.toHaveBeenCalled();
    expect(pwd(container).type).toBe("text"); // три нажатия: показан -> скрыт -> показан
    fireEvent.submit(pwd(container).form!); // Enter в поле пароля
    await waitFor(() => expect(api.login).toHaveBeenCalledTimes(1));
    expect(api.login).toHaveBeenCalledWith({ login: "ivanov", password: SECRET });
  });

  it("ac6_icon_is_first_child_aria_hidden_and_differs_between_states", () => {
    const { container } = renderAt("/login", <LoginPage />);
    const b = eye(container);
    const icon = () => b.firstElementChild!;
    expect(icon().tagName.toLowerCase()).toBe("svg");
    expect(icon().getAttribute("aria-hidden")).toBe("true");
    const hidden = icon().innerHTML;
    expect(hidden).not.toBe("");
    fireEvent.click(b);
    expect(icon().getAttribute("aria-hidden")).toBe("true");
    expect(icon().innerHTML).not.toBe("");
    expect(icon().innerHTML).not.toBe(hidden);
  });

  it("ac7_401_hides_password_keeps_values_and_shows_message", async () => {
    vi.mocked(api.login).mockRejectedValue(new ApiError(401, "invalid_credentials", "x"));
    const { container } = renderAt("/login", <LoginPage />);
    fill(container, "ivanov", SECRET);
    fireEvent.click(eye(container));
    expect(pwd(container).type).toBe("text");
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Неверный логин или пароль");
    expect(pwd(container).type).toBe("password");
    expect(eye(container).getAttribute("aria-pressed")).toBe("false");
    expect(pwd(container).value).toBe(SECRET);
    expect(field(container, "username").value).toBe("ivanov");
  });

  it("ac7_shown_password_is_hidden_even_when_client_validation_stops_submit", () => {
    const { container } = renderAt("/login", <LoginPage />);
    fireEvent.change(pwd(container), { target: { value: SECRET } }); // логин пуст
    fireEvent.click(eye(container));
    expect(pwd(container).type).toBe("text");
    fireEvent.click(submitButton(container));
    expect(api.login).not.toHaveBeenCalled();
    expect(pwd(container).type).toBe("password");
    expect(eye(container).getAttribute("aria-pressed")).toBe("false");
    expect(pwd(container).value).toBe(SECRET);
  });

  it("ac8_remount_shows_password_hidden", () => {
    const first = renderAt("/login", <LoginPage />);
    fireEvent.click(eye(first.container));
    expect(pwd(first.container).type).toBe("text");
    first.unmount();
    const second = renderAt("/login", <LoginPage />);
    expect(pwd(second.container).type).toBe("password");
    expect(eye(second.container).getAttribute("aria-pressed")).toBe("false");
  });

  it("ac9_reveal_is_disabled_with_field_while_request_is_pending_and_still_present", async () => {
    const d = deferred<ReturnType<typeof user>>();
    vi.mocked(api.login).mockReturnValue(d.promise as never);
    const { container } = renderAt("/login", <LoginPage />);
    fill(container);
    expect(eye(container).disabled).toBe(false);
    fireEvent.click(submitButton(container));
    expect(revealButtons(container)).toHaveLength(1);
    expect(eye(container).disabled).toBe(true);
    expect(pwd(container).disabled).toBe(true);
    d.resolve(user());
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
  });

  it("ac10_shown_password_keeps_attributes_label_and_makes_no_requests", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    try {
      const { container } = renderAt("/login", <LoginPage />);
      fireEvent.change(pwd(container), { target: { value: SECRET } });
      const b = eye(container);
      fireEvent.click(b);
      fireEvent.click(b);
      fireEvent.click(b);
      const p = pwd(container);
      expect(p.type).toBe("text");
      expect(p.getAttribute("autocomplete")).toBe("current-password");
      expect(p.getAttribute("spellcheck")).toBe("false");
      expect(p.getAttribute("autocapitalize")).toBe("off");
      expect(p.labels?.[0]?.textContent).toBe(ru["auth.password_label"]);
      expect(fetchMock).not.toHaveBeenCalled();
      expect(api.login).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
