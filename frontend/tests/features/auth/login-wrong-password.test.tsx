// Reproduction: wrong password on /login through the real AppRoutes and fetch.
// Expected: the error alert shows the dictionary text and the typed login stays in the field.
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderApp } from "../admin/helpers";
import { field, installStatusFetch, submitButton } from "./helpers";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("login with a wrong password (reproduction of the prod report)", () => {
  it("shows the invalid-credentials alert and keeps the typed login", async () => {
    installStatusFetch(false, (r) => {
      const path = new URL(r.url).pathname;
      if (path === "/api/v1/me") return json(401, { detail: "x", code: "not_authenticated" });
      if (path === "/api/v1/auth/login" && r.method === "POST") {
        return json(401, { detail: "Неверный логин или пароль", code: "invalid_credentials" });
      }
      return json(404, { detail: "x", code: "not_found" });
    });
    const { container } = renderApp("/login");
    await waitFor(() => expect(field(container, "username")).toBeTruthy());

    fireEvent.change(field(container, "username"), { target: { value: "admin" } });
    fireEvent.change(field(container, "current-password"), { target: { value: "wrong-password-1" } });
    await act(async () => {
      fireEvent.click(submitButton(container));
    });

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Неверный логин или пароль"));
    expect(field(container, "username").value).toBe("admin");
    expect(screen.getByTestId("where").textContent).toBe("/login");
  });
});
