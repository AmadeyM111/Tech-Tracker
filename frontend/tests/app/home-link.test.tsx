// 003 / R4-T03 (переписан): ссылки «На главную» и ссылок на `/` нет на экранах ТА, бизнес-экранах
// и экранах отказа. AC-16 (+ AC-27, AC-28: экраны отказа). Фикстуры spec §5: BA, U, TA.
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, err, installFetch, j, meWith, page, renderApp, type Handler } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const TASK_ID = "44444444-4444-4444-8444-444444444444";
const PROJECT_ID = "33333333-3333-4333-8333-333333333333";
const PATHS = [
  "/projects",
  `/projects/${PROJECT_ID}`,
  `/tasks/${TASK_ID}`,
  "/my-tasks",
  "/admin/users",
  "/admin/audit",
];

const FIXTURES: Record<string, { caps: string[]; role: string }> = {
  BA: { caps: ["business_access", "project_create", "task_assign_others"], role: "business_admin" },
  U: { caps: ["business_access"], role: "user" },
  TA: { caps: CAPS_ALL, role: "tech_admin" },
};

const ROUTES: Record<string, Handler> = {
  "GET /api/v1/projects": () => j(200, page([])),
  "GET /api/v1/me/tasks": () => j(200, page([])),
  "GET /api/v1/admin/users": () => j(200, page([])),
  "GET /api/v1/admin/audit": () => j(200, page([])),
  [`GET /api/v1/tasks/${TASK_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}/members`]: () => err(404, "not_found"),
};

afterEach(cleanup);

describe("AC-16 no home link anywhere", () => {
  const cases = Object.keys(FIXTURES).flatMap((fx) => PATHS.map((path) => [fx, path] as const));

  it.each(cases)("ac16_%s_%s_has_no_home_link_no_href_root_no_home_text", async (fx, path) => {
    const { caps, role } = FIXTURES[fx]!;
    installFetch({ ...ROUTES, [ME]: () => j(200, meWith(caps, role)) });
    const { container } = renderApp(path);
    // боковое меню есть на каждом из этих экранов (в том числе на экранах отказа): ждём его
    await screen.findByRole("navigation", { name: ru["app.menu_label"] });
    expect(container.querySelector('a[href="/"]')).toBeNull();
    expect(screen.queryByRole("link", { name: ru["app.home_link"] })).toBeNull();
    expect(container.querySelector(".ui-home-link")).toBeNull();
    expect(document.body.textContent ?? "").not.toContain("Главная");
    expect(document.body.textContent ?? "").not.toContain(ru["app.home_link"]);
  });
});
