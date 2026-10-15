import { describe, expect, it } from "vitest";
import type { UserConfig } from "vite";

import rawConfig from "../../vite.config";

async function resolveConfig(): Promise<UserConfig> {
  const value: unknown = rawConfig;
  if (typeof value === "function") {
    return (await value({ command: "serve", mode: "development" })) as UserConfig;
  }
  return (await value) as UserConfig;
}

describe("vite.config.ts (T21)", () => {
  it("proxies /api to the backend without changing origin", async () => {
    const cfg = await resolveConfig();
    const proxy = cfg.server?.proxy?.["/api"];
    expect(proxy).toBeDefined();
    const opts = typeof proxy === "string" ? { target: proxy } : proxy;
    expect(opts?.target).toBe("http://localhost:8000");
    expect(opts?.changeOrigin ?? false).toBe(false);
    expect(cfg.server?.port).toBe(5173);
  });

  it("configures vitest: jsdom, include, setupFiles", async () => {
    const cfg = (await resolveConfig()) as UserConfig & {
      test?: { include?: string[]; environment?: string; setupFiles?: string | string[] };
    };
    expect(cfg.test?.include).toEqual(["tests/**/*.test.{ts,tsx}"]);
    expect(cfg.test?.environment).toBe("jsdom");
    const setup = ([] as string[]).concat(cfg.test?.setupFiles ?? []);
    expect(setup.some((s) => s.endsWith("tests/setup.ts"))).toBe(true);
  });
});
