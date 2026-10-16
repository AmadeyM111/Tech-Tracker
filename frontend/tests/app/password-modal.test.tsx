// T103: принудительная смена пароля - модальное окно поверх приложения.
//
// Контракт для исполнителя (router.tsx, ChangePasswordPage.tsx, ru.ts, ui.css при необходимости):
//  - маршрут /change-password: GET /me -> 403 password_change_required (реальный бэкенд) ИЛИ 200 с
//    must_change_password=true => показывается окно; 200 с must_change_password=false => <Navigate "/">;
//    401 -> /login. Окно рендерится внутри контейнера приложения (без портала в body), в оверлее
//    .ui-overlay: div[role="dialog"][aria-modal="true"] с aria-labelledby на заголовок
//    ru["app.welcome_title"] и текстом ru["app.welcome_hint"] (= «Для продолжения задайте новый пароль.»).
//  - внутри: форма смены пароля (поля input[autocomplete=current-password|new-password x2], submit
//    «Сменить пароль», ErrorAlert) и кнопка выхода type=button; кнопки «Отмена»/«Закрыть» нет.
//  - Escape и клик по оверлею окно не закрывают; фокус в первом поле; Tab/Shift+Tab циклично внутри
//    (обработчик keydown с preventDefault + ручной focus, как в ConfirmDialog).
//  - содержимое подложки (всё вне .ui-overlay) под inert или aria-hidden="true"; сам оверлей - нет.
//  - успех: окно закрыто, путь "/", профиль перечитан (повторный GET /me), главная отрисована.
//  - ссылок на /change-password нет.
//  - (ревью) .ui-overlay: overflow-y:auto и align-items:safe center (theme.test.ts); у окна aria-describedby на
//    элемент с ru["app.welcome_hint"]; после успеха фокус на h1 главной (tabindex=-1); переходы только
//    /change-password -> / (replace), /me перечитывается после POST /auth/password; 403 password_change_required
//    с /no-role ведёт на /change-password через replace (одна запись истории, /no-role не остаётся);
//    повторный 403 password_change_required на /change-password не вызывает navigate.
// Новые ключи ru.ts (описать в шапке словаря): app.welcome_hint меняется на
//  «Для продолжения задайте новый пароль.»; app.change_password_link и welcome-блок удаляются.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../src/app/router";
import { ru } from "../../src/shared/i18n";
import { ADMIN_ID, err, expectAt, installFetch, j, meWith, renderApp, where } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const PWD = "POST /api/v1/auth/password";
const FORCED = () => err(403, "password_change_required");
const FORCED_200 = () => j(200, { ...meWith([], "user"), must_change_password: true });
const OK204 = () => new Response(null, { status: 204 });
const OLD = "One-Time-Pass-123";
const NEW = "Brand-New-Passw0rd!";

afterEach(() => vi.unstubAllGlobals());

const input = (d: HTMLElement, ac: string, n = 0) =>
  d.querySelectorAll<HTMLInputElement>(`input[autocomplete="${ac}"]`)[n]!;

function focusables(d: HTMLElement): HTMLElement[] {
  return Array.from(
    d.querySelectorAll<HTMLElement>('input, button, select, textarea, a[href], [tabindex]:not([tabindex="-1"])'),
  ).filter((el) => !(el as HTMLButtonElement).disabled);
}

async function openDialog() {
  const f = installFetch({ [ME]: FORCED, [PWD]: OK204 });
  const r = renderApp("/change-password");
  const dialog = await screen.findByRole("dialog");
  return { f, dialog, ...r };
}

describe("T103 modal password change", () => {
  it.each([
    ["me_403", FORCED],
    ["me_200_flag_true", FORCED_200],
  ])("ac1_%s_shows_modal_dialog_in_overlay_with_welcome", async (_n, me) => {
    installFetch({ [ME]: me });
    const { container } = renderApp("/change-password");
    const dialog = await screen.findByRole("dialog", { name: ru["app.welcome_title"] });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.tagName).toBe("DIV");
    expect(dialog.parentElement?.classList.contains("ui-overlay")).toBe(true);
    expect(container.contains(dialog)).toBe(true);
    expect(ru["app.welcome_title"]).toBe("Добро пожаловать");
    expect(ru["app.welcome_hint"]).toBe("Для продолжения задайте новый пароль.");
    expect(within(dialog).getByText(ru["app.welcome_hint"])).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: ru["auth.change_password_submit"] })).toBeTruthy();
    for (const ac of ["current-password"]) expect(input(dialog, ac).type).toBe("password");
    expect(dialog.querySelectorAll('input[autocomplete="new-password"]').length).toBe(2);
    expect(where()).toBe("/change-password");
  });

  it("ac1_no_cancel_or_close_button_and_no_links", async () => {
    const { dialog } = await openDialog();
    const names = Array.from(dialog.querySelectorAll("button")).map((b) => b.textContent?.trim());
    expect(names).not.toContain(ru["admin.cancel"]);
    expect(names.join("|")).not.toMatch(/Отмена|Закрыть/);
    expect(dialog.querySelectorAll("a[href]").length).toBe(0);
    expect(dialog.querySelector("form")).not.toBeNull();
  });

  it("ac1_escape_and_overlay_click_do_not_close", async () => {
    const { dialog, container } = await openDialog();
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(dialog.parentElement!);
    fireEvent.click(dialog.parentElement!);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(container.contains(dialog)).toBe(true);
    expect(where()).toBe("/change-password");
  });

  it("ac1_first_field_is_focused", async () => {
    const { dialog } = await openDialog();
    await waitFor(() => expect(document.activeElement).toBe(input(dialog, "current-password")));
  });

  it("ac1_focus_trap_tab_and_shift_tab_cycle", async () => {
    const { dialog } = await openDialog();
    const items = focusables(dialog);
    expect(items.length).toBeGreaterThanOrEqual(4);
    const first = items[0]!;
    const last = items[items.length - 1]!;
    expect(first).toBe(input(dialog, "current-password"));
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("ac1_content_under_modal_is_inert_or_aria_hidden_but_dialog_is_not", async () => {
    const { dialog, container } = await openDialog();
    expect(dialog.closest('[inert], [aria-hidden="true"]')).toBeNull();
    const overlay = dialog.closest(".ui-overlay")!;
    expect(overlay.closest('[inert], [aria-hidden="true"]')).toBeNull();
    const under = Array.from(container.querySelectorAll<HTMLElement>("main, h1, nav, .ui-sidebar, a, button, input")).filter(
      (el) => !overlay.contains(el) && !el.contains(overlay),
    );
    for (const el of under) {
      expect(el.closest('[inert], [aria-hidden="true"]'), el.outerHTML.slice(0, 80)).not.toBeNull();
    }
    // Everything that is not inside the overlay is hidden from the accessibility tree.
    expect(screen.queryByRole("main")).toBeNull();
  });

  it("ac1_success_closes_dialog_goes_home_and_rereads_profile", async () => {
    let changed = false;
    const f = installFetch({
      [ME]: () => (changed ? j(200, meWith(["business_access"], "user")) : FORCED()),
      [PWD]: () => ((changed = true), OK204()),
    });
    renderApp("/change-password");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(input(dialog, "current-password"), { target: { value: OLD } });
    fireEvent.change(input(dialog, "new-password", 0), { target: { value: NEW } });
    fireEvent.change(input(dialog, "new-password", 1), { target: { value: NEW } });
    fireEvent.click(within(dialog).getByRole("button", { name: ru["auth.change_password_submit"] }));
    await expectAt("/");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByRole("heading", { level: 1, name: ru["app.home_title"] })).toBeTruthy();
    expect(await f.last(PWD).json()).toEqual({ current_password: OLD, new_password: NEW });
    expect(f.count(ME)).toBeGreaterThanOrEqual(2);
    expect(document.querySelector('a[href="/change-password"]')).toBeNull();
    expect(screen.queryByRole("main")?.closest('[inert], [aria-hidden="true"]') ?? null).toBeNull();
  });

  it("ac1_server_error_shows_single_alert_and_keeps_dialog", async () => {
    installFetch({ [ME]: FORCED, [PWD]: () => err(422, "invalid_current_password") });
    renderApp("/change-password");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(input(dialog, "current-password"), { target: { value: OLD } });
    fireEvent.change(input(dialog, "new-password", 0), { target: { value: NEW } });
    fireEvent.change(input(dialog, "new-password", 1), { target: { value: NEW } });
    fireEvent.click(within(dialog).getByRole("button", { name: ru["auth.change_password_submit"] }));
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(dialog.contains(alerts[0]!)).toBe(true);
    expect(alerts[0]!.textContent).toContain(ru["error.invalid_current_password"]);
    expect(screen.getByRole("dialog")).toBe(dialog);
  });

  it("ac2_overlay_visible_on_top_of_blank_home_substrate", async () => {
    installFetch({ [ME]: FORCED });
    const { container } = renderApp("/change-password");
    await screen.findByRole("dialog");
    expect(container.querySelector('section[data-section="welcome"]')).toBeNull();
    expect(container.querySelector('a[href="/change-password"]')).toBeNull();
    expect(container.querySelectorAll(".ui-overlay").length).toBe(1);
  });

  it("ac3_not_forced_user_is_redirected_home_without_dialog", async () => {
    installFetch({ [ME]: () => j(200, meWith(["business_access"], "user")) });
    renderApp("/change-password");
    await expectAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: ru["app.home_title"] })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".ui-overlay")).toBeNull();
  });

  it("ac4_unauthenticated_goes_to_login", async () => {
    installFetch({ [ME]: () => err(401, "not_authenticated") });
    renderApp("/change-password");
    await expectAt("/login");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("ac1_forced_user_on_home_is_sent_to_modal", async () => {
    installFetch({ [ME]: FORCED });
    renderApp("/");
    await expectAt("/change-password");
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(ADMIN_ID).toBeTruthy();
  });
});

interface Step {
  path: string;
  type: string;
}

function renderRecorded(path: string) {
  const steps: Step[] = [];
  function Rec() {
    const l = useLocation();
    const type = useNavigationType();
    steps.push({ path: l.pathname, type });
    return null;
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Rec />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // One entry per distinct location render (renders without a location change are collapsed).
  const distinct = () => steps.filter((s, i) => i === 0 || s.path !== steps[i - 1]!.path || s.type !== steps[i - 1]!.type);
  return { ...out, steps: distinct };
}

async function submitForm(dialog: HTMLElement) {
  fireEvent.change(input(dialog, "current-password"), { target: { value: OLD } });
  fireEvent.change(input(dialog, "new-password", 0), { target: { value: NEW } });
  fireEvent.change(input(dialog, "new-password", 1), { target: { value: NEW } });
  fireEvent.click(within(dialog).getByRole("button", { name: ru["auth.change_password_submit"] }));
}

describe("T103 review follow-ups", () => {
  it("rv2_dialog_is_described_by_the_hint_text", async () => {
    const { dialog } = await openDialog();
    const id = dialog.getAttribute("aria-describedby");
    expect(id, "aria-describedby").toBeTruthy();
    const el = document.getElementById(id!);
    expect(el).not.toBeNull();
    expect(dialog.contains(el)).toBe(true);
    expect(el!.textContent).toBe(ru["app.welcome_hint"]);
  });

  it("rv3_after_success_focus_is_on_home_heading_not_body", async () => {
    let changed = false;
    installFetch({
      [ME]: () => (changed ? j(200, meWith(["business_access"], "user")) : FORCED()),
      [PWD]: () => ((changed = true), OK204()),
    });
    renderApp("/change-password");
    await submitForm(await screen.findByRole("dialog"));
    const h1 = await screen.findByRole("heading", { level: 1, name: ru["app.home_title"] });
    await waitFor(() => expect(document.activeElement).toBe(h1));
    expect(h1.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).not.toBe(document.body);
  });

  it("rv4_success_path_sequence_and_me_reread_after_post", async () => {
    let changed = false;
    const f = installFetch({
      [ME]: () => (changed ? j(200, meWith(["business_access"], "user")) : FORCED()),
      [PWD]: () => ((changed = true), OK204()),
    });
    const { steps } = renderRecorded("/change-password");
    await submitForm(await screen.findByRole("dialog"));
    await screen.findByRole("heading", { level: 1, name: ru["app.home_title"] });
    await new Promise((r) => setTimeout(r, 50));
    expect(steps().map((s) => s.path)).toEqual(["/change-password", "/"]);
    expect(steps()[1]!.type).toBe("REPLACE");
    const keys = f.calls.map((c) => `${c.method} ${new URL(c.url).pathname}`);
    const post = keys.indexOf(PWD);
    expect(post).toBeGreaterThan(-1);
    expect(keys.slice(post + 1)).toContain(ME);
  });

  it("rv5_forced_403_on_no_role_goes_straight_to_dialog_via_replace", async () => {
    let forced = false;
    installFetch({
      [ME]: () => (forced ? FORCED() : err(403, "no_role")),
      "GET /api/v1/admin/users": () => err(403, "password_change_required"),
    });
    const { getAppClient } = await import("../../src/shared/api/client");
    const { steps } = renderRecorded("/no-role");
    await waitFor(() => expect(steps().length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 30));
    forced = true;
    await act(async () => {
      await getAppClient().GET("/api/v1/admin/users", {}).catch(() => undefined);
    });
    expect(await screen.findByRole("dialog")).toBeTruthy();
    await new Promise((r) => setTimeout(r, 50));
    const seq = steps();
    expect(seq.at(-1)).toEqual({ path: "/change-password", type: "REPLACE" });
    expect(seq.filter((s) => s.path === "/change-password")).toHaveLength(1);
    expect(seq.filter((s) => s.path === "/no-role").length).toBeLessThanOrEqual(1);
    expect(seq[0]!.path).toBe("/no-role");
    expect(seq.slice(1).every((s) => s.path === "/change-password")).toBe(true);
  });

  it("rv6_repeated_forced_403_on_change_password_does_not_navigate_again", async () => {
    installFetch({ [ME]: FORCED, "GET /api/v1/admin/users": () => err(403, "password_change_required") });
    const { getAppClient } = await import("../../src/shared/api/client");
    const { steps } = renderRecorded("/change-password");
    await screen.findByRole("dialog");
    const before = steps().length;
    for (let i = 0; i < 2; i++) {
      await act(async () => {
        await getAppClient().GET("/api/v1/admin/users", {}).catch(() => undefined);
      });
    }
    await new Promise((r) => setTimeout(r, 50));
    expect(steps()).toHaveLength(before);
    expect(steps().filter((s) => s.type === "REPLACE")).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
