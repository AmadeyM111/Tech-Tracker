// Spec 029: provider buttons on /login, the error text of a refused external login, «Способы входа» in the profile.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { err, installFetch, j, renderApp } from "../admin/helpers";

const PROVIDERS = "GET /api/v1/auth/external/providers";
const METHODS = "GET /api/v1/me/login-methods";
const ID = "11111111-1111-4111-8111-111111111111";
const IDENTITY = "22222222-2222-4222-8222-222222222222";

const base = {
  "GET /api/v1/auth/password-reset/status": () => j(200, { enabled: false }),
  "GET /api/v1/me": () => err(401, "not_authenticated"),
};

afterEach(() => vi.unstubAllGlobals());

describe("login screen providers", () => {
  it("shows a link for each enabled provider; remember goes into the address", async () => {
    installFetch({
      ...base,
      [PROVIDERS]: () => j(200, [{ name: "yandex" }, { name: "google" }]),
    });
    renderApp("/login");
    const yandex = await screen.findByRole("link", {
      name: ru["auth.external_yandex"],
    });
    expect(yandex.getAttribute("href")).toBe(
      "/api/v1/auth/external/yandex/start",
    );
    expect(
      screen.queryByRole("link", { name: ru["auth.external_vk"] }),
    ).toBeNull();
    fireEvent.click(screen.getByLabelText(ru["auth.remember_me"]));
    await waitFor(() =>
      expect(
        screen
          .getByRole("link", { name: ru["auth.external_google"] })
          .getAttribute("href"),
      ).toBe("/api/v1/auth/external/google/start?remember=true"),
    );
  });

  it("shows the same buttons on /register while registration is on (Q-3)", async () => {
    installFetch({
      ...base,
      "GET /api/v1/auth/password-reset/status": () => j(200, { enabled: true }),
      [PROVIDERS]: () => j(200, [{ name: "yandex" }, { name: "google" }]),
    });
    renderApp("/register");
    expect(
      await screen.findByRole("link", { name: ru["auth.external_yandex"] }),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: ru["auth.external_google"] }),
    ).toBeTruthy();
  });

  it("shows no block when no provider is enabled", async () => {
    installFetch({ ...base, [PROVIDERS]: () => j(200, []) });
    renderApp("/login");
    await screen.findByText(ru["auth.login_submit"]);
    expect(screen.queryByText(ru["auth.external_with"])).toBeNull();
  });

  it("shows one neutral text for a refusal and ignores unknown codes", async () => {
    installFetch({ ...base, [PROVIDERS]: () => j(200, []) });
    const { unmount } = renderApp(
      "/login?external_error=login_failed&provider=yandex",
    );
    expect(
      await screen.findByText(
        ru["auth.external_error.login_failed"].replace(
          "{provider}",
          ru["profile.methods_provider.yandex"],
        ),
      ),
    ).toBeTruthy();
    unmount();
    installFetch({ ...base, [PROVIDERS]: () => j(200, []) });
    renderApp("/login?external_error=evil_text_9");
    await screen.findByText(ru["auth.login_submit"]);
    expect(document.body.textContent).not.toContain(
      "Не удалось войти через внешний аккаунт",
    );
  });
});

describe("profile: login methods", () => {
  const me = () => ({
    id: ID,
    login: "petrov",
    role: "user",
    must_change_password: false,
    capabilities: ["business_access"],
    first_name: "Анна",
    last_name: "Петрова",
  });

  it("lists linked providers and keeps the last method from being unlinked", async () => {
    installFetch({
      "GET /api/v1/me": () => j(200, me()),
      [METHODS]: () =>
        j(200, {
          has_password: false,
          linked: [
            {
              id: IDENTITY,
              provider: "yandex",
              linked_at: "2026-11-13T10:00:00Z",
              last_used_at: null,
              can_unlink: false,
            },
          ],
          available: ["google"],
        }),
    });
    renderApp("/profile");
    await screen.findByText(ru["profile.methods_title"]);
    const unlink = await screen.findByRole("button", {
      name: ru["profile.methods_unlink"],
    });
    expect((unlink as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(ru["profile.methods_last"])).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: ru["profile.methods_password_set_button"],
      }),
    ).toBeTruthy();
  });

  it("unlinks after the confirmation dialog", async () => {
    const del = vi.fn(() => new Response(null, { status: 204 }));
    const fetchApi = installFetch({
      "GET /api/v1/me": () => j(200, me()),
      [METHODS]: () =>
        j(200, {
          has_password: true,
          linked: [
            {
              id: IDENTITY,
              provider: "yandex",
              linked_at: "2026-11-13T10:00:00Z",
              last_used_at: null,
              can_unlink: true,
            },
          ],
          available: [],
        }),
      [`DELETE /api/v1/me/login-methods/${IDENTITY}`]: del,
    });
    renderApp("/profile");
    fireEvent.click(
      await screen.findByRole("button", { name: ru["profile.methods_unlink"] }),
    );
    expect(del).not.toHaveBeenCalled(); // nothing before the confirmation
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      dialog.querySelector("button:last-of-type") as HTMLButtonElement,
    );
    await waitFor(() =>
      expect(
        fetchApi.count(`DELETE /api/v1/me/login-methods/${IDENTITY}`),
      ).toBe(1),
    );
  });
});
