// Spec 005-login-help v0.3: layout contracts of the login screen, checked on the CSS text.
// Design: OpenBot/Shared/Design/login-first-screen-design.md, decisions P-1, P-2, P-6 (2026-11-08).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const strip = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "");
const uiCss = strip(readFileSync(resolve(__dirname, "../../../src/shared/ui/ui.css"), "utf8"));
const authCss = strip(readFileSync(resolve(__dirname, "../../../src/features/auth/auth-screens.css"), "utf8"));

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
    rules.push({ selectors: (m[1] ?? "").split(",").map((s) => s.trim().replace(/\s+/g, " ")), decls });
  }
  return rules;
}

function declsFor(rules: Rule[], selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rules) if (r.selectors.includes(selector)) Object.assign(out, r.decls);
  return out;
}

const ui = parseRules(uiCss);
const auth = parseRules(authCss);

describe("spec 005 v0.3 P-1: border of text fields", () => {
  it("shared field rule uses --text-muted for the border (1.36:1 -> 6.66:1 on --surface-2)", () => {
    const rule = ui.find((r) => r.selectors.includes("input") && r.selectors.includes("textarea") && r.selectors.includes("select"));
    expect(rule, "input, textarea, select rule").toBeTruthy();
    expect(rule!.decls["border"]).toBe("1px solid var(--text-muted)");
  });

  it("--border token itself is unchanged (cards and other containers keep it)", () => {
    expect(declsFor(ui, ".ui-form")["border"]).toBe("1px solid var(--border)");
  });
});

describe("spec 005 v0.3 P-2: show/hide button is a 44 by 44 px target (shared ui.css)", () => {
  it("reveal button has width, height and minimum size 44px", () => {
    const d = declsFor(ui, ".ui-reveal");
    expect(d["width"]).toBe("44px");
    expect(d["height"]).toBe("44px");
    expect(d["min-width"]).toBe("44px");
    expect(d["min-height"]).toBe("44px");
  });
});

describe("spec 005 v0.3 ErrorAlert (UI kit section 5): block with --danger border", () => {
  it("alert block has a 1px --danger border and a --surface-2 background", () => {
    const d = declsFor(ui, ".ui-error-alert");
    expect(d["border"]).toBe("1px solid var(--danger)");
    expect(d["background"]).toBe("var(--surface-2)");
    expect(d["display"]).toBe("flex");
  });

  it("alert icon is drawn in --danger", () => {
    expect(declsFor(ui, ".ui-error-alert .ui-icon")["color"]).toBe("var(--danger)");
  });
});

describe("spec 005 v0.3 P-6: card is centred", () => {
  it("form container keeps horizontal auto margins", () => {
    expect(declsFor(ui, ".ui-form")["margin"]).toBe("2rem auto");
  });
});

describe("spec 005 v0.3 design: logo size and head spacing on the login card", () => {
  it("logo is 40 px and the brand row has a 20 px gap below it", () => {
    const logo = declsFor(auth, ".login-card .ui-brand .ui-logo");
    expect(logo["width"]).toBe("40px");
    expect(logo["height"]).toBe("40px");
    expect(declsFor(auth, ".login-card .ui-brand")["margin-bottom"]).toBe("20px");
  });
});

describe("spec 005 v0.3 NFR-2: login screen styles use theme tokens only", () => {
  it("auth-screens.css has no hex colours", () => {
    expect(authCss).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });
});
