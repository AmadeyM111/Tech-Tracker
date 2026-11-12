// 028 FR-11 (AC-9, AC-12): «Облачные клиенты» on the agent access page: list, «Отключить» with confirmation.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { err, installFetch, j, meWith, renderApp } from "../admin/helpers";

const GRANTS = "GET /api/v1/me/oauth-grants";
const G1 = "11111111-1111-4111-8111-111111111111";
const G2 = "22222222-2222-4222-8222-222222222222";
const DEL = (id: string) => `DELETE /api/v1/me/oauth-grants/${id}`;
const grant = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  client_name: "ChatGPT",
  redirect_host: "chatgpt.com",
  created_at: "2026-11-10T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
  ...over,
});

function setup(list: unknown[], extra: Record<string, () => Response> = {}) {
  return installFetch({
    "GET /api/v1/me": () => j(200, meWith(["business_access"], "user")),
    "GET /api/v1/me/tokens": () => j(200, []),
    [GRANTS]: () => j(200, list),
    ...extra,
  });
}

describe("CloudClients", () => {
  it("lists the clients with the domain, dates in Moscow time and the status; own tokens stay a separate block", async () => {
    setup([grant(G1, { last_used_at: "2026-11-12T21:30:00Z" }), grant(G2, { client_name: "Claude", redirect_host: "claude.ai", revoked_at: "2026-11-11T10:00:00Z" })]);
    const { container } = renderApp("/profile/agents");
    expect(await screen.findByRole("heading", { level: 2, name: ru["oauth.clients_title"] })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: ru["agent_tokens.own_title"] })).toBeTruthy();
    await waitFor(() => expect(container.querySelector(`tr[data-grant-id="${G1}"]`)).toBeTruthy());
    const row1 = container.querySelector<HTMLElement>(`tr[data-grant-id="${G1}"]`)!;
    expect(row1.textContent).toContain("ChatGPT");
    expect(row1.textContent).toContain("chatgpt.com");
    expect(row1.textContent).toContain("13.11.2026"); // 21:30Z = 00:30 МСК следующего дня
    const row2 = container.querySelector<HTMLElement>(`tr[data-grant-id="${G2}"]`)!;
    expect(within(row2).getByText(ru["oauth.status_revoked"])).toBeTruthy();
    expect(within(row2).queryByRole("button")).toBeNull();
    expect(screen.getByText("Активных токенов: 0 из 10")).toBeTruthy();
  });

  it("shows the empty state", async () => {
    setup([]);
    renderApp("/profile/agents");
    expect(await screen.findByText(ru["oauth.clients_empty"])).toBeTruthy();
  });

  it("«Отключить» asks first, then deletes the grant and re-reads the list", async () => {
    let revoked = false;
    const f = setup([], {
      [GRANTS]: () => j(200, [grant(G1, revoked ? { revoked_at: "2026-11-12T10:00:00Z" } : {})]),
      [DEL(G1)]: () => {
        revoked = true;
        return new Response(null, { status: 204 });
      },
    });
    renderApp("/profile/agents");
    const button = await screen.findByRole("button", { name: "Отключить клиент ChatGPT" });
    fireEvent.click(button);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("«ChatGPT» сразу потеряет доступ");
    expect(f.count(DEL(G1))).toBe(0);
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.cancel"] }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(DEL(G1))).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Отключить клиент ChatGPT" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: ru["oauth.disconnect"] }));
    await waitFor(() => expect(f.count(DEL(G1))).toBe(1));
    expect(await screen.findByText(ru["oauth.status_revoked"])).toBeTruthy();
  });

  it("a failed revoke is shown by its code", async () => {
    setup([grant(G1)], { [DEL(G1)]: () => err(404, "not_found") });
    renderApp("/profile/agents");
    fireEvent.click(await screen.findByRole("button", { name: "Отключить клиент ChatGPT" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: ru["oauth.disconnect"] }));
    expect((await screen.findByRole("alert")).textContent).toBe(errorMessage("not_found"));
  });
});
