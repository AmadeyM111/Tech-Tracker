// T100 / 003 R4-T03 (AC-20, AC-16): иконки слева у пунктов бокового меню и у «Выйти»; «На главную» нет.
//
// Контракт для исполнителя:
//  - у каждой ссылки/кнопки внутри `.ui-sidebar` первый дочерний ЭЛЕМЕНТ (и первый узел) -
//    inline <svg class="ui-icon" aria-hidden="true" focusable="false"> без <title>/текста;
//    это же верно для ссылок меню и «Выйти» на экранах ТА (AC-20); ссылки «На главную»
//    (`.ui-home-link`) нет нигде; иконки "home" в Icon.tsx тоже нет (R4-T07) (AC-16). Доступные имена не меняются.
//  - у разных пунктов меню разная разметка иконки (innerHTML).
//  - ui.css: `.ui-icon` с width и height (20px или 1.25em), flex-shrink: 0, отступ справа
//    (margin-right|margin-inline-end у .ui-icon либо gap у `.ui-sidebar a`/`.ui-sidebar button`);
//    цвет наследуется: `stroke: currentColor` или `fill: currentColor` в правиле .ui-icon,
//    либо такой же атрибут у svg. Ссылки/кнопки сайдбара - flex/inline-flex с align-items: center.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, installFetch, j, meWith, page, renderApp } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const ALL = ["business_access", "project_create", "task_assign_others", ...CAPS_ALL];
const ROUTES = {
  [ME]: () => j(200, meWith(ALL)),
  "GET /api/v1/projects": () => j(200, page([])),
};

const NAV = [ru["nav.projects"], ru["nav.my_tasks"], ru["admin.home_users_link"], ru["admin.home_audit_link"]];

function expectIcon(el: HTMLElement) {
  const first = el.firstElementChild;
  expect(first, `no child element in "${el.textContent}"`).not.toBeNull();
  expect(el.firstChild).toBe(first);
  expect(first!.tagName.toLowerCase()).toBe("svg");
  expect(first!.getAttribute("aria-hidden")).toBe("true");
  expect(first!.getAttribute("focusable")).toBe("false");
  expect(first!.classList.contains("ui-icon")).toBe(true);
  expect(first!.querySelector("title")).toBeNull();
  expect((first!.textContent ?? "").trim()).toBe("");
  expect(first!.innerHTML).not.toBe("");
  return first as Element;
}

describe("T100 sidebar icons", () => {
  // Бывший `home: every sidebar link...` (003/AC-19): "/" больше не экран, проверка на /projects
  // с business_access и админскими возможностями (4 ссылки и «Выйти»).
  it("003_ac19 /projects: every sidebar link and the logout button start with an icon, names unchanged", async () => {
    installFetch(ROUTES);
    renderApp("/projects");
    // T102: «Сменить пароль» переехала из меню в приветственный блок (см. welcome.test.tsx).
    const names = NAV;
    const markup: string[] = [];
    for (const name of names) {
      const link = await screen.findByRole("link", { name });
      expect(link.closest(".ui-sidebar")).not.toBeNull();
      markup.push(expectIcon(link).innerHTML);
    }
    const logout = screen.getByRole("button", { name: ru["auth.logout"] });
    expect(logout.closest(".ui-sidebar")).not.toBeNull();
    markup.push(expectIcon(logout).innerHTML);
    expect(new Set(markup).size).toBe(markup.length);
  });

  it("/projects: sidebar links have distinct icons", async () => {
    installFetch(ROUTES);
    renderApp("/projects");
    const markup: string[] = [];
    for (const name of NAV) {
      const link = await screen.findByRole("link", { name });
      expect(link.closest(".ui-sidebar")).not.toBeNull();
      markup.push(expectIcon(link).innerHTML);
    }
    expect(new Set(markup).size).toBe(NAV.length);
  });

  it.each(["/admin/users", "/admin/audit"])("AC-20 %s: menu links and logout have distinct icons, no home link", async (path) => {
    installFetch({
      ...ROUTES,
      [ME]: () => j(200, meWith(CAPS_ALL)),
      "GET /api/v1/admin/users": () => j(200, page([])),
      "GET /api/v1/admin/audit": () => j(200, page([])),
    });
    renderApp(path);
    const markup: string[] = [];
    for (const name of [ru["admin.home_users_link"], ru["admin.home_audit_link"]]) {
      const link = await screen.findByRole("link", { name });
      expect(link.closest(".ui-sidebar")).not.toBeNull();
      markup.push(expectIcon(link).innerHTML);
    }
    const logout = screen.getByRole("button", { name: ru["auth.logout"] });
    expect(logout.closest(".ui-sidebar")).not.toBeNull();
    markup.push(expectIcon(logout).innerHTML);
    expect(new Set(markup).size).toBe(markup.length);
    expect(screen.queryByRole("link", { name: "На главную" })).toBeNull();
    expect(document.querySelector(".ui-home-link")).toBeNull();
  });
});

const css = readFileSync(resolve(__dirname, "../../src/shared/ui/ui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function decls(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    const sels = (m[1] ?? "").split(",").map((s) => s.trim().replace(/\s+/g, " "));
    if (!sels.includes(selector)) continue;
    for (const part of (m[2] ?? "").split(";")) {
      const i = part.indexOf(":");
      if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
    }
  }
  return out;
}

describe("T100 .ui-icon styles", () => {
  const icon = decls(".ui-icon");
  it("size 20px", () => {
    expect(["20px", "1.25em"]).toContain(icon["width"]);
    expect(icon["height"]).toBe(icon["width"]);
  });
  it("does not shrink", () => {
    expect(icon["flex-shrink"]).toBe("0");
  });
  it("inherits color", () => {
    expect(`${icon["stroke"]} ${icon["fill"]}`).toContain("currentColor");
  });
  it("has spacing from the label", () => {
    const own = icon["margin-right"] ?? icon["margin-inline-end"];
    const gap = decls(".ui-sidebar a")["gap"] ?? decls(".ui-sidebar button")["gap"];
    expect(own ?? gap).toBeTruthy();
  });
  it.each([".ui-sidebar a", ".ui-sidebar button"])("%s lays the icon out in a row", (sel) => {
    const d = decls(sel);
    expect(["flex", "inline-flex"]).toContain(d["display"]);
    expect(d["align-items"]).toBe("center");
  });
});

describe("003 R4-T07: dead home icon removed", () => {
  it("003_nfr2 Icon.tsx has no home icon in IconName/PATHS", () => {
    const src = readFileSync(resolve(__dirname, "../../src/shared/ui/Icon.tsx"), "utf8");
    expect(src).not.toMatch(/["']home["']/);
    expect(src).not.toMatch(/^\s*home\s*:/m);
  });
});
