// R6-T04: воспроизведение ошибки п. 6 (вторая и последующие подзадачи не создаются).
// AC: 006/AC-36, AC-37 (FR-26, NFR-5). Тесты падают на текущем коде, если ошибка воспроизводится.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  ALL_PERMS,
  EXECUTOR_PERMS,
  TASK,
  SUB_POST,
  deferred,
  openCard,
  setValue,
  subForm,
  subSection,
  subTitleField,
  subTitlesShown,
  subtaskServer,
  titleInput,
  waitCount,
} from "./taskpage-helpers";

const VALIDATION = errorMessage("validation_error");

/** Нет ни role=alert, ни текста validation_error (и не только в alert). */
function expectNoValidationError() {
  expect(screen.queryAllByRole("alert")).toHaveLength(0);
  expect(document.body.textContent).not.toContain(VALIDATION);
}

/** Enter в поле: фокус в поле, отправка формы (jsdom не отправляет форму по keydown). */
function pressEnter(c: ParentNode) {
  subTitleField(c).focus();
  fireEvent.submit(subForm(c)!);
}

/** Нажатие кнопки «Добавить подзадачу»: фокус на кнопке, затем click. */
function clickAdd(c: ParentNode) {
  const btn = within(subForm(c)!);
  btn.focus();
  fireEvent.click(btn);
}
function within(form: HTMLFormElement): HTMLButtonElement {
  const b = Array.from(form.querySelectorAll("button")).find((x) => x.textContent === ru["tasks.subtask_create_submit"]);
  if (!b) throw new Error("no add button");
  return b;
}

/** После шага: POST ушёл, подзадача в списке, поле пусто и в фокусе, ошибок нет. */
async function expectStepDone(c: ParentNode, posted: string[], titles: string[]) {
  await waitFor(() => expect(subTitlesShown(c)).toEqual(titles));
  expect(posted).toEqual(titles);
  await waitFor(() => expect(subTitleField(c).value).toBe(""));
  await waitFor(() => expect(document.activeElement).toBe(subTitleField(c)));
  expectNoValidationError();
}

type Srv = ReturnType<typeof subtaskServer>;

async function open(srv: Srv, role: "business_admin" | "user" = "user") {
  return openCard(() => ({}), srv.routes, role);
}

/** Вводит название и отправляет выбранным способом. */
function enter(c: ParentNode, name: string, how: "enter" | "button") {
  setValue(subTitleField(c), name);
  if (how === "enter") pressEnter(c);
  else clickAdd(c);
}

describe("subtasks in a row (006/AC-36, AC-37)", () => {
  it("ac36_three_subtasks_in_a_row_enter_button_enter", async () => {
    const srv = subtaskServer(EXECUTOR_PERMS);
    const { container, f } = await open(srv);
    const titles: string[] = [];
    for (const [name, how] of [
      ["Шаг 1", "enter"],
      ["Шаг 2", "button"],
      ["Шаг 3", "enter"],
    ] as const) {
      enter(container, name, how);
      titles.push(name);
      await waitCount(f, SUB_POST, titles.length);
      await expectStepDone(container, srv.posted, titles);
    }
    expect(f.count(SUB_POST)).toBe(3);
    expect(subTitlesShown(container)).toEqual(["Шаг 1", "Шаг 2", "Шаг 3"]);
  });

  it("ac37_poll_tick_between_second_and_third", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const srv = subtaskServer(EXECUTOR_PERMS);
    const { container, f } = await open(srv);
    enter(container, "Шаг 1", "enter");
    await expectStepDone(container, srv.posted, ["Шаг 1"]);
    enter(container, "Шаг 2", "button");
    await expectStepDone(container, srv.posted, ["Шаг 1", "Шаг 2"]);
    const reads = f.count(TASK);
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(TASK)).toBeGreaterThan(reads));
    await waitFor(() => expect(f.last(TASK).headers.get("X-GT-Background")).toBe("1"));
    expectNoValidationError();
    enter(container, "Шаг 3", "enter");
    await expectStepDone(container, srv.posted, ["Шаг 1", "Шаг 2", "Шаг 3"]);
    expect(f.count(SUB_POST)).toBe(3);
  });

  it("ac37_next_title_submitted_before_slow_reread_answers", async () => {
    const srv = subtaskServer(EXECUTOR_PERMS);
    const { container, f } = await open(srv);
    const gate = deferred<null>();
    srv.holdReads(gate.promise);
    try {
      enter(container, "Шаг 1", "enter");
      await waitCount(f, SUB_POST, 1);
      // Перечитывание ещё не ответило; поле уже пустое - пользователь вводит следующее название.
      await waitFor(() => expect(subTitleField(container).value).toBe(""));
      expect(subTitlesShown(container)).toEqual([]);
      enter(container, "Шаг 2", "button");
      // Вторая отправка не должна ждать ответа перечитывания и не должна теряться молча.
      await waitFor(() => expect(srv.posted).toEqual(["Шаг 1", "Шаг 2"]), { timeout: 1500 });
      expectNoValidationError();
    } finally {
      gate.resolve(null);
    }
    await expectStepDone(container, srv.posted, ["Шаг 1", "Шаг 2"]);
    enter(container, "Шаг 3", "enter");
    await expectStepDone(container, srv.posted, ["Шаг 1", "Шаг 2", "Шаг 3"]);
    expect(f.count(SUB_POST)).toBe(3);
  });

  it("ac37_unsaved_task_title_edit_does_not_break_subtasks", async () => {
    const srv = subtaskServer(ALL_PERMS);
    const { container, f } = await open(srv, "business_admin");
    setValue(titleInput(), "Черновик названия");
    const titles: string[] = [];
    for (const [name, how] of [
      ["Шаг 1", "enter"],
      ["Шаг 2", "button"],
      ["Шаг 3", "enter"],
    ] as const) {
      enter(container, name, how);
      titles.push(name);
      await waitCount(f, SUB_POST, titles.length);
      await expectStepDone(container, srv.posted, titles);
      expect(titleInput()!.value).toBe("Черновик названия");
    }
    expect(f.count(SUB_POST)).toBe(3);
    expect(subSection(container)).not.toBeNull();
  });
});
