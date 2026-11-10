// Users table columns (UI-kit, 2026-11-08): words wrap by word, not by letter; name and e-mail columns keep a width.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "../../src/shared/ui/ui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function rule(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    const sels = (m[1] ?? "").split(",").map((x) => x.trim());
    if (!sels.includes(selector)) continue;
    for (const part of (m[2] ?? "").split(";")) {
      const i = part.indexOf(":");
      if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
    }
  }
  return out;
}

describe("users table columns wrap by words", () => {
  it("table cells use break-word, not anywhere (short Cyrillic words must not split by letter)", () => {
    expect(rule(".ui-table td")["overflow-wrap"]).toBe("break-word");
    expect(rule(".ui-table td")["overflow-wrap"]).not.toBe("anywhere");
  });

  it("name and origin columns have a minimum width", () => {
    for (const f of ["first_name", "last_name", "origin"]) {
      expect(rule(`.ui-table td[data-field="${f}"]`)["min-width"]).toBe("8rem");
    }
  });

  it("e-mail column keeps a width and may break inside a long address", () => {
    const d = rule('.ui-table td[data-field="email"]');
    expect(d["min-width"]).toBe("10rem");
    expect(d["overflow-wrap"]).toBe("anywhere");
  });
});
