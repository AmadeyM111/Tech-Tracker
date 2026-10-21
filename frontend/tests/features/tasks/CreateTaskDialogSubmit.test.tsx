// 004 / R5-T03: диалог «Новая задача» - отправка, ошибки, повторная отправка, закрытие во время запроса.
// AC: 22, 23, 24, 25, 28, 30, 31 (Escape и «Отмена»), 26 (onCreated с задачей), 6 (CreateTaskForm.test.tsx без правок);
// FR-13..FR-18. Роли: BA - routesBA, U - routesU (spec §5). Переход на карточку и фокус (AC-26 путь) - R5-T05.
//
// 006 / R6-T11, правки по spec 006 §9.2 («Спек 004»); время зафиксировано (freezeDateForFile, 2026-10-19T21:30:00Z):
//   - везде, где раньше вводилось только название, теперь заполняется ещё описание, срок стоит по умолчанию
//     2026-10-20 (AC-22, AC-26, AC-28..AC-31, FR-15: смысл прежний, функция `fill`);
//   - 004/AC-23 (пустое название -> общий validation_error) -> сообщение у поля «Введите название задачи» (006/FR-19);
//   - 004/AC-25 (тело ровно { "title": "Отчёт" }) -> 006/AC-33: название, описание, срок, у БА и исполнитель,
//     без priority;
//   - 004/AC-24 (проект не выбран) - прежний общий errorMessage("validation_error");
//   - 004/AC-28: после ошибки сохраняются и описание/срок, повторная отправка с тем же телом.
//   Новые тесты (AC-32 в диалоге, AC-33 целиком) - блок «006 ...» в конце файла.
import { QueryObserver } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { LIST, listItem } from "../projects/helpers";
import {
  ADMIN_ID,
  BA,
  CREATE_IN,
  ID_KUZNETSOV,
  P1,
  P3,
  TODAY,
  U,
  YESTERDAY,
  freezeDateForFile,
  T_NEW,
  deferred,
  err,
  installFetch,
  j,
  networkFail,
  page,
  readBody,
  renderDialog,
  routesBA,
  routesU,
  exactLabel,
} from "./create-dialog-helpers";

const dialog = () => screen.getByRole("dialog");
const projectSelect = () => within(dialog()).getByLabelText(ru["tasks.project_label"]) as HTMLSelectElement;
const titleInput = () => within(dialog()).getByLabelText(ru["tasks.title_label"]) as HTMLInputElement;
const submitBtn = () =>
  within(dialog()).getByRole("button", { name: ru["tasks.create_submit"] }) as HTMLButtonElement;
const cancelBtn = () => within(dialog()).getByRole("button", { name: ru["admin.cancel"] }) as HTMLButtonElement;
const form = () => dialog().querySelector("form") as HTMLFormElement;
const loaded = () => screen.findByLabelText(ru["tasks.project_label"]);
const posts = (f: { calls: Request[] }) => f.calls.filter((c) => c.method === "POST");
const descInput = () => within(dialog()).getByLabelText(exactLabel(ru["tasks.description_label"])) as HTMLTextAreaElement;
const dueInput = () => within(dialog()).getByLabelText(exactLabel(ru["tasks.due_label"])) as HTMLInputElement;
const type = (v: string) => fireEvent.change(titleInput(), { target: { value: v } });
const typeDescription = (v: string) => fireEvent.change(descInput(), { target: { value: v } });
const DESC = "Собрать данные за квартал";
/** 006: название + описание (срок уже стоит по умолчанию). */
const fill = (title: string, description = DESC) => {
  type(title);
  typeDescription(description);
};
freezeDateForFile(); // 006: Date = 2026-10-19T21:30:00Z для всех тестов файла
const pick = (id: string) => fireEvent.change(projectSelect(), { target: { value: id } });

describe("validation (AC-23, AC-24, FR-13)", () => {
  // Изменено по spec 006 §9.2 (004/AC-23 -> 006/FR-19): вместо общего validation_error - сообщение у поля названия.
  for (const [label, value] of [
    ["empty", ""],
    ["spaces", "   "],
  ] as const) {
    it(`004_ac23_${label}_title_sends_nothing_field_message_instead_of_general_alert`, async () => {
      const f = installFetch(routesU());
      renderDialog({ currentProjectId: P1 });
      await loaded();
      type(value);
      typeDescription(DESC);
      fireEvent.submit(form());
      const alert = await screen.findByRole("alert");
      expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
      expect(alert.textContent).toBe("Введите название задачи");
      expect(screen.queryByText(errorMessage("validation_error"))).toBeNull();
      expect(titleInput().getAttribute("aria-invalid")).toBe("true");
      expect(titleInput().getAttribute("aria-describedby")).toBe(alert.id);
      await waitFor(() => expect(document.activeElement).toBe(titleInput()));
      expect(posts(f)).toHaveLength(0);
      expect(projectSelect().value).toBe(P1);
      expect(descInput().value).toBe(DESC);
      expect(screen.getByRole("dialog")).toBeTruthy();
    });
  }

  it("004_ac24_no_project_sends_nothing_keeps_title", async () => {
    const f = installFetch(routesBA());
    const { onClose, onCreated } = renderDialog({ currentProjectId: null });
    await loaded();
    expect(projectSelect().value).toBe("");
    fill("Отчёт");
    fireEvent.click(submitBtn());
    const alert = await screen.findByRole("alert");
    expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(posts(f)).toHaveLength(0);
    expect(titleInput().value).toBe("Отчёт");
    expect(descInput().value).toBe(DESC);
    expect(onClose).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe("request (AC-22, AC-25, FR-14, FR-15)", () => {
  it("004_ac22_changed_project_gets_the_request", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    expect(projectSelect().value).toBe(P1);
    pick(P3);
    fill("Х");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    expect(f.count(CREATE_IN(P1))).toBe(0);
    expect(posts(f)).toHaveLength(1);
  });

  // Изменено по spec 006 §9.2 (004/AC-25 -> 006/AC-33): тело не только { title }, а название, описание, срок;
  // приоритета и (у «Пользователя») исполнителя в теле нет.
  it("004_ac25_user_body_is_trimmed_title_description_due_without_priority_and_assignee", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: null, session: U });
    await loaded();
    pick(P3);
    fill("  Отчёт  ");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    expect(await readBody(f.last(CREATE_IN(P3)))).toStrictEqual({
      title: "Отчёт",
      description: DESC,
      due_date: TODAY,
    });
    expect(posts(f)).toHaveLength(1);
    expect(f.calls.some((c) => new URL(c.url).pathname.endsWith("/move"))).toBe(false);
  });

  // Изменено по spec 006 §9.2 (004/AC-25, Q-10): у БА в теле теперь assignee_id (по умолчанию он сам).
  it("004_ac25_business_admin_body_has_title_description_due_and_own_assignee_id_no_priority", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    pick(P3);
    fill("  Отчёт  ");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    const body = await readBody(f.last(CREATE_IN(P3)));
    expect(body).toStrictEqual({ title: "Отчёт", description: DESC, due_date: TODAY, assignee_id: ADMIN_ID });
    expect("priority" in body).toBe(false);
    expect(posts(f)).toHaveLength(1);
    expect(f.calls.some((c) => new URL(c.url).pathname.includes("/move"))).toBe(false);
  });

  it("004_ac26_created_task_goes_to_on_created_dialog_not_closed_by_itself", async () => {
    installFetch(routesU());
    const { onCreated, onClose } = renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated).toHaveBeenCalledWith(T_NEW);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_fr15_invalidations_of_three_keys_are_called_before_on_created", async () => {
    installFetch(routesU());
    const { qc, onCreated } = renderDialog({ currentProjectId: P1 });
    let seq = 0;
    const invalidated = new Map<string, number>();
    const orig = qc.invalidateQueries.bind(qc);
    vi.spyOn(qc, "invalidateQueries").mockImplementation(((filters: { queryKey?: unknown }, ...rest: unknown[]) => {
      invalidated.set(JSON.stringify(filters?.queryKey), ++seq);
      return (orig as (...a: unknown[]) => Promise<void>)(filters, ...rest);
    }) as typeof qc.invalidateQueries);
    let createdAt = 0;
    onCreated.mockImplementation(() => {
      createdAt = ++seq;
    });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    for (const key of [["tasks", "project", P1], ["board", P1], ["tasks", "mine"]]) {
      const at = invalidated.get(JSON.stringify(key));
      expect(at, `invalidate ${JSON.stringify(key)}`).toBeDefined();
      expect(at as number).toBeLessThan(createdAt);
    }
  });

  it("004_fr15_on_created_does_not_wait_for_refetch_of_active_board", async () => {
    installFetch(routesU());
    const { qc, onCreated } = renderDialog({ currentProjectId: P1 });
    const gate = deferred<string>();
    let fetches = 0;
    const observer = new QueryObserver(qc, {
      queryKey: ["board", P1],
      queryFn: () => (++fetches === 1 ? Promise.resolve("first") : gate.promise),
      retry: false,
    });
    const unsubscribe = observer.subscribe(() => undefined);
    try {
      await waitFor(() => expect(fetches).toBe(1));
      await loaded();
      fill("Отчёт");
      fireEvent.submit(form());
      // перезапрос Доски стартовал и висит; onCreated не должен ждать его завершения
      await waitFor(() => expect(fetches).toBe(2));
      await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1), { timeout: 800 });
      expect(onCreated).toHaveBeenCalledWith(T_NEW);
      expect(cancelBtn().disabled).toBe(false);
      expect(submitBtn().getAttribute("aria-busy")).toBeNull();
    } finally {
      gate.resolve("second");
      unsubscribe();
    }
  });

  it("004_fr15_on_created_throwing_shows_no_create_error_and_no_second_post", async () => {
    const f = installFetch(routesU());
    const { onCreated } = renderDialog({ currentProjectId: P1 });
    onCreated.mockImplementation(() => {
      throw new Error("navigation failed");
    });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 50));
    // задача уже создана: сообщения «ошибка создания» нет
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    // повторная отправка не создаёт дубликат
    fireEvent.submit(form());
    await new Promise((r) => setTimeout(r, 50));
    expect(f.count(CREATE_IN(P1))).toBe(1);
    expect(posts(f)).toHaveLength(1);
  });

  it("004_fr15_invalidation_targets_the_chosen_project_not_the_page_project", async () => {
    installFetch(routesU());
    const { qc, onCreated } = renderDialog({ currentProjectId: P1 });
    const spy = vi.spyOn(qc, "invalidateQueries");
    await loaded();
    pick(P3);
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    const keys = spy.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey?: unknown })?.queryKey));
    expect(keys).toContain(JSON.stringify(["tasks", "project", P3]));
    expect(keys).toContain(JSON.stringify(["board", P3]));
    expect(keys).not.toContain(JSON.stringify(["tasks", "project", P1]));
  });
});

describe("create errors (AC-28, FR-16)", () => {
  const cases: [string, string, () => Response][] = [
    ["403", "forbidden", () => err(403, "forbidden")],
    ["404", "not_found", () => err(404, "not_found")],
    ["422", "validation_error", () => err(422, "validation_error")],
    ["503", "service_busy", () => err(503, "service_busy")],
    ["network", "network_error", networkFail],
  ];
  for (const [label, code, make] of cases) {
    it(`004_ac28_${label}_one_alert_input_kept_retry_sends_second_request`, async () => {
      const f = installFetch(routesU({ [CREATE_IN(P3)]: make }));
      const { onClose, onCreated } = renderDialog({ currentProjectId: null });
      await loaded();
      pick(P3);
      fill("Отчёт");
      fireEvent.submit(form());
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toBe(errorMessage(code));
      expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
      expect(f.count(CREATE_IN(P3))).toBe(1);
      expect(screen.getByRole("dialog")).toBeTruthy();
      expect(projectSelect().value).toBe(P3);
      expect(titleInput().value).toBe("Отчёт");
      expect(descInput().value).toBe(DESC);
      expect(dueInput().value).toBe(TODAY);
      expect(onCreated).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      // busy снят: повторная отправка уходит
      await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
      fireEvent.submit(form());
      await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(2));
      await waitFor(() => expect(within(dialog()).getAllByRole("alert")).toHaveLength(1));
      expect(onCreated).not.toHaveBeenCalled();
    });
  }

  it("004_ac28_retry_after_error_can_succeed", async () => {
    let n = 0;
    const f = installFetch(
      routesU({ [CREATE_IN(P1)]: () => (++n === 1 ? err(503, "service_busy") : j(201, T_NEW)) }),
    );
    const { onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await screen.findByRole("alert");
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
    expect(f.count(CREATE_IN(P1))).toBe(2);
  });

  it("004_ac28_new_attempt_clears_previous_error_alert", async () => {
    const gate = deferred<Response>();
    let n = 0;
    installFetch(routesU({ [CREATE_IN(P1)]: () => (++n === 1 ? err(503, "service_busy") : gate.promise) }));
    renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await screen.findByRole("alert");
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
    fireEvent.submit(form());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    expect(within(dialog()).queryByRole("alert")).toBeNull();
    gate.resolve(j(201, T_NEW));
  });
});

describe("double submit (AC-30, FR-17)", () => {
  it("004_ac30_two_submits_and_click_send_one_request_aria_busy_until_response", async () => {
    const gate = deferred<Response>();
    const f = installFetch(routesU({ [CREATE_IN(P1)]: () => gate.promise }));
    const { onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    expect(submitBtn().getAttribute("aria-busy")).not.toBe("true");
    fireEvent.submit(form());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    expect(submitBtn().disabled).toBe(false);
    fireEvent.submit(form());
    fireEvent.click(submitBtn());
    expect(f.count(CREATE_IN(P1))).toBe(1);
    gate.resolve(j(201, T_NEW));
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBeNull());
    expect(f.count(CREATE_IN(P1))).toBe(1);
  });
});

describe("close during request (AC-31, FR-18)", () => {
  it("004_ac31_escape_during_request_keeps_dialog_then_created", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [CREATE_IN(P1)]: () => gate.promise }));
    const { onClose, onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    fireEvent.keyDown(titleInput(), { key: "Escape" });
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    gate.resolve(j(201, T_NEW));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_ac31_cancel_is_disabled_during_request_and_click_does_not_close", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [CREATE_IN(P1)]: () => gate.promise }));
    const { onClose, onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    expect(cancelBtn().disabled).toBe(false);
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(cancelBtn().disabled).toBe(true));
    fireEvent.click(cancelBtn());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    gate.resolve(j(201, T_NEW));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_ac31_escape_and_cancel_work_again_after_error", async () => {
    installFetch(routesU({ [CREATE_IN(P1)]: () => err(503, "service_busy") }));
    const { onClose } = renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    await screen.findByRole("alert");
    await waitFor(() => expect(cancelBtn().disabled).toBe(false));
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(cancelBtn());
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("loading: early exit of the handler (AC-18, R5-T02 remainder)", () => {
  it("004_ac18_submit_while_list_loads_exits_early_even_if_disabled_removed_via_dom", async () => {
    const gate = deferred<Response>();
    const f = installFetch(routesU({ [LIST]: () => gate.promise }));
    renderDialog({ currentProjectId: P1 });
    await screen.findByRole("status");
    type("Отчёт"); // во время загрузки есть только название; описание заполняется после появления списка
    // Снимаем disabled через DOM: защита должна быть и в обработчике, а не только в атрибуте.
    submitBtn().removeAttribute("disabled");
    expect(submitBtn().disabled).toBe(false);
    fireEvent.click(submitBtn());
    fireEvent.submit(form());
    expect(posts(f)).toHaveLength(0);
    expect(within(dialog()).queryByRole("alert")).toBeNull(); // выход без сообщения
    expect(titleInput().value).toBe("Отчёт");
    // после загрузки списка та же форма работает: ранний выход не «ломает» отправку
    gate.resolve(j(200, page([listItem(P1, "Альфа")], 1, false, 100)));
    await loaded();
    expect(projectSelect().value).toBe(P1);
    expect(titleInput().value).toBe("Отчёт");
    typeDescription(DESC); // 006: описание обязательно
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P1))).toBe(1));
  });
});

// ---------------------------------------------------------------------------------------------
// 006 R6-T11: AC-32 (диалог), AC-33 целиком, FR-19..FR-21, FR-25.
// ---------------------------------------------------------------------------------------------
const MSG = {
  title: "Введите название задачи",
  description: "Введите описание задачи",
  due: "Укажите срок",
  past: "Срок не может быть раньше сегодняшнего дня",
  assignee: "Выберите исполнителя",
};
const ASSIGNEE_NAME = ru["tasks.assignee_label"];
const assigneePicker = () => within(dialog()).getByRole("combobox", { name: ASSIGNEE_NAME }) as HTMLInputElement;
const selectedLine = () => dialog().querySelector<HTMLElement>('[data-field="selected-assignee"]');
const alertTexts = () => within(dialog()).queryAllByRole("alert").map((a) => a.textContent);
function describedText(el: HTMLElement): string | null {
  const ids = (el.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
  return ids.length === 0 ? null : ids.map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
}
async function pickKuznetsov() {
  fireEvent.change(assigneePicker(), { target: { value: "kuz" } });
  fireEvent.click((await within(await screen.findByRole("listbox")).findAllByRole("option"))[0]!);
  await waitFor(() => expect(selectedLine()!.textContent).toBe("kuznetsov"));
}

describe("006 AC-33: validation before sending (FR-19)", () => {
  it("006_ac33_empty_description_sends_nothing_message_linked_focus_on_description", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    expect(await screen.findByText(MSG.description)).toBeTruthy();
    expect(posts(f)).toHaveLength(0);
    expect(descInput().getAttribute("aria-invalid")).toBe("true");
    expect(describedText(descInput())).toBe(MSG.description);
    await waitFor(() => expect(document.activeElement).toBe(descInput()));
    expect(alertTexts()).toEqual([MSG.description]); // общего validation_error нет
    expect(titleInput().getAttribute("aria-invalid")).toBeNull();
    expect(dueInput().getAttribute("aria-invalid")).toBeNull();
  });

  it("006_ac33_whitespace_description_is_empty", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт", " \n\t ");
    fireEvent.submit(form());
    expect(await screen.findByText(MSG.description)).toBeTruthy();
    expect(posts(f)).toHaveLength(0);
  });

  it("006_ac33_empty_title_and_description_two_messages_focus_on_title", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    fireEvent.submit(form());
    expect(await screen.findByText(MSG.title)).toBeTruthy();
    expect(screen.getByText(MSG.description)).toBeTruthy();
    expect(alertTexts().sort()).toEqual([MSG.description, MSG.title].sort());
    await waitFor(() => expect(document.activeElement).toBe(titleInput()));
    expect(posts(f)).toHaveLength(0);
  });

  it("006_ac33_cleared_due_date_message_due_required_focus_on_due", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.change(dueInput(), { target: { value: "" } });
    fireEvent.submit(form());
    expect(await screen.findByText(MSG.due)).toBeTruthy();
    expect(dueInput().getAttribute("aria-invalid")).toBe("true");
    expect(describedText(dueInput())).toBe(MSG.due);
    await waitFor(() => expect(document.activeElement).toBe(dueInput()));
    expect(alertTexts()).toEqual([MSG.due]);
    expect(posts(f)).toHaveLength(0);
  });

  it("006_ac33_yesterday_msk_is_past_today_is_accepted", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    fill("Отчёт");
    fireEvent.change(dueInput(), { target: { value: YESTERDAY } });
    fireEvent.submit(form());
    expect(await screen.findByText(MSG.past)).toBeTruthy();
    expect(describedText(dueInput())).toBe(MSG.past);
    expect(alertTexts()).toEqual([MSG.past]);
    expect(posts(f)).toHaveLength(0);
    fireEvent.change(dueInput(), { target: { value: TODAY } });
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P1))).toBe(1));
    expect((await readBody(f.last(CREATE_IN(P1)))).due_date).toBe(TODAY);
  });

  it("006_ac33_cleared_assignee_message_choose_assignee_focus_on_picker_no_request", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    fill("Отчёт");
    fireEvent.click(dialog().querySelector('button[data-action="clear-assignee"]')!);
    await waitFor(() => expect(selectedLine()).toBeNull());
    fireEvent.submit(form());
    expect(await screen.findByText(MSG.assignee)).toBeTruthy();
    expect(assigneePicker().getAttribute("aria-invalid")).toBe("true");
    expect(describedText(assigneePicker())).toBe(MSG.assignee);
    await waitFor(() => expect(document.activeElement).toBe(assigneePicker()));
    expect(posts(f)).toHaveLength(0);
  });

  it("006_ac33_no_project_still_uses_general_validation_error_not_a_field_message", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: null });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
    expect(posts(f)).toHaveLength(0);
  });
});

describe("006 AC-33: request body and assignee", () => {
  it("006_ac33_ba_picks_kuznetsov_exactly_one_request_with_title_description_due_assignee_no_priority", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    await pickKuznetsov();
    fill("  Отчёт  ", "Собрать данные");
    fireEvent.change(dueInput(), { target: { value: "2026-12-31" } });
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P1))).toBe(1));
    expect(posts(f)).toHaveLength(1);
    const body = await readBody(f.last(CREATE_IN(P1)));
    expect(body).toStrictEqual({
      title: "Отчёт",
      description: "Собрать данные",
      due_date: "2026-12-31",
      assignee_id: ID_KUZNETSOV,
    });
    expect("priority" in body).toBe(false);
  });

  it("006_ac33_user_has_no_assignee_key_and_created_task_goes_to_on_created_with_assignee_u", async () => {
    const created = { ...T_NEW, assignee: { id: U.currentUser.id, login: U.currentUser.login } };
    const f = installFetch(routesU({ [CREATE_IN(P1)]: () => j(201, created) }));
    const { onCreated } = renderDialog({ currentProjectId: P1, session: U });
    await loaded();
    expect(dialog().querySelector('[data-field="fixed-assignee"]')!.textContent).toBe("Исполнитель: ivanov");
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    const body = await readBody(f.last(CREATE_IN(P1)));
    expect(body).toStrictEqual({ title: "Отчёт", description: DESC, due_date: TODAY });
    expect("assignee_id" in body).toBe(false);
    expect("priority" in body).toBe(false);
    expect(onCreated).toHaveBeenCalledWith(created);
    expect((onCreated.mock.calls[0]![0] as { assignee: { login: string } }).assignee.login).toBe("ivanov");
  });

  it("006_ac33_project_change_after_choosing_assignee_sends_own_id_for_new_project", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    await pickKuznetsov();
    pick(P3);
    await waitFor(() => expect(selectedLine()!.textContent).toBe("admin"));
    fill("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    expect((await readBody(f.last(CREATE_IN(P3)))).assignee_id).toBe(ADMIN_ID);
  });
});

describe("006 AC-32: due_date_in_past from the server (FR-21), in the dialog", () => {
  it("006_ac32_422_due_date_in_past_message_at_due_field_values_kept_resubmit_sends_new_request", async () => {
    let n = 0;
    const f = installFetch(
      routesBA({ [CREATE_IN(P1)]: () => (n++ === 0 ? err(422, "due_date_in_past") : j(201, T_NEW)) }),
    );
    const { onClose, onCreated } = renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    await pickKuznetsov();
    fill("Отчёт", "Собрать данные");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P1))).toBe(1));
    expect(await screen.findByText(MSG.past)).toBeTruthy();
    expect(dueInput().getAttribute("aria-invalid")).toBe("true");
    expect(describedText(dueInput())).toBe(MSG.past);
    // единственное сообщение - у поля срока, общего alert нет
    expect(alertTexts()).toEqual([MSG.past]);
    expect(screen.queryByText(errorMessage("validation_error"))).toBeNull();
    // всё введённое сохранено, окно открыто
    expect(titleInput().value).toBe("Отчёт");
    expect(descInput().value).toBe("Собрать данные");
    expect(dueInput().value).toBe(TODAY);
    expect(projectSelect().value).toBe(P1);
    expect(selectedLine()!.textContent).toBe("kuznetsov");
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // после смены срока повторная отправка уходит новым запросом с новым сроком
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
    fireEvent.change(dueInput(), { target: { value: "2026-10-21" } });
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P1))).toBe(2));
    const body = await readBody(f.last(CREATE_IN(P1)));
    expect(body.due_date).toBe("2026-10-21");
    expect(body.assignee_id).toBe(ID_KUZNETSOV);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
  });

  it("006_ac32_other_server_errors_stay_in_the_common_alert_not_at_the_due_field", async () => {
    installFetch(routesU({ [CREATE_IN(P1)]: () => err(403, "forbidden") }));
    renderDialog({ currentProjectId: P1, session: U });
    await loaded();
    fill("Отчёт");
    fireEvent.submit(form());
    expect((await screen.findByRole("alert")).textContent).toBe(errorMessage("forbidden"));
    expect(dueInput().getAttribute("aria-invalid")).toBeNull();
  });
});
