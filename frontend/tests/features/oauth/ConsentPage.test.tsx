// 028 FR-5, FR-6 (AC-5, AC-12): the consent screen, the way back after the login, errors of the client.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { redirects } from "../../../src/features/oauth/ConsentPage";
import { errorMessage, ru } from "../../../src/shared/i18n";
import { err, installFetch, j, meWith, renderApp } from "../admin/helpers";

const ME = "GET /api/v1/me";
const CTX = "GET /api/v1/oauth/authorize/context";
const DECISION = "POST /api/v1/oauth/authorize/decision";
const LOGIN = "POST /api/v1/auth/login";
const QUERY =
  "/oauth/authorize?response_type=code&client_id=cid1&redirect_uri=https%3A%2F%2Fchatgpt.com%2Fcb&code_challenge=abc&code_challenge_method=S256&state=xyz";
const OK = {
  status: "ok",
  client_name: "ChatGPT",
  redirect_host: "chatgpt.com",
  redirect_uri: "https://chatgpt.com/cb",
  login: "sokolov.petr",
  request_token: "tok.sig",
};

afterEach(() => vi.restoreAllMocks());

function go(): ReturnType<typeof vi.fn> {
  const spy = vi.fn();
  vi.spyOn(redirects, "go").mockImplementation(spy);
  return spy;
}

describe("ConsentPage", () => {
  it("shows the client, the rights, who is signed in and where the user returns to", async () => {
    installFetch({ [ME]: () => j(200, meWith(["business_access"], "user")), [CTX]: () => j(200, OK) });
    renderApp(QUERY);
    expect(await screen.findByRole("heading", { level: 1, name: "ChatGPT просит доступ к вашему GTrack" })).toBeTruthy();
    expect(screen.getByText("ChatGPT сможет видеть и изменять ваши проекты и задачи от вашего имени.")).toBeTruthy();
    expect(screen.getByText(ru["oauth.item_read"])).toBeTruthy();
    expect(screen.getByText("Вы вошли как sokolov.petr.")).toBeTruthy();
    expect(screen.getByText("https://chatgpt.com/cb")).toBeTruthy();
    expect(document.activeElement?.tagName).toBe("H1");
  });

  it("sends the request parameters to the server as they came", async () => {
    const f = installFetch({ [ME]: () => j(200, meWith(["business_access"], "user")), [CTX]: () => j(200, OK) });
    renderApp(QUERY);
    await screen.findByRole("button", { name: ru["oauth.allow"] });
    const q = f.query(f.last(CTX));
    expect(q.get("client_id")).toBe("cid1");
    expect(q.get("redirect_uri")).toBe("https://chatgpt.com/cb");
    expect(q.get("code_challenge_method")).toBe("S256");
    expect(q.get("state")).toBe("xyz");
  });

  it("«Разрешить» posts the decision and sends the browser to the address from the answer", async () => {
    const spy = go();
    const bodies: unknown[] = [];
    installFetch({
      [ME]: () => j(200, meWith(["business_access"], "user")),
      [CTX]: () => j(200, OK),
      [DECISION]: async (r) => {
        bodies.push(await r.json());
        return j(200, { redirect_to: "https://chatgpt.com/cb?code=c1&state=xyz&iss=https%3A%2F%2Ft.example" });
      },
    });
    renderApp(QUERY);
    fireEvent.click(await screen.findByRole("button", { name: ru["oauth.allow"] }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("https://chatgpt.com/cb?code=c1&state=xyz&iss=https%3A%2F%2Ft.example"));
    expect(bodies).toEqual([{ request_token: "tok.sig", allow: true }]);
  });

  it("«Отклонить» posts allow=false", async () => {
    const spy = go();
    const bodies: unknown[] = [];
    installFetch({
      [ME]: () => j(200, meWith(["business_access"], "user")),
      [CTX]: () => j(200, OK),
      [DECISION]: async (r) => {
        bodies.push(await r.json());
        return j(200, { redirect_to: "https://chatgpt.com/cb?error=access_denied" });
      },
    });
    renderApp(QUERY);
    fireEvent.click(await screen.findByRole("button", { name: ru["oauth.deny"] }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(bodies).toEqual([{ request_token: "tok.sig", allow: false }]);
  });

  it("a protocol error is answered to the client with a redirect, the user sees nothing", async () => {
    const spy = go();
    installFetch({
      [ME]: () => j(200, meWith(["business_access"], "user")),
      [CTX]: () => j(200, { status: "redirect", redirect_to: "https://chatgpt.com/cb?error=invalid_request" }),
    });
    renderApp(QUERY);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("https://chatgpt.com/cb?error=invalid_request"));
  });

  it.each([
    ["oauth_client_unknown", "oauth.error_unknown"],
    ["oauth_request_invalid", "oauth.error_request"],
  ] as const)("%s is a page error with one button back to GTrack and no redirect", async (code, key) => {
    const spy = go();
    installFetch({ [ME]: () => j(200, meWith(["business_access"], "user")), [CTX]: () => err(422, code) });
    renderApp(QUERY);
    expect(await screen.findByRole("heading", { level: 1, name: ru["oauth.error_title"] })).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toBe(ru[key]);
    expect(screen.getByRole("link", { name: ru["oauth.back"] }).getAttribute("href")).toBe("/");
    expect(spy).not.toHaveBeenCalled();
  });

  it("a failed decision shows an error and keeps the buttons usable", async () => {
    go();
    installFetch({
      [ME]: () => j(200, meWith(["business_access"], "user")),
      [CTX]: () => j(200, OK),
      [DECISION]: () => err(422, "limit_reached"),
    });
    renderApp(QUERY);
    const allow = (await screen.findByRole("button", { name: ru["oauth.allow"] })) as HTMLButtonElement;
    fireEvent.click(allow);
    expect((await screen.findByRole("alert")).textContent).toBe(errorMessage("limit_reached"));
    await waitFor(() => expect(allow.disabled).toBe(false));
  });

  it("without a session the user goes to /login and, after the login, back to the same request", async () => {
    let signedIn = false;
    installFetch({
      [ME]: () => (signedIn ? j(200, meWith(["business_access"], "user")) : err(401, "not_authenticated")),
      [CTX]: () => (signedIn ? j(200, OK) : err(401, "not_authenticated")),
      [LOGIN]: () => {
        signedIn = true;
        return j(200, { user: { id: "u1", login: "sokolov.petr", role: "user", must_change_password: false } });
      },
    });
    renderApp(QUERY);
    expect(await screen.findByText(ru["oauth.login_context"])).toBeTruthy();
    fireEvent.change(screen.getByLabelText(ru["auth.login_label"]), { target: { value: "sokolov.petr" } });
    fireEvent.change(screen.getByLabelText(ru["auth.password_label"]), { target: { value: "Passw0rd-long-enough" } });
    fireEvent.click(screen.getByRole("button", { name: ru["auth.login_submit"] }));
    expect(await screen.findByRole("heading", { level: 1, name: "ChatGPT просит доступ к вашему GTrack" })).toBeTruthy();
  });

  it("the login page returns only to the consent path, never to an arbitrary address", async () => {
    installFetch({
      [ME]: () => err(401, "not_authenticated"),
      [LOGIN]: () => j(200, { user: { id: "u1", login: "a", role: "user", must_change_password: false } }),
    });
    renderApp("/login?next=https%3A%2F%2Fevil.example%2F");
    await screen.findByLabelText(ru["auth.login_label"]);
    expect(screen.queryByText(ru["oauth.login_context"])).toBeNull();
  });
});
