// T90: тёмная тема по референсу docs/ui/task-plane.png (NFR-7: контраст AA, видимый фокус).
//
// Контракт для исполнителя (frontend/src/shared/ui/ui.css, тест читает его как текст):
//  1. Блок `:root { ... }` с токенами (цвета только в hex #rgb/#rrggbb):
//       --bg, --surface, --surface-2, --border, --text, --text-muted,
//       --accent (акцентный цвет текста/ссылок), --accent-contrast (текст на фоне --accent),
//       --danger, --focus, --button-bg, --button-text.
//     Контраст (WCAG): text/bg, text/surface, text/surface-2, text-muted/surface,
//     accent/surface, danger/surface, button-text/button-bg, accent-contrast/accent >= 4.5;
//     focus/bg и focus/surface >= 3.
//  2. Вне блока токенов цвета только через var(--...). Исключение: rgba(...) в `.ui-overlay`.
//     hex/rgb()/hsl()/именованные цвета запрещены. Нет @import, url(http...), @font-face/внешних шрифтов.
//  3. Правила (хотя бы одно с таким селектором в списке; значения через var(--...)):
//       body: background|background-color и color
//       .ui-sidebar: background и border-right* (левая панель навигации; класс добавляется в разметку оболочки)
//       .ui-table (+ `.ui-table th`/`td` с border через var)
//       .ui-tabs [role="tab"]: background, color, border*; и [aria-selected="true"] с background,
//         отличным от невыбранной вкладки
//       .ui-dialog: background, border*, border-radius; .ui-overlay: rgba-фон
//       button, a, input, textarea, select: color (a) / background+border+color (остальные)
//       [data-column]: background, border*, border-radius; [data-task-id]: background, border*
//       :focus-visible: outline использует var(--focus)
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

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
      selectors: (m[1] ?? "").split(",").map((s) => s.trim().replace(/\s+/g, " ")),
      decls,
    });
  }
  return rules;
}

const rules = parseRules(css);

function declsFor(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rules) if (r.selectors.includes(selector)) Object.assign(out, r.decls);
  return out;
}

/** Значение первого из свойств (или по префиксу `border`), содержащее var(--...). */
function usesVar(selector: string, props: string[]): void {
  const d = declsFor(selector);
  const found = Object.entries(d).find(
    ([k, v]) => props.some((p) => k === p || k.startsWith(`${p}-`)) && /var\(--[\w-]+\)/.test(v),
  );
  expect(found, `${selector}: ожидается ${props.join("|")} через var(--...)`).toBeTruthy();
}

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

const REQUIRED = [
  "bg", "surface", "surface-2", "border", "text", "text-muted",
  "accent", "accent-contrast", "danger", "focus", "button-bg", "button-text",
];

describe("T90 theme tokens", () => {
  it("defines all design tokens on :root as hex colors", () => {
    for (const t of REQUIRED) {
      expect(rootTokens[t], `--${t}`).toMatch(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
    }
  });

  it("is a dark theme (bg darker than surface-2 text)", () => {
    expect(tok("bg"), "--bg").toBeTruthy();
    expect(lum(tok("bg"))).toBeLessThan(0.05);
    expect(lum(tok("text"))).toBeGreaterThan(0.5);
    expect(lum(tok("surface"))).toBeGreaterThanOrEqual(lum(tok("bg")));
    expect(declsFor(":root")["color-scheme"]).toMatch(/dark/);
  });

  const pairs: [string, string, number][] = [
    ["text", "bg", 4.5],
    ["text", "surface", 4.5],
    ["text", "surface-2", 4.5],
    ["text-muted", "surface", 4.5],
    ["text-muted", "bg", 4.5],
    ["accent", "surface", 4.5],
    ["danger", "surface", 4.5],
    ["button-text", "button-bg", 4.5],
    ["accent-contrast", "accent", 4.5],
    ["focus", "bg", 3],
    ["focus", "surface", 3],
  ];
  for (const [fg, bg, min] of pairs) {
    it(`contrast --${fg} on --${bg} >= ${min}`, () => {
      expect(rootTokens[fg], `--${fg}`).toBeTruthy();
      expect(rootTokens[bg], `--${bg}`).toBeTruthy();
      expect(contrast(tok(fg), tok(bg))).toBeGreaterThanOrEqual(min);
    });
  }
});

describe("T90 no hard-coded colors / no external resources", () => {
  const NAMED =
    /\b(white|black|red|green|blue|gray|grey|silver|navy|teal|purple|orange|yellow|maroon|olive|lime|aqua|fuchsia|pink|brown)\b/i;
  const COLOR_PROPS = /^(color|background|background-color|border|border-[\w-]+|outline|outline-color|box-shadow|fill|stroke|text-decoration-color|caret-color|accent-color)$/;

  it("uses colors outside :root only via var(--...) (rgba allowed in .ui-overlay)", () => {
    const bad: string[] = [];
    for (const r of rules) {
      if (r.selectors.includes(":root")) continue;
      for (const [k, v] of Object.entries(r.decls)) {
        if (!COLOR_PROPS.test(k)) continue;
        const stripped = v.replace(/var\(--[\w-]+\)/g, "");
        const overlayOk = r.selectors.includes(".ui-overlay") && /^rgba\(/.test(stripped.trim());
        if (overlayOk) continue;
        if (/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/.test(stripped) || NAMED.test(stripped)) {
          bad.push(`${r.selectors.join(",")} { ${k}: ${v} }`);
        }
      }
    }
    expect(bad).toEqual([]);
  });

  it("has no @import, remote url() or font-face", () => {
    expect(css).not.toMatch(/@import/i);
    expect(css).not.toMatch(/url\(\s*['"]?(https?:)?\/\//i);
    expect(css).not.toMatch(/@font-face/i);
  });
});

describe("T90 shell and component styles", () => {
  it("body uses token background and color", () => {
    usesVar("body", ["background"]);
    usesVar("body", ["color"]);
  });

  it(".ui-sidebar (left navigation panel) is styled", () => {
    usesVar(".ui-sidebar", ["background"]);
    usesVar(".ui-sidebar", ["border"]);
  });

  it(".ui-table cells use token borders", () => {
    usesVar(".ui-table th", ["border"]);
    usesVar(".ui-table td", ["border"]);
  });

  it("tabs are styled and the selected tab is distinguishable", () => {
    const tab = '.ui-tabs [role="tab"]';
    usesVar(tab, ["background"]);
    usesVar(tab, ["color"]);
    usesVar(tab, ["border"]);
    const sel = declsFor('.ui-tabs [role="tab"][aria-selected="true"]');
    const base = declsFor(tab);
    expect(sel["background"] ?? sel["background-color"]).toMatch(/var\(--/);
    expect(sel["background"] ?? sel["background-color"]).not.toBe(
      base["background"] ?? base["background-color"],
    );
  });

  it("dialog and overlay", () => {
    usesVar(".ui-dialog", ["background"]);
    usesVar(".ui-dialog", ["border"]);
    expect(declsFor(".ui-dialog")["border-radius"]).toBeTruthy();
    const ov = declsFor(".ui-overlay");
    expect(ov["background"] ?? ov["background-color"]).toMatch(/rgba\(/);
  });

  it("controls use token background, border and color", () => {
    for (const sel of ["button", "input", "textarea", "select"]) {
      usesVar(sel, ["background"]);
      usesVar(sel, ["border"]);
      usesVar(sel, ["color"]);
    }
    usesVar("a", ["color"]);
  });

  it("buttons use the pill style with button tokens", () => {
    const d = declsFor("button");
    expect(d["background"] ?? d["background-color"]).toContain("var(--button-bg)");
    expect(d["color"]).toContain("var(--button-text)");
    expect(Number.parseFloat(d["border-radius"] ?? "0")).toBeGreaterThanOrEqual(16);
  });

  it("board columns and cards are styled", () => {
    usesVar("[data-column]", ["background"]);
    usesVar("[data-column]", ["border"]);
    expect(declsFor("[data-column]")["border-radius"]).toBeTruthy();
    usesVar("[data-task-id]", ["background"]);
    usesVar("[data-task-id]", ["border"]);
  });

  it(":focus-visible uses --focus", () => {
    const d = declsFor(":focus-visible");
    expect(d["outline"] ?? d["outline-color"]).toContain("var(--focus)");
    expect(d["outline"]).not.toMatch(/\bnone\b|\b0\b/);
  });
});

describe("T92 .ui-home-link (pill link styled like buttons)", () => {
  const SEL = ".ui-home-link";

  it("is defined and uses button tokens", () => {
    const d = declsFor(SEL);
    expect(Object.keys(d).length, `${SEL} is not defined`).toBeGreaterThan(0);
    expect(d["background"] ?? d["background-color"]).toContain("var(--button-bg)");
    expect(d["color"]).toContain("var(--button-text)");
    expect(contrast(tok("button-text"), tok("button-bg"))).toBeGreaterThanOrEqual(4.5);
  });

  it("has pill radius >= 16px, inline box, padding and no underline", () => {
    const d = declsFor(SEL);
    expect(Number.parseFloat(d["border-radius"] ?? "0")).toBeGreaterThanOrEqual(16);
    expect(d["display"]).toMatch(/^inline-(flex|block)$/);
    expect(d["padding"], "padding").toBeTruthy();
    expect(d["text-decoration"] ?? d["text-decoration-line"]).toMatch(/^none\b/);
  });

  it("has a border through a token", () => {
    usesVar(SEL, ["border"]);
  });

  it(":hover is styled through tokens", () => {
    const d = declsFor(`${SEL}:hover`);
    expect(Object.keys(d).length, `${SEL}:hover is not defined`).toBeGreaterThan(0);
    const vals = Object.values(d).join(" ");
    expect(vals).toMatch(/var\(--[\w-]+\)/);
    expect(d["text-decoration"] ?? "none").toMatch(/^none\b/);
  });

  it(":focus-visible is styled through the --focus token", () => {
    const d = declsFor(`${SEL}:focus-visible`);
    expect(Object.keys(d).length, `${SEL}:focus-visible is not defined`).toBeGreaterThan(0);
    expect(d["outline"] ?? d["outline-color"] ?? d["box-shadow"]).toContain("var(--focus)");
    expect(d["outline"] ?? "").not.toMatch(/\bnone\b|\b0\b/);
  });
});
