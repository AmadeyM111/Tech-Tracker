import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const USE_API_CLIENT = "Use the API client from src/shared/api.";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/shared/api/schema.d.ts"] },
  ...tseslint.configs.strict,
  reactHooks.configs.flat.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/ban-ts-comment": [
        "error",
        {
          "ts-expect-error": "allow-with-description",
          "ts-ignore": true,
          "ts-nocheck": true,
          "ts-check": false,
          minimumDescriptionLength: 10,
        },
      ],
    },
  },
  {
    // All network access goes through src/shared/api (typed client + ApiError middleware).
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/shared/api/**"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: USE_API_CLIENT },
        { name: "XMLHttpRequest", message: USE_API_CLIENT },
        { name: "EventSource", message: USE_API_CLIENT },
      ],
      "no-restricted-properties": [
        "error",
        { object: "self", property: "fetch", message: USE_API_CLIENT },
        { object: "window", property: "fetch", message: USE_API_CLIENT },
        { object: "globalThis", property: "fetch", message: USE_API_CLIENT },
        { object: "navigator", property: "sendBeacon", message: USE_API_CLIENT },
        { object: "window", property: "XMLHttpRequest", message: USE_API_CLIENT },
        { object: "window", property: "EventSource", message: USE_API_CLIENT },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "ImportExpression[source.value=/^axios/]",
          message: USE_API_CLIENT,
        },
        {
          // window.navigator.sendBeacon: no-restricted-properties matches one level only.
          selector:
            "MemberExpression[property.name='sendBeacon'][object.type='MemberExpression'][object.property.name='navigator']",
          message: USE_API_CLIENT,
        },
      ],
      "no-restricted-imports": [
        "error",
        {
          paths: [{ name: "axios", message: USE_API_CLIENT }],
          patterns: [{ group: ["axios/*"], message: USE_API_CLIENT }],
        },
      ],
    },
  },
  {
    // Tests may assert on values narrowed away by closures (non-null assertions).
    files: ["tests/**/*.{ts,tsx}"],
    rules: { "@typescript-eslint/no-non-null-assertion": "off" },
  },
);
