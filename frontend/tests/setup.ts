import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Сеть в тестах запрещена: любой неожиданный fetch падает громко.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("network is disabled in tests");
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
