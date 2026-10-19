// T84: подзадачи в карточке задачи.
// AC: UF-4, FR-21 (один уровень), FR-22 (прогресс; null = «нет подзадач»), AC-7, AC-47, NFR-6, NFR-7.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage } from "../../../src/shared/i18n";
import {
  SUB1,
  SUB2,
  SUB3,
  SUB_POST,
  TID3,
  bodyOf,
  card,
  d,
  deferred,
  err,
  f_,
  j,
  openCard,
  setValue,
  sub,
  subForm,
  subSection,
  waitCount,
  EXECUTOR_PERMS,
  ALL_PERMS,
} from "./taskpage-helpers";

const SUBS = [sub(SUB1, "Собрать данные", "done"), sub(SUB2, "Написать текст", "review"), sub(SUB3, "Согласовать", "todo")];
const titleInput = (c: ParentNode) => subForm(c)!.querySelector<HTMLInputElement>('input[name="title"]')!;
const row = (c: ParentNode, id: string) => c.querySelector<HTMLElement>(`[data-subtask-id="${id}"]`)!;

describe("subtask list and progress (UF-4, FR-22, AC-7)", () => {
  it("uf4_rows_show_title_link_status_and_assignee", async () => {
    const subs = [{ ...sub(SUB1, "Собрать данные", "done"), assignee: { id: "x", login: "petrov" } }, ...SUBS.slice(1)];
    const { container } = await openCard(() => card({ subtasks: subs, progress: 33 }));
    const r = row(container, SUB1);
    expect(f_(r, "title")!.querySelector("a")!.getAttribute("href")).toBe(`/tasks/${SUB1}`);
    expect(f_(r, "title")!.textContent).toBe("Собрать данные");
    expect(f_(r, "status")!.textContent).toBe(d("tasks.status.done"));
    expect(f_(r, "assignee")!.textContent).toBe("petrov");
    expect(f_(row(container, SUB3), "assignee")!.textContent).toBe(d("tasks.assignee_none"));
    expect(subSection(container)!.querySelector("h2")!.textContent).toBe(d("tasks.subtasks_title"));
  });

  it("ac7_progress_number_is_shown_as_percent", async () => {
    const { container } = await openCard(() => card({ subtasks: SUBS, progress: 33 }));
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("33%");
  });

  it("ac7_progress_100_is_shown", async () => {
    const all = SUBS.map((s) => ({ ...s, status: "done" }));
    const { container } = await openCard(() => card({ subtasks: all, progress: 100 }));
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("100%");
  });

  it("fr22_null_progress_is_no_subtasks_text_not_zero_percent", async () => {
    const { container } = await openCard(() => card({ subtasks: [], progress: null }));
    const p = f_(subSection(container)!, "progress")!;
    expect(p.textContent).toBe(d("tasks.progress_none"));
    expect(p.textContent).not.toContain("0%");
    expect(container.querySelector('[data-role="empty"]')!.textContent).toBe(d("tasks.subtasks_empty"));
  });

  it("fr22_zero_progress_is_zero_percent_when_subtasks_exist", async () => {
    const { container } = await openCard(() => card({ subtasks: [sub(SUB1, "A", "todo")], progress: 0 }));
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("0%");
  });
});

describe("create subtask (FR-19b, FR-20, FR-21, AC-47)", () => {
  it("fr21_subtask_has_no_create_form_even_with_permission", async () => {
    const { container } = await openCard(() => card({ parent_id: TID3, permissions: ALL_PERMS }));
    expect(subForm(container)).toBeNull();
  });

  it("ac47_no_create_subtask_permission_hides_form", async () => {
    const { container } = await openCard(() => card({ permissions: { ...ALL_PERMS, create_subtask: false } }));
    expect(subForm(container)).toBeNull();
  });

  it("ac47_post_has_trimmed_title_and_no_assignee_key_then_card_is_refetched", async () => {
    let created = false;
    const { container, f } = await openCard(
      () => (created ? card({ subtasks: [sub(SUB1, "Новая подзадача")], progress: 0 }) : card({ permissions: EXECUTOR_PERMS })),
      {
        [SUB_POST]: () => {
          created = true;
          return j(201, card());
        },
      },
      "user",
    );
    const form = subForm(container)!;
    expect(titleInput(container).labels?.length).toBeTruthy();
    setValue(titleInput(container), "  Новая подзадача  ");
    fireEvent.submit(form);
    await waitCount(f, SUB_POST, 1);
    const b = await bodyOf(f.last(SUB_POST));
    expect(b).toEqual({ title: "Новая подзадача" });
    expect("assignee_id" in b).toBe(false);
    await waitFor(() => expect(row(container, SUB1)).toBeTruthy());
    expect(f_(subSection(container)!, "progress")!.textContent).toContain("0%");
    expect(titleInput(container).value).toBe("");
  });

  it("ac47_empty_title_blocks_request_and_shows_validation_alert", async () => {
    const { container, f } = await openCard();
    setValue(titleInput(container), "  ");
    fireEvent.submit(subForm(container)!);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(f.count(SUB_POST)).toBe(0);
  });

  it("ac47_403_other_assignee_shows_alert_and_keeps_input", async () => {
    const { container } = await openCard(() => card(), { [SUB_POST]: () => err(403, "forbidden") });
    setValue(titleInput(container), "Чужая");
    fireEvent.submit(subForm(container)!);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(titleInput(container).value).toBe("Чужая");
  });

  it("nfr6_double_submit_sends_one_post", async () => {
    const gate = deferred<Response>();
    const { container, f } = await openCard(() => card(), { [SUB_POST]: () => gate.promise });
    setValue(titleInput(container), "Однократно");
    const form = subForm(container)!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitCount(f, SUB_POST, 1);
    gate.resolve(j(201, card()));
    await waitFor(() => expect(titleInput(container).value).toBe(""));
    expect(f.count(SUB_POST)).toBe(1);
  });
});
