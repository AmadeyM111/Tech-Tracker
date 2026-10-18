// 004 / R5-T04 (AC-42, FR-6): вид кнопки «Задача» и раскладка бокового меню.
// Статический разбор ui.css (как theme.test.ts) и рендер иконки `plus`.
// Разметку кнопки (один svg, нет вложенных интерактивных элементов) проверяет app/create-task-button.test.tsx (R5-T05).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Icon } from "../../src/shared/ui/Icon";

const raw = readFileSync(resolve(__dirname, "../../src/shared/ui/ui.css"), "utf8");
const css = raw.replace(/\/\*[\s\S]*?\*\//g, "");

interface Rule {
  selectors: string[];
  decls: Record<string, string>;
}

function parseRules(src: string): Rule[] {
  const rules: Rule[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    const decls: Record<string, string> = {};
    for (const part of (m[2] ?? "").split(";")) {
      const i = part.indexOf(":");
      if (i > 0) decls[part.slice(0, i).trim().toLowerCase()] = part.slice(i + 1).trim();
    }
    rules.push({
      // Вложенное @media склеивается с первым селектором блока: отрезаем префикс до последней "{".
      selectors: (m[1] ?? "").split(",").map((s) => s.replace(/^[\s\S]*\{/, "").trim().replace(/\s+/g, " ")),
      decls,
    });
  }
  return rules;
}

const rules = parseRules(css);

// Правила верхнего уровня: без блока @media.
const mediaStart = css.indexOf("@media");
const topRules = parseRules(mediaStart === -1 ? css : css.slice(0, mediaStart));
const mediaNarrow = (() => {
  const i = css.search(/@media\s*\(max-width:\s*719px\)/);
  if (i === -1) return "";
  const open = css.indexOf("{", i);
  let depth = 0;
  for (let k = open; k < css.length; k++) {
    if (css[k] === "{") depth++;
    else if (css[k] === "}" && --depth === 0) return css.slice(open + 1, k);
  }
  return "";
})();

const rootTokens: Record<string, string> = {};
for (const r of rules.filter((r) => r.selectors.includes(":root"))) {
  for (const [k, v] of Object.entries(r.decls)) if (k.startsWith("--")) rootTokens[k.slice(2)] = v;
}

function lum(hex: string): number {
  let h = hex.replace("#", "");
  if (h.length === 3) h = [...h].map((c) => c + c).join("");
  const ch = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const [r = 0, g = 0, b = 0] = ch;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [x = 0, y = 0] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

function tok(name: string): string {
  const v = rootTokens[name];
  if (v === undefined) throw new Error(`token --${name} is not defined on :root`);
  return v;
}

function varName(value: string | undefined): string | null {
  return /var\(--([\w-]+)\)/.exec(value ?? "")?.[1] ?? null;
}

/** Селекторы, действующие на кнопку «Задача» (plan §4.5). */
function appliesToCreateButton(sel: string): boolean {
  return (
    sel === "button" ||
    /^button:/.test(sel) ||
    sel === ":focus-visible" ||
    sel === ".ui-sidebar button" ||
    /^\.ui-sidebar button:/.test(sel) ||
    sel.includes('[data-action="create-task"]')
  );
}

const buttonRules = rules.filter((r) => r.selectors.some(appliesToCreateButton));
const COLOR_PROPS = ["background", "background-color", "color", "border", "border-color", "outline", "outline-color", "fill", "stroke"];
const FORBIDDEN_COLOR = /#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(|\b(white|black|red|green|blue|gray|grey|silver|yellow|orange|purple|pink|brown)\b/i;

describe("004 AC-42: стиль кнопки «Задача» (только токены темы)", () => {
  it("004_ac42_rules_for_button_exist", () => {
    expect(buttonRules.length).toBeGreaterThanOrEqual(3);
  });

  it("004_ac42_button_colors_only_var_tokens", () => {
    for (const r of buttonRules) {
      for (const [prop, val] of Object.entries(r.decls)) {
        if (!COLOR_PROPS.includes(prop)) continue;
        const sel = r.selectors.join(",");
        const rest = val.replace(/var\(--[\w-]+\)/g, "");
        expect(rest, `${sel} { ${prop}: ${val} }`).not.toMatch(FORBIDDEN_COLOR);
        if (!["border", "outline"].includes(prop) && !/^(none|inherit|currentcolor|transparent)$/i.test(val)) {
          expect(val, `${sel} { ${prop} }`).toMatch(/var\(--[\w-]+\)/);
        }
      }
    }
  });

  it("004_ac42_button_is_pill_999px", () => {
    const d = topRules.find((r) => r.selectors.includes("button"))?.decls ?? {};
    expect(d["border-radius"]).toBe("999px");
  });

  it("004_ac42_button_uses_button_tokens", () => {
    const d = topRules.find((r) => r.selectors.includes("button"))?.decls ?? {};
    expect(varName(d["background"] ?? d["background-color"])).toBe("button-bg");
    expect(varName(d["color"])).toBe("button-text");
  });

  it("004_ac42_contrast_button_text_on_button_bg_normal", () => {
    expect(contrast(tok("button-text"), tok("button-bg"))).toBeGreaterThanOrEqual(4.5);
  });

  it("004_ac42_contrast_on_hover_if_hover_rule_exists", () => {
    const hover = buttonRules.filter((r) => r.selectors.some((s) => /:hover/.test(s)));
    for (const r of hover) {
      const bg = varName(r.decls["background"] ?? r.decls["background-color"]) ?? "button-bg";
      const fg = varName(r.decls["color"]) ?? "button-text";
      expect(contrast(tok(fg), tok(bg)), r.selectors.join(",")).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("004_ac42_focus_ring_uses_focus_token_with_contrast_3_on_surface", () => {
    const d = topRules.find((r) => r.selectors.includes(":focus-visible"))?.decls ?? {};
    expect(d["outline"]).toContain("var(--focus)");
    expect(contrast(tok("focus"), tok("surface"))).toBeGreaterThanOrEqual(3);
  });
});

describe("004 AC-42 / D-11: раскладка бокового меню (к низу прижата только «Выйти»)", () => {
  const sidebarButton = () => topRules.find((r) => r.selectors.includes(".ui-sidebar button"))?.decls ?? {};
  const logout = () => topRules.find((r) => r.selectors.includes('.ui-sidebar [data-action="logout"]'))?.decls ?? {};

  it("004_ac42_sidebar_button_has_no_margin_top_auto", () => {
    expect(sidebarButton()["margin-top"]).not.toBe("auto");
  });

  it("004_ac42_sidebar_button_is_single_line", () => {
    expect(sidebarButton()["white-space"]).toBe("nowrap");
  });

  it("004_ac42_logout_is_pushed_to_bottom", () => {
    expect(logout()["margin-top"]).toBe("auto");
  });

  it("004_ac42_narrow_screen_moves_margin_to_logout_only", () => {
    const narrow = parseRules(mediaNarrow);
    const lo = narrow.find((r) => r.selectors.includes('.ui-sidebar [data-action="logout"]'));
    expect(lo?.decls["margin-top"]).toBe("0");
    expect(lo?.decls["margin-left"]).toBe("auto");
    const generic = narrow.find((r) => r.selectors.includes(".ui-sidebar button"));
    expect(generic?.decls["margin-left"]).toBeUndefined();
  });
});

describe("004 D-7: слой окна", () => {
  it("004_ac42_overlay_z_index_10", () => {
    const d = topRules.find((r) => r.selectors.includes(".ui-overlay"))?.decls ?? {};
    expect(d["z-index"]).toBe("10");
  });

  it("004_ac42_shell_overlay_has_no_margin", () => {
    const d = topRules.find((r) => r.selectors.includes(".ui-shell > .ui-overlay"))?.decls ?? {};
    expect(d["margin"]).toMatch(/^0(px)?$/);
  });
});

describe("004 D-11: иконка plus", () => {
  const names = ["projects", "tasks", "users", "audit", "password", "logout"];
  const html = (name: string) => renderToStaticMarkup(createElement(Icon, { name: name as never }));

  it("004_ac42_plus_icon_draws_a_plus", () => {
    const h = html("plus");
    expect(h).toContain('d="M12 5v14"');
    expect(h).toContain('d="M5 12h14"');
  });

  it("004_ac42_plus_icon_differs_from_other_icons", () => {
    const plus = html("plus");
    for (const n of names) expect(html(n), n).not.toBe(plus);
  });
});
