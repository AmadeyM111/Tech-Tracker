import { ru } from "./ru";

export { ru };

/**
 * Minimum password length. Mirrors backend MIN_PASSWORD_LENGTH
 * (backend/app/core/security/passwords.py); the server stays authoritative.
 */
export const PASSWORD_MIN_LENGTH = 12;

export type MessageKey = keyof typeof ru;

const PLACEHOLDER = /\{([a-z_][a-z0-9_]*)\}/g;

/**
 * Returns the dictionary text for `key` with `{name}` placeholders replaced
 * from `params`. An unknown key yields the key itself (never throws).
 */
export function t(key: MessageKey, params?: Record<string, string | number>): string {
  if (!Object.hasOwn(ru, key)) {
    return key;
  }
  const template: string = ru[key];
  if (params === undefined) {
    return template;
  }
  return template.replace(PLACEHOLDER, (match: string, name: string) => {
    const value = Object.hasOwn(params, name) ? params[name] : undefined;
    return value === undefined ? match : String(value);
  });
}

/** User-facing text for an API/client error code; unknown codes -> `error.unknown`. */
export function errorMessage(code: string): string {
  const key = `error.${code}`;
  return Object.hasOwn(ru, key) ? ru[key as MessageKey] : ru["error.unknown"];
}
