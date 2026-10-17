// T92: ссылка «На главную» на admin-экранах и на экране «нет прав» оформлена классом ui-home-link.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, installFetch, j, meWith, page, renderApp } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const NAME = ru["app.home_link"];

function expectHomeLink() {
  const links = screen.getAllByRole("link", { name: NAME });
  expect(links).toHaveLength(1);
  const [a] = links;
  expect(a?.getAttribute("href")).toBe("/");
  expect(a?.className.split(/\s+/)).toContain("ui-home-link");
}

describe("T92 home link", () => {
  it.each(["/admin/users", "/admin/audit"])("ac_%s_home_link_is_styled", async (path) => {
    installFetch({
      [ME]: () => j(200, meWith(CAPS_ALL)),
      "GET /api/v1/users": () => j(200, page([])),
      "GET /api/v1/audit": () => j(200, page([])),
    });
    renderApp(path);
    await screen.findByRole("link", { name: NAME });
    expectHomeLink();
  });

  it.each(["/admin/users", "/admin/audit"])("ac_%s_forbidden_home_link_is_styled", async (path) => {
    installFetch({ [ME]: () => j(200, meWith([], "user")) });
    renderApp(path);
    await screen.findByRole("alert");
    expectHomeLink();
  });
});
