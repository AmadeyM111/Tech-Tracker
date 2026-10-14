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
    expect(CYRILLIC.test(stripComments("const a = 1; // Привет\n"))).toBe(false);
    expect(CYRILLIC.test(stripComments("/* Привет */ const a = 1;"))).toBe(false);
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
    expect(t("error.not_found" as keyof typeof ru)).toBe(dict["error.not_found"]);
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
    for (const code of [...API_CODES, ...CLIENT_CODES, ...HTTP_CODES, "unknown"]) {
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

  it.each([...API_CODES, ...CLIENT_CODES, ...HTTP_CODES])("maps %s to its dictionary message", (code) => {
    expect(errorMessage(code)).toBe(dict[`error.${code}`]);
  });

  it("falls back to error.unknown for an unknown code", () => {
    expect(errorMessage("brand_new_code")).toBe(dict["error.unknown"]);
    expect(errorMessage("")).toBe(dict["error.unknown"]);
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
    const ruPath = Object.keys(files).find((p) => p.endsWith("src/shared/i18n/ru.ts"));
    expect(ruPath).toBeDefined();
    expect(CYRILLIC.test(files[ruPath!]!)).toBe(true);
  });
});
