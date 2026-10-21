// R6-T01 (006, plan 4.4, NFR-3): стили кнопки показа пароля в ui.css (читается как текст).
// .ui-input-row, .ui-input-row input, .ui-reveal существуют; у .ui-reveal min-width/min-height >= 24px;
// в этих правилах нет цветов вне var(--...) и нет font-size.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "../../src/shared/ui/ui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function rules(selector: string): string[] {
  const out: string[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    const sels = (m[1] ?? "").split(",").map((s) => s.trim().replace(/\s+/g, " "));
    if (sels.includes(selector)) out.push(m[2] ?? "");
  }
  return out;
}

const SELECTORS = [".ui-input-row", ".ui-input-row input", ".ui-reveal"];

function px(body: string, prop: string): number | null {
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([\\d.]+)(px|rem)`).exec(body);
  if (!m) return null;
  return Number(m[1]) * (m[2] === "rem" ? 16 : 1);
}

describe("reveal css (NFR-3)", () => {
  it.each(SELECTORS)("rule %s exists", (sel) => {
    expect(rules(sel).length).toBeGreaterThan(0);
  });

  it("ui-reveal min target size >= 24px", () => {
    const bodies = rules(".ui-reveal");
    const w = bodies.map((b) => px(b, "min-width")).find((v) => v !== null) ?? null;
    const h = bodies.map((b) => px(b, "min-height")).find((v) => v !== null) ?? null;
    expect(w).not.toBeNull();
    expect(h).not.toBeNull();
    expect(w as number).toBeGreaterThanOrEqual(24);
    expect(h as number).toBeGreaterThanOrEqual(24);
  });

  it("new rules have no raw colours and no font-size", () => {
    const bodies = SELECTORS.flatMap(rules);
    expect(bodies.length).toBeGreaterThan(0);
    for (const b of bodies) {
      expect(b).not.toMatch(/font-size/);
      expect(b).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(b).not.toMatch(/\b(rgb|rgba|hsl|hsla)\s*\(/);
      for (const d of b.split(";")) {
        const m = /^\s*(color|background(?:-color)?|border(?:-color)?|outline(?:-color)?|fill|stroke)\s*:\s*(.+)$/s.exec(d);
        if (m) expect(m[2]).toMatch(/var\(--/);
      }
    }
  });

  it("ui-input-row is a flex row, input shrinks", () => {
    expect(rules(".ui-input-row").join(";")).toMatch(/display\s*:\s*flex/);
    expect(rules(".ui-input-row input").join(";")).toMatch(/min-width\s*:\s*0/);
  });
});
