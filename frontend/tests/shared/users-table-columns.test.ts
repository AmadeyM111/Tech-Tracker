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

// UX-audit P1 (ta-accounts-to-be): компактная строка учётных записей и карточки на 360 px.
// Правила скоупятся на .ui-users-table: общие .ui-table правила выше не меняются (их использует другой экран).

/** Тела всех блоков @media (max-width: N px) - с учётом вложенных фигурных скобок. */
function mediaBodies(maxWidthPx: number): string[] {
  const out: string[] = [];
  const re = new RegExp(`@media\\s*\\(max-width:\\s*${maxWidthPx}px\\)\\s*\\{`, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    const start = m.index + m[0].length;
    let depth = 1;
    let i = start;
    while (depth > 0 && i < css.length) {
      if (css[i] === "{") depth += 1;
      else if (css[i] === "}") depth -= 1;
      i += 1;
    }
    out.push(css.slice(start, i - 1));
  }
  return out;
}

/** Объявления правила с селектором внутри @media (max-width: 719px). */
function mobileRule(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const body of mediaBodies(719)) {
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(body))) {
      const sels = (m[1] ?? "").split(",").map((x) => x.trim());
      if (!sels.includes(selector)) continue;
      for (const part of (m[2] ?? "").split(";")) {
        const i = part.indexOf(":");
        if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
      }
    }
  }
  return out;
}

describe("users accounts table: compact row and 360 px cards (UX-audit P1)", () => {
  it("secondary actions live in a native details summary with a 44px touch target", () => {
    expect(rule(".ui-users-more > summary")["min-height"]).toBe("44px");
  });

  it("the table has three desktop columns with explicit widths, not eight", () => {
    const widths = [".ui-users-table__account", ".ui-users-table__person", ".ui-users-table__actions"].map(
      (s) => rule(s)["width"],
    );
    for (const w of widths) expect(w, "desktop column width").toMatch(/^\d+%$/);
    const sum = widths.reduce((acc, w) => acc + Number((w ?? "0").replace("%", "")), 0);
    expect(sum).toBeLessThanOrEqual(100);
  });

  it("at 360 px the table, body, rows and cells become blocks (cards)", () => {
    for (const s of [".ui-users-table", ".ui-users-table tbody", ".ui-users-table tr", ".ui-users-table td"]) {
      expect(mobileRule(s)["display"], s).toBe("block");
    }
  });

  it("at 360 px the header row is hidden and each field shows its ru.ts label via data-label", () => {
    expect(mobileRule(".ui-users-table thead")["display"]).toBe("none");
    expect(mobileRule(".ui-users-table [data-label]::before")["content"]).toContain("attr(data-label)");
  });

  it("the card rules do not change the shared .ui-table on other screens", () => {
    expect(mobileRule(".ui-table td")["display"]).toBeUndefined();
    expect(mobileRule(".ui-table")["display"]).toBeUndefined();
    expect(rule(".ui-table td")["display"]).toBeUndefined();
  });
});
