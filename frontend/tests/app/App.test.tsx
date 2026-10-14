import { useQueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { useNavigate } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import indexHtml from "../../index.html?raw";
import { App } from "../../src/app/App";
import { Providers } from "../../src/app/providers";

const CYRILLIC = /[Ѐ-ӿ]/;

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("App scaffold (T21)", () => {
  it("mounts inside Providers and renders a main landmark", () => {
    render(
      <Providers>
        <App />
      </Providers>,
    );
    expect(screen.getByRole("main")).toBeTruthy();
  });

  it("Providers expose QueryClient and Router", () => {
    let seen: { client: unknown; navigate: unknown } | null = null;
    function Probe() {
      seen = { client: useQueryClient(), navigate: useNavigate() };
      return <p>probe</p>;
    }
    render(
      <Providers>
        <Probe />
      </Providers>,
    );
    expect(seen).not.toBeNull();
    expect(seen!.client).toBeDefined();
    expect(typeof seen!.navigate).toBe("function");
  });

  it("does not call fetch on mount", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <Providers>
        <App />
      </Providers>,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("has no Cyrillic literals in any src/**/*.tsx outside shared/i18n (NFR-6)", () => {
    const files = import.meta.glob("../../src/**/*.tsx", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    const paths = Object.keys(files);
    expect(paths.some((p) => p.endsWith("app/App.tsx"))).toBe(true);
    for (const [path, source] of Object.entries(files)) {
      if (path.includes("/shared/i18n/")) continue;
      expect(CYRILLIC.test(stripComments(source)), path).toBe(false);
    }
  });

  it("index.html has lang=ru and a title", () => {
    expect(indexHtml).toMatch(/<html[^>]*\blang="ru"/);
    expect(indexHtml).toMatch(/<title>[^<]+<\/title>/);
  });
});
