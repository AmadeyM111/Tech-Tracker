// Spec 021: consent checkbox on /register, public texts, the «Подтвердите согласие» screen.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RegisterPage } from "../../../src/features/auth/RegisterPage";
import { ExternalLogin } from "../../../src/features/auth/ExternalLogin";
import { LegalPage } from "../../../src/features/legal/LegalPage";
import { PdnConsentPage } from "../../../src/features/legal/PdnConsentPage";
import { errorMessage, t } from "../../../src/shared/i18n";
import { field, renderAt, submitButton } from "../auth/helpers";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const keyOf = (r: Request) => `${r.method} ${new URL(r.url).pathname}`;
const VERSION = "2026-11-15";
const LEGAL_ON = { "GET /api/v1/legal": () => json(200, { enabled: true, version: VERSION }) };
const REQUEST = "POST /api/v1/auth/registration/request";
const STATUS = { "GET /api/v1/auth/password-reset/status": () => json(200, { enabled: true }) };

type Reply = (r: Request) => Response | Promise<Response>;
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

function fillForm(c: HTMLElement) {
  fireEvent.change(field(c, "email"), { target: { value: "a@example.ru" } });
  fireEvent.change(field(c, "given-name"), { target: { value: "Ivan" } });
  fireEvent.change(field(c, "family-name"), { target: { value: "Petrov" } });
  fireEvent.change(field(c, "new-password"), { target: { value: "Correct-Horse-Battery-9" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("RegisterPage consent (021)", () => {
  it("shows_the_box_with_two_links_when_the_feature_is_on", async () => {
    stubNet({ ...STATUS, ...LEGAL_ON });
    renderAt("/register", <RegisterPage />, "/register");
    const box = await screen.findByRole("checkbox");
    expect(box.getAttribute("name")).toBe("pdn_consent");
    expect(screen.getByRole("link", { name: t("legal.consent_link") }).getAttribute("href")).toBe("/consent");
    expect(screen.getByRole("link", { name: t("legal.privacy_link") }).getAttribute("href")).toBe("/privacy");
  });

  it("without_the_box_no_request_is_sent_and_the_error_is_shown_under_it", async () => {
    const calls = stubNet({ ...STATUS, ...LEGAL_ON, [REQUEST]: () => json(200, { detail: "x" }) });
    const { container } = renderAt("/register", <RegisterPage />, "/register");
    await screen.findByRole("checkbox");
    fillForm(container);
    fireEvent.click(submitButton(container));
    expect(await screen.findByText(t("legal.consent_required"))).toBeTruthy();
    expect(calls.filter((c) => keyOf(c) === REQUEST)).toHaveLength(0);
  });

  it("with_the_box_the_request_carries_pdn_consent_and_the_version", async () => {
    const calls = stubNet({ ...STATUS, ...LEGAL_ON, [REQUEST]: () => json(200, { detail: "x" }) });
    const { container } = renderAt("/register", <RegisterPage />, "/register");
    fireEvent.click(await screen.findByRole("checkbox"));
    fillForm(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(calls.filter((c) => keyOf(c) === REQUEST)).toHaveLength(1));
    const body = await calls.filter((c) => keyOf(c) === REQUEST)[0]!.json();
    expect(body).toMatchObject({ pdn_consent: true, pdn_consent_version: VERSION });
  });

  it("no_box_when_the_feature_is_off", async () => {
    stubNet({ ...STATUS, "GET /api/v1/legal": () => json(200, { enabled: false, version: VERSION }) });
    renderAt("/register", <RegisterPage />, "/register");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("LegalPage (021)", () => {
  it("renders_title_version_and_sections_from_the_api", async () => {
    stubNet({
      "GET /api/v1/legal/privacy": () =>
        json(200, {
          kind: "privacy",
          title: "Политика конфиденциальности",
          version: VERSION,
          effective_date: VERSION,
          sections: [{ heading: "1. Раздел", paragraphs: ["Абзац один"] }],
        }),
    });
    renderAt("/privacy", <LegalPage kind="privacy" />, "/privacy");
    expect(await screen.findByRole("heading", { level: 1, name: "Политика конфиденциальности" })).toBeTruthy();
    expect(screen.getByText(t("legal.version", { date: "15.11.2026" }))).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "1. Раздел" })).toBeTruthy();
    expect(screen.getByText("Абзац один")).toBeTruthy();
    expect(screen.getByRole("button", { name: t("legal.back") })).toBeTruthy();
  });
});

describe("LegalPage when the feature is off (021)", () => {
  it("feature_disabled_sends_to_login", async () => {
    stubNet({ "GET /api/v1/legal/privacy": () => json(404, { detail: "x", code: "feature_disabled" }) });
    const { container } = renderAt("/privacy", <LegalPage kind="privacy" />, "/privacy");
    await waitFor(() => expect(container.querySelector("article")).toBeNull());
  });

  it("a web address in the text is a link opening in a new tab", async () => {
    stubNet({
      "GET /api/v1/legal/consent": () =>
        json(200, {
          kind: "consent",
          title: "Согласие",
          version: VERSION,
          effective_date: VERSION,
          sections: [{ heading: null, paragraphs: ["Сведения — в ЕГРИП (сервис ФНС: https://egrul.nalog.ru/)."] }],
        }),
    });
    renderAt("/consent", <LegalPage kind="consent" />, "/consent");
    const link = await screen.findByRole("link", { name: "https://egrul.nalog.ru/" });
    expect(link.getAttribute("href")).toBe("https://egrul.nalog.ru/");
    expect(link.getAttribute("target")).toBe("_blank");
  });
});

describe("PdnConsentPage (021)", () => {
  it("accept_posts_the_current_version", async () => {
    const calls = stubNet({ ...LEGAL_ON, "POST /api/v1/me/pdn-consent": () => new Response(null, { status: 204 }) });
    renderAt("/pdn-consent", <PdnConsentPage />, "/pdn-consent");
    expect(await screen.findByRole("heading", { level: 1, name: t("legal.confirm_title") })).toBeTruthy();
    await waitFor(() => expect(calls.some((c) => keyOf(c) === "GET /api/v1/legal")).toBe(true));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: t("legal.confirm_submit") }));
    await waitFor(() => expect(calls.some((c) => keyOf(c) === "POST /api/v1/me/pdn-consent")).toBe(true));
    const post = calls.find((c) => keyOf(c) === "POST /api/v1/me/pdn-consent")!;
    expect(await post.json()).toEqual({ pdn_consent: true, pdn_consent_version: VERSION });
  });

  it("logout_button_is_a_44px_touch_target_class", async () => {
    stubNet(LEGAL_ON);
    renderAt("/pdn-consent", <PdnConsentPage />, "/pdn-consent");
    const out = await screen.findByRole("button", { name: t("auth.logout") });
    expect(out.classList.contains("pdn-consent-logout")).toBe(true);
  });

  it("without_the_box_nothing_is_sent", async () => {
    const calls = stubNet(LEGAL_ON);
    renderAt("/pdn-consent", <PdnConsentPage />, "/pdn-consent");
    fireEvent.click(await screen.findByRole("button", { name: t("legal.confirm_submit") }));
    expect(await screen.findByText(t("legal.consent_required"))).toBeTruthy();
    expect(calls.some((c) => keyOf(c) === "POST /api/v1/me/pdn-consent")).toBe(false);
  });

  it("stale_version_shows_the_server_error", async () => {
    stubNet({
      ...LEGAL_ON,
      "POST /api/v1/me/pdn-consent": () => json(422, { detail: "x", code: "pdn_consent_version_mismatch" }),
    });
    renderAt("/pdn-consent", <PdnConsentPage />, "/pdn-consent");
    await screen.findByRole("checkbox");
    await waitFor(() => expect(screen.getByRole("checkbox")).toBeTruthy());
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: t("legal.confirm_submit") }));
    expect(await screen.findByText(errorMessage("pdn_consent_version_mismatch"))).toBeTruthy();
  });
});

describe("ExternalLogin consent (021)", () => {
  const PROVIDERS = { "GET /api/v1/auth/external/providers": () => json(200, [{ name: "yandex" }]) };

  it("buttons_are_disabled_until_the_box_is_ticked_then_carry_the_version", async () => {
    stubNet({ ...PROVIDERS, ...LEGAL_ON });
    renderAt("/login", <ExternalLogin remember={false} />, "/login");
    const box = await screen.findByRole("checkbox");
    const button = screen.getByRole("link", { name: t("auth.external_yandex") });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.getAttribute("href")).toBeNull();
    expect(screen.getByText(t("legal.providers_need_consent"))).toBeTruthy();
    // the block is marked as locked around the buttons; the official button itself is not restyled
    const list = button.parentElement as HTMLElement;
    expect(list.className).toContain("ext-list-locked");
    expect(list.getAttribute("aria-describedby")).toBe("ext-need-consent");
    expect(button.getAttribute("style")).toBeNull();
    fireEvent.click(box);
    expect(screen.queryByText(t("legal.providers_need_consent"))).toBeNull();
    const ready = screen.getByRole("link", { name: t("auth.external_yandex") });
    expect((ready.parentElement as HTMLElement).className).not.toContain("ext-list-locked");
    expect(ready.getAttribute("href")).toBe(
      `/api/v1/auth/external/yandex/start?consent=true&consent_version=${VERSION}`,
    );
  });

  it("without_the_feature_there_is_no_box_and_the_address_is_plain", async () => {
    stubNet({ ...PROVIDERS, "GET /api/v1/legal": () => json(200, { enabled: false, version: VERSION }) });
    renderAt("/login", <ExternalLogin remember={false} />, "/login");
    const button = await screen.findByRole("link", { name: t("auth.external_yandex") });
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(button.getAttribute("href")).toBe("/api/v1/auth/external/yandex/start");
  });
});
