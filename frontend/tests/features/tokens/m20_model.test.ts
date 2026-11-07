// M20 / PN-15: pure helpers of "Доступ для агентов" (status, Moscow time, name check, error text).
import { describe, expect, it } from "vitest";

import { failureMessage, formatMsk, nameProblem, tokenStatus } from "../../../src/features/tokens/model";
import { ApiError } from "../../../src/shared/api/client";
import { errorMessage, ru } from "../../../src/shared/i18n";

describe("tokenStatus (PN-15, AC-3)", () => {
  it("is revoked whenever revoked_at is set", () => {
    expect(tokenStatus({ active: false, revoked_at: "2026-10-20T10:00:00Z" })).toBe("revoked");
    expect(tokenStatus({ active: true, revoked_at: "2026-10-20T10:00:00Z" })).toBe("revoked");
  });

  it("is expired when not active and not revoked", () => {
    expect(tokenStatus({ active: false, revoked_at: null })).toBe("expired");
  });

  it("is active otherwise", () => {
    expect(tokenStatus({ active: true, revoked_at: null })).toBe("active");
  });
});

describe("formatMsk (NFR-5)", () => {
  it("shows Moscow time, not UTC", () => {
    // 09:00 UTC is 12:00 in Europe/Moscow, whatever the test machine's zone is.
    expect(formatMsk("2026-10-13T09:00:00Z")).toMatch(/13\.10\.2026/);
    expect(formatMsk("2026-10-13T09:00:00Z")).toMatch(/12:00/);
  });
});

describe("nameProblem (FR: 1..64 characters)", () => {
  it("requires a name after trimming", () => {
    expect(nameProblem("")).toBe("agent_tokens.name_required");
    expect(nameProblem("   ")).toBe("agent_tokens.name_required");
  });

  it("accepts 64 characters and rejects 65", () => {
    expect(nameProblem("a".repeat(64))).toBeNull();
    expect(nameProblem("a".repeat(65))).toBe("agent_tokens.name_too_long");
  });

  it("counts code points, as the server does", () => {
    // 64 emoji are 128 UTF-16 units but 64 characters.
    expect(nameProblem("\u{1F600}".repeat(64))).toBeNull();
    expect(nameProblem("\u{1F600}".repeat(65))).toBe("agent_tokens.name_too_long");
  });

  it("trims surrounding spaces before counting", () => {
    expect(nameProblem(` ${"a".repeat(64)} `)).toBeNull();
  });
});

describe("failureMessage (no raw codes in the UI)", () => {
  it("maps token_limit_reached to its own dictionary text", () => {
    const text = failureMessage(new ApiError(409, "token_limit_reached", "Достигнут лимит активных токенов"));
    expect(text).toBe(ru["error.token_limit_reached"]);
    expect(text).not.toContain("token_limit_reached");
  });

  it("maps validation_error to the dictionary text", () => {
    expect(failureMessage(new ApiError(422, "validation_error", "bad"))).toBe(errorMessage("validation_error"));
  });

  it("falls back to the unknown-error text for non-API errors", () => {
    expect(failureMessage(new Error("boom"))).toBe(ru["error.unknown"]);
  });
});
