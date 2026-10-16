// T100: шрифты +4px (docs/ui/backlog.md, п.3). Тест читает src/shared/ui/ui.css как текст.
//
// Контракт: каждое объявление font-size (rem, при html font-size 16px) = прежнее + 0.25rem;
//   body = 19px либо 1.1875rem. Новых font-size без записи в таблице быть не должно.
//   Токены и цвета не меняются (проверяет theme.test.ts).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "../../src/shared/ui/ui.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function sizes(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    const d = /(?:^|;)\s*font-size\s*:\s*([^;]+)/.exec(m[2] ?? "");
    if (d) out.push([(m[1] ?? "").trim().replace(/\s+/g, " "), (d[1] ?? "").trim()]);
  }
  return out;
}

function px(v: string): number {
  const m = /^([\d.]+)(rem|px)$/.exec(v);
  if (!m) throw new Error(`unexpected font-size unit: ${v}`);
  return Number(m[1]) * (m[2] === "rem" ? 16 : 1);
}

// selector -> прежний размер, px (до T100)
const OLD: Record<string, number> = {
  body: 15,
  h1: 24,
  h2: 18,
  h3: 16,
  dt: 13,
  button: 14,
  ".ui-home-link": 14,
  ".ui-hint": 14,
  ".ui-table th": 13,
  ".ui-secret code": 20,
  "[data-column] h3": 14,
  'li[data-task-id] [data-field]:not([data-field="title"])': 13,
};

describe("T100 font sizes +4px", () => {
  it("body font-size is 19px", () => {
    const body = sizes().find(([s]) => s === "body");
    expect(body).toBeDefined();
    expect(px(body![1])).toBe(19);
  });

  it.each(Object.entries(OLD))("font-size of %s is old + 4px", (selector, old) => {
    const hit = sizes().find(([s]) => s === selector);
    expect(hit, `no font-size rule for ${selector}`).toBeDefined();
    expect(px(hit![1])).toBeCloseTo(old + 4, 5);
  });

  it("no font-size declarations outside the table", () => {
    const unknown = sizes().filter(([s]) => !(s in OLD));
    expect(unknown).toEqual([]);
  });
});
