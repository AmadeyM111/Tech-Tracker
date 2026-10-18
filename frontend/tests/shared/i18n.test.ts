// T22: словарь строк (plan §4.14, NFR-6, AC-98, FR-45).
//
// Контракт для исполнителя:
//   src/shared/i18n/ru.ts    export const ru = { "error.<code>": "...", ... } as const  (плоский)
//   src/shared/i18n/index.ts export { ru }; export function t(key: keyof typeof ru,
//                                params?: Record<string, string | number>): string
//                            export function errorMessage(code: string): string
//   Плейсхолдеры в значениях: {name}. Неизвестный ключ: t() возвращает сам ключ и не бросает.
//   errorMessage(code): ru["error.<code>"], а для неизвестного кода — ru["error.unknown"].
import * as ts from "typescript";
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
  // MVP (T71, T72, T29, T81)
  "owner_cannot_be_removed",
  "not_project_member",
  "recipient_wrong_role",
  "user_blocked",
  "user_not_found",
  "service_busy",
  "subtask_depth_exceeded",
  "invalid_neighbors",
  "project_deleted",
  "parent_task_deleted",
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

describe("003 dictionary cleanup (AC-18)", () => {
  it("003_ac18_no_home_keys", () => {
    expect(dict).not.toHaveProperty("app.home_title");
    expect(dict).not.toHaveProperty("app.home_link");
  });

  it("003_ac18_no_home_texts_among_values", () => {
    const values = Object.values(dict).map((v) => v.trim().toLowerCase());
    expect(values).not.toContain("главная");
    expect(values).not.toContain("на главную");
  });

  it("003_ac18_menu_label", () => {
    expect(dict["app.menu_label"]).toBe("Меню");
  });
});

describe("MVP error codes (T81, FR-45)", () => {
  const MVP = [
    "owner_cannot_be_removed",
    "not_project_member",
    "recipient_wrong_role",
    "user_blocked",
    "user_not_found",
    "service_busy",
    "subtask_depth_exceeded",
    "invalid_neighbors",
  ];

  it.each(MVP)("ac_fr45_%s_is_a_human_readable_russian_sentence", (code) => {
    const msg = errorMessage(code);
    expect(msg).not.toBe(dict["error.unknown"]);
    expect(msg).toBe(dict[`error.${code}`]);
    expect(CYRILLIC.test(msg)).toBe(true);
    expect(msg).not.toMatch(/[{}]/);
    expect(msg).not.toContain(code);
    expect(msg.trim().split(/\s+/).length).toBeGreaterThanOrEqual(2);
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

// --- Latin UI literals in .tsx sources (T32, T81: compiler API `typescript`, AC-98, NFR-6) --------
//
// Scanner on the TypeScript AST (comments are not nodes). It reports Latin letters in:
//   1. JsxText nodes (`<p>Hello</p>`, `{n} items`);
//   2. string / template literals that are rendered: JsxExpression children, including inside
//      ternaries, `&&` / `||` / `??`, parentheses and template substitutions
//      (`{c ? "Loading" : t("x")}`, `{ok && "Done"}`, `{`Total ${n}`}`; template parts count
//      only if they contain whitespace: `${id}-t` is an identifier);
//   3. string literals in attributes (`aria-label="Close"`, `message={"Failed"}`,
//      `title={c ? "A" : t("b")}`) for every attribute except the technical list below;
//   4. identifiers in the positions 2-3 that resolve to a `const X = "literal"` of the same file
//      (the finding is reported at the declaration: `const MSG = "Failed"` ... `{MSG}`).
// Not reported: arguments of calls (`t("x")`, `errorMessage("code")`), technical attributes
// (type, name, id, role, className, href, data-*, aria-* that are not user-visible, ...),
// comparisons and JSX inside expressions (`{a > b ? <hr/> : null}`), values without Latin letters.
const TECHNICAL_ATTRS = new Set([
  "key", "ref", "type", "name", "id", "role", "className", "style", "href", "to", "src",
  "htmlFor", "autoComplete", "autoCapitalize", "spellCheck", "inputMode", "tabIndex", "target",
  "rel", "method", "action", "lang", "dir", "min", "max", "step", "pattern", "accept", "value",
  "defaultValue", "variant", "size", "kind", "level", "as", "scope", "path", "colSpan", "rowSpan",
  "headers", "capability",
  "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-activedescendant",
  "aria-modal", "aria-live", "aria-current", "aria-expanded", "aria-haspopup", "aria-autocomplete",
  "aria-selected", "aria-checked", "aria-pressed", "aria-hidden", "aria-invalid", "aria-busy",
  "aria-sort", "aria-atomic", "aria-relevant", "aria-orientation",
]); // fmt: skip
// Whitelist of Latin literals allowed outside the dictionary (exact match after trim).
const LATIN_ALLOWED = new Set<string>([
  "GOSTracker", // product name: a proper noun, not translated (NFR-6)
]);
const LATIN = /[A-Za-z]/;

export interface Finding {
  line: number;
  kind: "text" | "attribute" | "literal";
  value: string;
}

function isViolation(value: string): boolean {
  const v = value.trim();
  return LATIN.test(v) && !LATIN_ALLOWED.has(v);
}

function isTechnicalAttr(name: string): boolean {
  return TECHNICAL_ATTRS.has(name) || name.startsWith("data-");
}

export function scanLatinUi(source: string): Finding[] {
  const sf = ts.createSourceFile("scan.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: Finding[] = [];
  const lineAt = (pos: number): number => sf.getLineAndCharacterOfPosition(pos).line + 1;
  const add = (pos: number, kind: Finding["kind"], value: string): void => {
    if (isViolation(value)) found.push({ line: lineAt(pos), kind, value: value.trim() });
  };

  // const NAME = "literal" (any scope; the last declaration of a name wins)
  const consts = new Map<string, ts.StringLiteralLike>();
  const collect = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer !== undefined &&
      ts.isStringLiteralLike(node.initializer) &&
      (ts.getCombinedNodeFlags(node) & ts.NodeFlags.Const) !== 0
    ) {
      consts.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, collect);
  };
  collect(sf);

  // Literals that end up on the screen when `expr` is rendered / passed as a visible value.
  const rendered = (expr: ts.Expression, kind: Finding["kind"]): void => {
    if (ts.isParenthesizedExpression(expr) || ts.isAsExpression(expr) || ts.isNonNullExpression(expr)) {
      rendered(expr.expression, kind);
    } else if (ts.isStringLiteralLike(expr)) {
      add(expr.getStart(sf), kind, expr.text);
    } else if (ts.isTemplateExpression(expr)) {
      // Literal parts of a template are phrases only if they contain whitespace: `${id}-title`
      // is a technical identifier, `Total ${n}` is text.
      const part = (lit: ts.TemplateHead | ts.TemplateMiddle | ts.TemplateTail): void => {
        if (/\s/.test(lit.text)) add(lit.getStart(sf), kind, lit.text);
      };
      part(expr.head);
      for (const span of expr.templateSpans) {
        rendered(span.expression, kind);
        part(span.literal);
      }
    } else if (ts.isConditionalExpression(expr)) {
      rendered(expr.whenTrue, kind);
      rendered(expr.whenFalse, kind);
    } else if (ts.isBinaryExpression(expr)) {
      const op = expr.operatorToken.kind;
      if (
        op === ts.SyntaxKind.AmpersandAmpersandToken ||
        op === ts.SyntaxKind.BarBarToken ||
        op === ts.SyntaxKind.QuestionQuestionToken
      ) {
        rendered(expr.left, kind);
        rendered(expr.right, kind);
      }
    } else if (ts.isIdentifier(expr)) {
      const decl = consts.get(expr.text);
      if (decl !== undefined) add(decl.getStart(sf), kind, decl.text);
    }
  };

  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) {
      add(node.pos, "text", node.text);
    } else if (ts.isJsxExpression(node) && node.expression !== undefined) {
      if (!ts.isJsxAttribute(node.parent)) rendered(node.expression, "literal");
    } else if (ts.isJsxAttribute(node) && node.initializer !== undefined) {
      const name = ts.isIdentifier(node.name) ? node.name.text : node.name.getText(sf);
      if (!isTechnicalAttr(name)) {
        const init = node.initializer;
        if (ts.isStringLiteral(init)) add(init.getStart(sf), "attribute", init.text);
        else if (ts.isJsxExpression(init) && init.expression !== undefined) {
          rendered(init.expression, "attribute");
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found.sort((a, b) => a.line - b.line);
}

describe("scanLatinUi (self-check of the compiler-API scanner)", () => {
  const caught = (code: string): Finding[] => scanLatinUi(code);
  const values = (code: string): string[] => caught(code).map((f) => f.value);

  it("catches a Latin aria-label literal", () => {
    expect(caught('const a = <button aria-label="Close">×</button>;')).toEqual([
      { line: 1, kind: "attribute", value: "Close" },
    ]);
  });

  it("catches a Latin JSX text node", () => {
    expect(caught("const a = <p>Hello</p>;")).toEqual([{ line: 1, kind: "text", value: "Hello" }]);
  });

  it("catches literals in every attribute form", () => {
    for (const code of [
      '<input placeholder="Search" />',
      "<input placeholder={'Search'} />",
      '<input placeholder={"Search"} />',
      "<input placeholder={`Search`} />",
      '<span title="Hint">·</span>',
      '<img alt="Logo" />',
    ]) {
      expect(caught(code).length, code).toBe(1);
    }
  });

  it("catches a custom prop and ternary/&& branches in props", () => {
    expect(values('<ErrorAlert message="Failed" />')).toEqual(["Failed"]);
    expect(values('<Field hint={c ? "Required" : t("a.b")} />')).toEqual(["Required"]);
    expect(values('<Field hint={ok && "Done"} />')).toEqual(["Done"]);
  });

  it("catches a string literal in an expression container and text next to an expression", () => {
    expect(values('<p>{"Hello"}</p>')).toEqual(["Hello"]);
    expect(values("<p>{count} items</p>")).toEqual(["items"]);
    expect(values("<p>Hello {name}</p>")).toEqual(["Hello"]);
  });

  it("catches text with ( ) ; = & | that the regexp scanner skipped", () => {
    expect(values("<p>Total (all) & more</p>")).toEqual(["Total (all) & more"]);
    expect(values("<p>a = b; c | d</p>")).toEqual(["a = b; c | d"]);
  });

  it("catches literals in ternaries, && and template literals", () => {
    expect(values('<p>{c ? "Loading" : t("x")}</p>')).toEqual(["Loading"]);
    expect(values('<p>{ok && "Done"}</p>')).toEqual(["Done"]);
    expect(values('<p>{a || "Empty"}</p>')).toEqual(["Empty"]);
    expect(values("<p>{`Total ${n}`}</p>")).toEqual(["Total"]);
    expect(values("<p>{`${n} rows`}</p>")).toEqual(["rows"]);
    expect(values('<p>{(c ? "A" : "B")}</p>')).toEqual(["A", "B"]);
  });

  it("catches a const string used in JSX, reported at the declaration", () => {
    const code = 'function C() {\n  const MSG = "Failed";\n  return <p>{MSG}</p>;\n}';
    expect(caught(code)).toEqual([{ line: 2, kind: "literal", value: "Failed" }]);
    const attr = 'const LABEL = "Close";\nfunction C() {\n  return <button aria-label={LABEL} />;\n}';
    expect(caught(attr)).toEqual([{ line: 1, kind: "attribute", value: "Close" }]);
  });

  it("reports the line of the offence", () => {
    expect(caught("const a = 1;\nconst b = <p>\n  Hello\n</p>;")[0]?.line).toBe(2);
    expect(caught('const a = (\n  <p>\n    {c ? "Hi" : null}\n  </p>\n);')[0]?.line).toBe(3);
  });

  it("ignores dictionary values and technical attributes", () => {
    for (const code of [
      '<button aria-label={t("common.close")}>{t("common.ok")}</button>',
      '<input type="password" name="login" id="login" autoComplete="off" />',
      '<a href="/admin" className="link" role="button" data-testid="x">{t("a.b")}</a>',
      '<div aria-labelledby="admin-password-title" aria-modal="true" />',
      '<input placeholder={t("a.hint")} title={`${id}-t`} />',
      '<select name="role"><option value="tech_admin">{t("role.tech_admin")}</option></select>',
      "<p>—</p>",
      "<p>{n} / {m}</p>",
      "<span>{label}: {value}</span>",
      '<ErrorAlert message={errorMessage("forbidden")} />',
      "const [a, setA] = useState<Foo | null>(null);\nconst r = useRef<HTMLDivElement>(null);",
      "const f = async (): Promise<void> => {};\nconst g = (x: number) => x > 1 && x < 3;",
      "const c = <Select<Option> />;",
      'const KEY = "tasks";\nconst k = useQuery({ queryKey: [KEY, "list"] });',
    ]) {
      expect(caught(code), code).toEqual([]);
    }
  });

  it("no false positive on comparison with JSX in a branch", () => {
    expect(caught("const a = <div>{a > b ? <hr /> : null}</div>;")).toEqual([]);
    expect(caught("const a = <div>{a < b && <hr />}</div>;")).toEqual([]);
    expect(caught('const a = <div>{items.map((i) => <li key={i.id}>{i.login}</li>)}</div>;')).toEqual([]);
  });

  it("does not look into comments", () => {
    expect(caught('// <p>Hello</p>\n/* <b aria-label="Close"/> */')).toEqual([]);
    expect(caught("<p>{/* Hello */}</p>")).toEqual([]);
  });

  it("allows only the explicit whitelist", () => {
    expect(caught("<h1>GOSTracker</h1>")).toEqual([]);
    expect(caught('<h1>{"GOSTracker"}</h1>')).toEqual([]);
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
