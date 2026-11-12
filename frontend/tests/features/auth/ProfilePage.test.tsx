// 019 / R8-T19: the profile screen /profile (FR-3c, AC-34). Route and guards come from AppRoutes; texts come from
// the ru dictionary; requests are recorded by the fetch stub of tests/features/admin/helpers.tsx.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { CAPS_ALL, err, installFetch, j, meWith, renderApp, where } from "../admin/helpers";

const ME = "GET /api/v1/me";
const NAME = "PUT /api/v1/me/name";
const ID = "11111111-1111-4111-8111-111111111111";

/** Profile as GET /me returns it (MeResponse with the name fields). */
function profile(over: Record<string, unknown> = {}) {
  return {
    id: ID,
    login: "petrov",
    role: "user",
    must_change_password: false,
    capabilities: ["business_access"],
    first_name: "Анна",
    last_name: "Петрова",
    ...over,
  };
}

const firstNameInput = () => screen.getByLabelText(ru["profile.first_name_label"]) as HTMLInputElement;
const lastNameInput = () => screen.getByLabelText(ru["profile.last_name_label"]) as HTMLInputElement;
const saveButton = () => screen.getByRole("button", { name: ru["profile.save"] });

async function openProfile() {
  const out = renderApp("/profile");
  await screen.findByRole("heading", { level: 1, name: ru["profile.title"] });
  return out;
}

afterEach(() => vi.unstubAllGlobals());

describe("AC-34 profile screen fields", () => {
  it("019_ac34_fields_are_filled_from_get_me_and_login_is_text", async () => {
    installFetch({ [ME]: () => j(200, profile()) });
    await openProfile();
    expect(where()).toBe("/profile");
    expect(firstNameInput().value).toBe("Анна");
    expect(lastNameInput().value).toBe("Петрова");
    // the login is shown as text only: no input carries it
    expect(screen.getByText("petrov")).toBeTruthy();
    expect(screen.queryByDisplayValue("petrov")).toBeNull();
  });
});

describe("AC-34 saving the own name", () => {
  it("019_ac34_save_sends_trimmed_names_shows_status_and_refreshes_me_cache", async () => {
    let body: unknown;
    const f = installFetch({
      [ME]: () => j(200, profile()),
      [NAME]: async (r) => {
        body = await r.json();
        return j(200, profile({ first_name: "Мария", last_name: "Смирнова" }));
      },
    });
    const { qc } = await openProfile();
    fireEvent.change(firstNameInput(), { target: { value: "  Мария " } });
    fireEvent.change(lastNameInput(), { target: { value: "Смирнова" } });
    fireEvent.click(saveButton());
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe(ru["profile.saved"]);
    expect(body).toEqual({ first_name: "Мария", last_name: "Смирнова" });
    expect(f.count(NAME)).toBe(1);
    expect(qc.getQueryData(["auth", "me"])).toMatchObject({ first_name: "Мария", last_name: "Смирнова" });
  });

  // P2 (PR #29 design review): an empty name shows its text under its own field and sends nothing.
  it.each([
    ["first", "   ", "Анна", "profile.first_name_label", "profile.first_name_required"],
    ["last", "Анна", "", "profile.last_name_label", "profile.last_name_required"],
  ] as const)(
    "019_ac34_empty_%s_name_is_under_its_field_and_sends_nothing",
    async (_n, first, last, labelKey, textKey) => {
      const f = installFetch({ [ME]: () => j(200, profile()), [NAME]: () => j(200, profile()) });
      await openProfile();
      fireEvent.change(firstNameInput(), { target: { value: first } });
      fireEvent.change(lastNameInput(), { target: { value: last } });
      fireEvent.click(saveButton());
      const input = screen.getByLabelText(ru[labelKey]) as HTMLInputElement;
      const error = (await screen.findByText(ru[textKey])).closest<HTMLElement>(".ui-field-error");
      expect(error?.getAttribute("role")).toBe("alert");
      expect(input.closest(".ui-field")?.contains(error)).toBe(true);
      expect(input.getAttribute("aria-invalid")).toBe("true");
      expect(f.count(NAME)).toBe(0);
      expect(screen.queryByRole("status")).toBeNull();
    },
  );

  // Server codes of the name fields: the rule text goes under the field it refers to, not into a general block.
  it.each([
    ["first_name_invalid", "profile.first_name_label", "error.first_name_invalid"],
    ["last_name_invalid", "profile.last_name_label", "error.last_name_invalid"],
  ] as const)("019_ac34_422_%s_is_under_its_field_and_no_status", async (code, labelKey, textKey) => {
    installFetch({ [ME]: () => j(200, profile()), [NAME]: () => err(422, code) });
    await openProfile();
    fireEvent.change(firstNameInput(), { target: { value: "Anna 2" } });
    fireEvent.click(saveButton());
    const error = (await screen.findByText(ru[textKey])).closest<HTMLElement>(".ui-field-error");
    const input = screen.getByLabelText(ru[labelKey]) as HTMLInputElement;
    expect(input.closest(".ui-field")?.contains(error)).toBe(true);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert")).toBe(error);
    expect(screen.queryByRole("status")).toBeNull();
    expect(where()).toBe("/profile");
  });
});

describe("AC-34 the profile route for every role", () => {
  it.each([
    ["BA", meWith(["business_access", "project_create", "task_assign_others"], "business_admin")],
    ["U", meWith(["business_access"], "user")],
    ["TA", meWith(CAPS_ALL, "tech_admin")],
    ["without capabilities", meWith([], "user")],
  ])("019_ac34_profile_opens_for_%s", async (_name, me) => {
    installFetch({ [ME]: () => j(200, { ...me, first_name: null, last_name: null }) });
    renderApp("/profile");
    await screen.findByRole("heading", { level: 1, name: ru["profile.title"] });
    expect(where()).toBe("/profile");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText(ru["profile.first_name_label"])).toBeTruthy();
  });

  it("019_ac34_profile_without_role_goes_to_no_role", async () => {
    installFetch({ [ME]: () => err(403, "no_role") });
    renderApp("/profile");
    await waitFor(() => expect(where()).toBe("/no-role"));
  });
});
