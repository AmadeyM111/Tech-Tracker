// 009/FR-7, AC-12: tech admin banner about stale backups.
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { backupWarning } from "../../../src/features/admin/BackupBanner";
import { CAPS_ALL, installFetch, j, meWith, page, renderApp } from "./helpers";

const ME = "GET /api/v1/me";
const USERS = "GET /api/v1/admin/users";
const AUDIT = "GET /api/v1/admin/audit";
const BACKUP = "GET /api/v1/admin/system/backup";

const OK = {
  last_success_at: "2026-11-08T23:30:00Z",
  last_success_size_bytes: 2048,
  last_run_at: "2026-11-08T23:30:00Z",
  last_run_status: "ok" as const,
  stale: false,
  stale_after_hours: 26,
};

afterEach(() => vi.unstubAllGlobals());

describe("backupWarning", () => {
  it("is null when backups are fresh", () => {
    expect(backupWarning(OK)).toBeNull();
  });
  it("says there are no backups", () => {
    expect(
      backupWarning({ ...OK, stale: true, last_success_at: null, last_run_at: null, last_run_status: null }),
    ).toBe("Резервных копий нет.");
  });
  it("names the age threshold and Moscow time of the last copy", () => {
    expect(backupWarning({ ...OK, stale: true })).toBe(
      "Последняя резервная копия старше 26 часов: 09.11.2026, 02:30.",
    );
  });
  it("prefers the failed last run", () => {
    expect(
      backupWarning({ ...OK, stale: true, last_run_status: "failed", last_run_at: "2026-11-09T23:31:00Z" }),
    ).toBe("Последняя резервная копия не удалась: 10.11.2026, 02:31.");
  });
});

describe("BackupBanner on tech admin screens", () => {
  it("shows the banner on /admin/users when stale", async () => {
    installFetch({
      [ME]: () => j(200, meWith(CAPS_ALL)),
      [USERS]: () => j(200, page([])),
      [BACKUP]: () => j(200, { ...OK, stale: true, last_success_at: null, last_run_status: null, last_run_at: null }),
    });
    renderApp("/admin/users");
    expect(await screen.findByText("Резервных копий нет.")).toBeTruthy();
  });

  it("shows nothing when backups are fresh", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(CAPS_ALL)),
      [USERS]: () => j(200, page([])),
      [BACKUP]: () => j(200, OK),
    });
    const { container } = renderApp("/admin/users");
    await waitFor(() => expect(f.count(BACKUP)).toBe(1));
    expect(container.querySelector('[data-banner="backup"]')).toBeNull();
  });

  it("does not ask for the status without manage_accounts", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(["view_audit"])),
      [AUDIT]: () => j(200, page([])),
    });
    renderApp("/admin/audit");
    await waitFor(() => expect(f.count(AUDIT)).toBe(1));
    expect(f.count(BACKUP)).toBe(0);
  });
});
