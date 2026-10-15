// T22: словарь строк (plan §4.14, NFR-6, AC-98, FR-45).
//
// Контракт для исполнителя:
//   src/shared/i18n/ru.ts    export const ru = { "error.<code>": "...", ... } as const  (плоский)
//   src/shared/i18n/index.ts export { ru }; export function t(key: keyof typeof ru,
//                                params?: Record<string, string | number>): string
//                            export function errorMessage(code: string): string
//   Плейсхолдеры в значениях: {name}. Неизвестный ключ: t() возвращает сам ключ и не бросает.
//   errorMessage(code): ru["error.<code>"], а для неизвестного кода — ru["error.unknown"].
import { describe, expect, it } from "vitest";

import { PASSWORD_MIN_LENGTH, errorMessage, t } from "../../src/shared/i18n";
import { ru } from "../../src/shared/i18n/ru";

const CYRILLIC = /[Ѐ-ӿ]/;

// Коды из backend/app/core/errors.py + клиентские коды ApiError (client.ts).
const API_CODES = [
  "not_authenticated",
  "invalid_credentials",
  "password_change_required",
  "no_role",
  "forbidden",
  "origin_mismatch",
  "not_found",
  "validation_error",
  "last_account_admin",
  "login_taken",
  "login_invalid",
  "password_too_short",
  "password_too_common",
  "invalid_current_password",
  "password_reused",
  "internal_error",
];
const CLIENT_CODES = ["network_error", "invalid_response"];
// Коды из общего обработчика HTTP-ошибок backend (core/errors.py, _HTTP_STATUS_MAP).
const HTTP_CODES = [
  "bad_request",
  "method_not_allowed",
  "payload_too_large",
  "unsupported_media_type",
  "too_many_requests",
  "http_error",
];
const PLACEHOLDER = /\{[a-z_]+\}/;

const dict = ru as Record<string, string>;

// Лексический срез комментариев: строки ('', "", ``) не трогаются; `//` сразу после `:`
// (URL в JSX-тексте, «http://…») комментарием не считается.
export function stripComments(src: string): string {
  let out = "";
  let i = 0;
  while (i < src.length) {
    const c = src[i]!;
    const n = src[i + 1];
    if (c === '"' || c === "'" || c === "`") {
      let j = i + 1;
      while (j < src.length && src[j] !== c) {
        if (src[j] === "\\") j += 1;
        else if (src[j] === "\n" && c !== "`") break;
        j += 1;
      }
      out += src.slice(i, j + 1);
      i = j + 1;
    } else if (c === "/" && n === "/" && src[i - 1] !== ":") {
      while (i < src.length && src[i] !== "\n") i += 1;
    } else if (c === "/" && n === "*") {
      const end = src.indexOf("*/", i + 2);
      i = end === -1 ? src.length : end + 2;
    } else {
      out += c;
      i += 1;
    }
  }
  return out;
}

describe("stripComments (self-check of the AC-98 scanner)", () => {
  it("drops real comments", () => {
    expect(CYRILLIC.test(stripComments("const a = 1; // Привет\n"))).toBe(
      false,
    );
    expect(CYRILLIC.test(stripComments("/* Привет */ const a = 1;"))).toBe(
      false,
    );
    expect(CYRILLIC.test(stripComments("a();//Привет"))).toBe(false);
  });

  it("keeps Cyrillic in string literals even after //", () => {
    expect(CYRILLIC.test(stripComments('const a = "x//Привет";'))).toBe(true);
    expect(CYRILLIC.test(stripComments("const a = 'x//Привет';"))).toBe(true);
    expect(CYRILLIC.test(stripComments("const a = `x//Привет`;"))).toBe(true);
  });

  it("keeps JSX text with a URL-like // sequence", () => {
    expect(CYRILLIC.test(stripComments("<p>http://Привет</p>"))).toBe(true);
  });
});

describe("ru dictionary (NFR-6)", () => {
  it.each([...API_CODES, ...CLIENT_CODES, ...HTTP_CODES, "unknown"])(
    "has a Russian message for error.%s",
    (code) => {
      const value = dict[`error.${code}`];
      expect(typeof value).toBe("string");
      expect(CYRILLIC.test(value!)).toBe(true);
    },
  );

  it("has no empty, whitespace-only or placeholder values", () => {
    const entries = Object.entries(dict);
    expect(entries.length).toBeGreaterThan(API_CODES.length);
    for (const [key, value] of entries) {
      expect(typeof value, key).toBe("string");
      expect(value.trim().length, key).toBeGreaterThan(0);
      expect(value, key).not.toBe(key);
      expect(value, key).not.toMatch(/^(todo|tbd|fixme|xxx|\?+|lorem)/i);
    }
  });

  it("error messages are pairwise distinct (no copy-pasted stubs)", () => {
    const values = Object.entries(dict)
      .filter(([k]) => k.startsWith("error."))
      .map(([, v]) => v);
    expect(new Set(values).size).toBe(values.length);
  });

  it("keys are dotted lower-case identifiers", () => {
    for (const key of Object.keys(dict)) {
      expect(key).toMatch(/^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/);
    }
  });
});

describe("t()", () => {
  it("returns the dictionary value for a known key", () => {
    expect(t("error.not_found" as keyof typeof ru)).toBe(
      dict["error.not_found"],
    );
  });

  it("password hint lives in its own key and substitutes {min} from PASSWORD_MIN_LENGTH", () => {
    const key = "auth.password_min_length_hint" as keyof typeof ru;
    const raw = dict["auth.password_min_length_hint"];
    expect(raw).toBeDefined();
    expect(raw).toContain("{min}");
    expect(PASSWORD_MIN_LENGTH).toBe(12); // backend MIN_PASSWORD_LENGTH
    const out = t(key, { min: PASSWORD_MIN_LENGTH });
    expect(out).toContain(String(PASSWORD_MIN_LENGTH));
    expect(out).not.toMatch(PLACEHOLDER);
    expect(CYRILLIC.test(out)).toBe(true);
  });

  it("the parametrised hint is not used as an error message", () => {
    const hint = dict["auth.password_min_length_hint"];
    for (const code of [
      ...API_CODES,
      ...CLIENT_CODES,
      ...HTTP_CODES,
      "unknown",
    ]) {
      expect(errorMessage(code), code).not.toBe(hint);
    }
  });

  it("a value without placeholders ignores extra params", () => {
    const key = "error.not_found" as keyof typeof ru;
    expect(t(key, { unused: 1 })).toBe(dict["error.not_found"]);
  });

  it("unknown key: returns the key itself, does not throw, deterministic", () => {
    const key = "no.such.key" as keyof typeof ru;
    expect(() => t(key)).not.toThrow();
    expect(t(key)).toBe("no.such.key");
    expect(t(key)).toBe(t(key));
    expect(t(key, { a: 1 })).toBe("no.such.key");
  });
});

describe("errorMessage()", () => {
  it.each([...API_CODES, ...CLIENT_CODES, ...HTTP_CODES, "unknown"])(
    "message for %s has no unsubstituted {placeholder}",
    (code) => {
      expect(errorMessage(code)).not.toMatch(PLACEHOLDER);
    },
  );

  it("no error.* dictionary value contains a placeholder", () => {
    for (const [k, v] of Object.entries(dict)) {
      if (k.startsWith("error.")) expect(v, k).not.toMatch(PLACEHOLDER);
    }
  });

  it.each([...API_CODES, ...CLIENT_CODES, ...HTTP_CODES])(
    "maps %s to its dictionary message",
    (code) => {
      expect(errorMessage(code)).toBe(dict[`error.${code}`]);
    },
  );

  it("falls back to error.unknown for an unknown code", () => {
    expect(errorMessage("brand_new_code")).toBe(dict["error.unknown"]);
    expect(errorMessage("")).toBe(dict["error.unknown"]);
  });
});

// --- Latin JSX text and literal user-visible attributes (T32, AC-98, acceptance note 4) ---------
//
// Scanner for .tsx sources (comments stripped first). It reports:
//   1. JSX text nodes with a Latin letter: `>Hello<`, `>Hello {x}<`, `{x} Hello</p>`,
//      `>{"Hello"}<`;
//   2. user-visible attributes given as a string literal (`aria-label="Close"`,
//      `placeholder={'Search'}`, backticks without `${}`): aria-label, aria-description,
//      aria-placeholder, aria-roledescription, aria-valuetext, placeholder, title, alt, label.
// Not reported (technical or dictionary values): type, name, id, role, className, href,
// autoComplete, data-*, aria-labelledby/-describedby (element ids), aria-modal, and any value
// coming from t(...) or another expression - they are not string literals of a listed attribute.
// Known limits (heuristic, no TS parser): text containing any of `;=()&|` is skipped so that
// generics and statements such as `useState<Foo>(null);` are not mistaken for JSX text.

const VISIBLE_ATTRS = [
  "aria-label",
  "aria-description",
  "aria-placeholder",
  "aria-roledescription",
  "aria-valuetext",
  "placeholder",
  "title",
  "alt",
  "label",
];
// Explicit whitelist of Latin literals that are allowed outside the dictionary. Everything else
// with a Latin letter must live in ru.ts. Values without Latin letters (numbers, punctuation,
// "—", "×", "/", "…", " ") are never reported.
const LATIN_ALLOWED = new Set<string>([
  "GOSTracker", // product name: a proper noun, not translated (NFR-6)
]);
const LATIN = /[A-Za-z]/;

export interface Finding {
  line: number;
  kind: "text" | "attribute";
  value: string;
}

function lineOf(src: string, index: number): number {
  return src.slice(0, index).split("\n").length;
}

function isViolation(value: string): boolean {
  const v = value.trim();
  return LATIN.test(v) && !LATIN_ALLOWED.has(v);
}

export function scanLatinUi(source: string): Finding[] {
  const src = stripComments(source);
  const found: Finding[] = [];
  const add = (index: number, kind: Finding["kind"], value: string): void => {
    if (isViolation(value))
      found.push({ line: lineOf(src, index), kind, value: value.trim() });
  };

  // text after a tag end ">" (up to "<" or "{")
  for (const m of src.matchAll(/>([^<>{};=()&|]*)(?=[<{])/g)) {
    const before = src[m.index! - 1];
    if (before === "=" || before === "-") continue; // arrow function, not a tag end
    add(m.index! + 1, "text", m[1]!);
  }
  // text after "}" on the same line, followed by a tag
  for (const m of src.matchAll(/\}([^<>{}\n;=()]+)(?=<[/A-Za-z])/g)) {
    add(m.index! + 1, "text", m[1]!);
  }
  // string literal in a JSX expression container: >{"Hello"}<
  for (const m of src.matchAll(/>\s*\{\s*(["'])([^"'\n]*)\1\s*\}/g)) {
    add(m.index!, "text", m[2]!);
  }
  // literal values of user-visible attributes
  const names = VISIBLE_ATTRS.map((a) => a.replace("-", "\\-")).join("|");
  const attr = new RegExp(
    `(?<![\\w-])(?:${names})=(?:"([^"]*)"|'([^']*)'|\\{\\s*(?:"([^"]*)"|'([^']*)'|` +
      "`([^`$]*)`" +
      `)\\s*\\})`,
    "g",
  );
  for (const m of src.matchAll(attr)) {
    add(m.index!, "attribute", m.slice(1).find((x) => x !== undefined) ?? "");
  }
  return found;
}

describe("scanLatinUi (self-check of the T32 scanner)", () => {
  const caught = (code: string): Finding[] => scanLatinUi(code);

  it("catches a Latin aria-label literal", () => {
    expect(caught('const a = <button aria-label="Close">×</button>;')).toEqual([
      { line: 1, kind: "attribute", value: "Close" },
    ]);
  });

  it("catches a Latin JSX text node", () => {
    expect(caught("const a = <p>Hello</p>;")).toEqual([
      { line: 1, kind: "text", value: "Hello" },
    ]);
  });

  it("catches placeholder/title/alt in all literal forms", () => {
    for (const code of [
      '<input placeholder="Search" />',
      "<input placeholder={'Search'} />",
      '<input placeholder={"Search"} />',
      "<input placeholder={`Search`} />",
      '<span title="Hint">·</span>',
      '<img alt="Logo" />',
    ]) {
      expect(caught(code).length, code).toBeGreaterThan(0);
    }
  });

  it("catches a string literal in an expression container and text next to an expression", () => {
    expect(caught('<p>{"Hello"}</p>').length).toBe(1);
    expect(caught("<p>{count} items</p>").length).toBe(1);
    expect(caught("<p>Hello {name}</p>").length).toBe(1);
  });

  it("reports the line of the offence", () => {
    expect(caught("const a = 1;\nconst b = <p>\n  Hello\n</p>;")[0]?.line).toBe(
      2,
    );
  });

  it("ignores dictionary values and technical attributes", () => {
    for (const code of [
      '<button aria-label={t("common.close")}>{t("common.ok")}</button>',
      '<input type="password" name="login" id="login" autoComplete="off" />',
      '<a href="/admin" className="link" role="button" data-testid="x">{t("a.b")}</a>',
      '<div aria-labelledby="admin-password-title" aria-modal="true" />',
      '<input placeholder={t("a.hint")} title={`${id}-t`} />',
      "<p>—</p>",
      "<p>{n} / {m}</p>",
      "<span>{label}: {value}</span>",
      "const [a, setA] = useState<Foo | null>(null);\nconst r = useRef<HTMLDivElement>(null);",
      "const f = async (): Promise<void> => {};\nconst g = (x: number) => x > 1 && x < 3;",
      "const c = <Select<Option> />;",
    ]) {
      expect(caught(code), code).toEqual([]);
    }
  });

  it("does not look into comments", () => {
    expect(caught('// <p>Hello</p>\n/* <b aria-label="Close"/> */')).toEqual(
      [],
    );
  });

  it("allows only the explicit whitelist", () => {
    expect(caught("<h1>GOSTracker</h1>")).toEqual([]);
    expect(caught("<h1>GOSTracker CRM</h1>").length).toBe(1);
  });
});

describe("no Latin UI literals in src/**/*.tsx (AC-98, NFR-6, T32)", () => {
  const tsx = import.meta.glob("../../src/**/*.tsx", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("scans the JSX sources", () => {
    expect(Object.keys(tsx).length).toBeGreaterThanOrEqual(10);
  });

  it("JSX text nodes and visible attributes come from the dictionary", () => {
    const offenders: string[] = [];
    for (const [path, source] of Object.entries(tsx)) {
      for (const f of scanLatinUi(source)) {
        offenders.push(
          `${path.replace("../../", "")}:${f.line} ${f.kind} ${JSON.stringify(f.value)}`,
        );
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("no UI strings outside the dictionary (AC-98, NFR-6)", () => {
  // schema.d.ts — генерируемые типы без исполняемых строк; русские описания лежат в комментариях.
  const files = {
    ...(import.meta.glob("../../src/**/*.tsx", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>),
    ...(import.meta.glob("../../src/**/*.ts", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>),
  };

  it("sees the T22 source files", () => {
    const names = Object.keys(files);
    for (const f of [
      "shared/api/client.ts",
      "shared/api/polling.ts",
      "shared/i18n/ru.ts",
      "shared/i18n/index.ts",
    ]) {
      expect(
        names.some((n) => n.endsWith(`src/${f}`)),
        f,
      ).toBe(true);
    }
  });

  it("no Cyrillic in src/**/*.ts(x) outside src/shared/i18n (string literals and JSX text)", () => {
    const offenders: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      if (path.includes("/shared/i18n/")) continue;
      if (path.endsWith("/schema.d.ts")) continue;
      if (CYRILLIC.test(stripComments(source))) offenders.push(path);
    }
    expect(offenders).toEqual([]);
  });

  it("the dictionary itself lives in src/shared/i18n and contains the Russian text", () => {
    const ruPath = Object.keys(files).find((p) =>
      p.endsWith("src/shared/i18n/ru.ts"),
    );
    expect(ruPath).toBeDefined();
    expect(CYRILLIC.test(files[ruPath!]!)).toBe(true);
  });
});
