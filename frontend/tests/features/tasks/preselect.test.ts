// 004 / R5-T01: правило предвыбора проекта (FR-12; для AC-20, AC-21, AC-41).
import { describe, expect, it } from "vitest";

import { preselectProject } from "../../../src/features/tasks/CreateTaskForm";

const P1 = { id: "55555555-5555-4555-8555-555555555555", name: "Альфа" };
const P2 = { id: "66666666-6666-4666-8666-666666666666", name: "Бета" };
const P3 = { id: "99999999-0000-4999-8999-999999999993", name: "Гамма" };
const OTHER = "00000000-0000-4000-8000-000000000000";

describe("preselectProject (004 FR-12)", () => {
  it("004_ac20_current_project_in_list_is_selected", () => {
    expect(preselectProject([P1, P3], P3.id)).toBe(P3.id);
    expect(preselectProject([P1], P1.id)).toBe(P1.id);
  });

  it("004_ac20_current_project_not_in_list_with_single_project_selects_single", () => {
    expect(preselectProject([P1], OTHER)).toBe(P1.id);
  });

  it("004_ac21_current_project_not_in_list_with_several_projects_gives_null", () => {
    expect(preselectProject([P1, P3], OTHER)).toBeNull();
  });

  it("004_ac21_no_current_project_with_single_project_selects_single", () => {
    expect(preselectProject([P2], null)).toBe(P2.id);
  });

  it("004_ac21_no_current_project_with_several_projects_gives_null", () => {
    expect(preselectProject([P1, P2, P3], null)).toBeNull();
  });

  it("004_ac41_empty_list_gives_null", () => {
    expect(preselectProject([], null)).toBeNull();
    expect(preselectProject([], OTHER)).toBeNull();
  });
});
