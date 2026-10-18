import { describe, expect, it } from "vitest";

import * as router from "../../src/app/router";
import type { MeResponse } from "../../src/features/auth/session";

type Cap = MeResponse["capabilities"][number];
type Profile = Pick<MeResponse, "must_change_password" | "capabilities">;

// Representative capability sets of the roles (spec 003, FR-3; AC-1..AC-3, AC-35, AC-36).
const BA: Cap[] = ["business_access", "project_create", "project_manage_any", "crm_read", "crm_write"];
const U: Cap[] = ["business_access", "project_create"];
const TA: Cap[] = ["manage_accounts", "assign_roles", "view_audit"];
const AUD: Cap[] = ["view_audit"];

function call(capabilities: Cap[], must_change_password = false): string {
  const fn = (router as unknown as { startPath?: (p: Profile) => string }).startPath;
  expect(typeof fn, "router.tsx must export startPath").toBe("function");
  return fn!({ must_change_password, capabilities });
}

describe("003 startPath (FR-3)", () => {
  it.each([
    ["003_ac1_ba_goes_to_projects", BA, "/projects"],
    ["003_ac2_user_goes_to_projects", U, "/projects"],
    ["003_ac3_ta_goes_to_admin_users", TA, "/admin/users"],
    ["003_ac35_aud_goes_to_audit", AUD, "/admin/audit"],
    ["003_ac36_nocap_goes_to_admin_users", [], "/admin/users"],
    ["003_fr3_only_manage_accounts_goes_to_admin_users", ["manage_accounts"], "/admin/users"],
    ["003_fr3_only_business_access_goes_to_projects", ["business_access"], "/projects"],
    ["003_fr3_extra_caps_only_goes_to_admin_users", ["crm_read", "project_manage_any"], "/admin/users"],
  ] as [string, Cap[], string][])("%s", (_name, caps, expected) => {
    expect(call(caps)).toBe(expected);
  });

  it("003_fr3_business_access_beats_manage_accounts_and_audit", () => {
    expect(call(["view_audit", "manage_accounts", "business_access"])).toBe("/projects");
  });

  it("003_fr3_manage_accounts_beats_audit_regardless_of_order", () => {
    expect(call(["view_audit", "manage_accounts"])).toBe("/admin/users");
    expect(call(["manage_accounts", "view_audit"])).toBe("/admin/users");
  });

  it("003_fr3_capability_order_does_not_matter", () => {
    expect(call([...BA].reverse())).toBe("/projects");
    expect(call([...TA].reverse())).toBe("/admin/users");
  });

  it.each([
    ["with_business_access", BA],
    ["with_manage_accounts", TA],
    ["without_capabilities", [] as Cap[]],
  ])("003_fr3_forced_password_change_wins_%s", (_n, caps) => {
    expect(call(caps, true)).toBe("/change-password");
  });
});
