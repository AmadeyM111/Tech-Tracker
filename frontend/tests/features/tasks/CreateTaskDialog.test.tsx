// 004 / R5-T02: диалог «Новая задача» - состав, список проектов, предвыбор, фокус, клавиатура.
// AC: 14 (кроме "вне nav" в меню), 15, 16, 17, 18, 19 (окно), 20, 21, 41, 32, 33, 34; FR-8..12, FR-19, FR-20.
// Отправка (AC-22 и далее) - R5-T03. Роли: BA - routesBA, U - routesU (spec §5).
//
// 006 / R6-T11 (spec 006 §9.2 «Спек 004»): диалог получает currentUser/canPickAssignee; в нём появились
// «Описание задачи», «Срок выполнения», у БА - «Исполнитель». Соответствие правок старых тестов:
//   004/AC-14 («полей описания, срока, исполнителя нет») -> 006/AC-33 (поля есть, приоритета нет);
//   004/AC-33 (Tab по кругу, 004-нумерация) - в круг входят описание и срок (DIALOG_FOCUSABLE + textarea);
//   остальные тесты: смысл прежний, сессия BA/U передаётся пропсами. Время зафиксировано (freezeDateForFile):
//   срок по умолчанию 2026-10-20 не зависит от реальной даты. Новые тесты - блок «006 ...» в конце файла.
import { QueryClient } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { LIST, listItem } from "../projects/helpers";
import {
  BA,
  CARD,
  LIST_BA,
  MEMBERS_OF,
  TODAY,
  U,
  freezeDateForFile,
  LIST_ONE,
  P1,
  P2,
  P3,
  deferred,
  dialogRoutes,
  err,
  installFetch,
  j,
  page,
  projectCard,
  renderDialog,
  routesBA,
  routesTwoPages,
  routesU,
  exactLabel,
} from "./create-dialog-helpers";

const dialog = () => screen.getByRole("dialog");
const projectSelect = () =>
  within(dialog()).getByLabelText(
    ru["tasks.project_label"],
  ) as HTMLSelectElement;
const titleInput = () =>
  within(dialog()).getByLabelText(ru["tasks.title_label"]) as HTMLInputElement;
const optionTexts = (s: HTMLSelectElement) =>
  Array.from(s.options).map((o) => o.textContent);
const loaded = () => screen.findByLabelText(ru["tasks.project_label"]);
const posts = (f: { calls: Request[] }) =>
  f.calls.filter((c) => c.method === "POST");
const emptyList = () => j(200, page([], 1, false, 100));
const newQc = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } });

freezeDateForFile(); // 006: все тесты файла идут при Date = 2026-10-19T21:30:00Z

// 006: DIALOG_FOCUSABLE дополнен textarea (описание) - иначе Tab выпадает из окна.
const FOCUSABLE = 'input, select, textarea, button, [tabindex]:not([tabindex="-1"])';
const focusables = (root: HTMLElement) =>
  Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (e) => !(e as HTMLButtonElement).disabled,
  );

/** Нажатие Tab как в браузере: если обработчик не отменил событие, фокус идёт к соседу. */
function press(shift: boolean) {
  const els = focusables(dialog());
  const active = document.activeElement as HTMLElement;
  const proceed = fireEvent.keyDown(active, { key: "Tab", shiftKey: shift });
  if (proceed) {
    const i = els.indexOf(active);
    const next = shift ? els[i - 1] : els[i + 1];
    (next ?? document.body).focus();
  }
}

const network = (): Response => {
  throw new TypeError("Failed to fetch");
};

describe("dictionary keys of the dialog (R5-T02)", () => {
  it("004_fr8_new_strings_are_in_dictionary", () => {
    expect(ru["tasks.project_label"]).toBe("Проект");
    expect(ru["tasks.project_placeholder"]).toBe("Выберите проект");
    expect(ru["tasks.no_creatable_projects"]).toBe(
      "Нет проектов, в которых вы можете создавать задачи",
    );
    expect(ru["tasks.dialog_close"]).toBe("Закрыть");
  });
});

describe("dialog composition (AC-14, FR-8, FR-19)", () => {
  it("004_ac14_one_modal_dialog_named_by_heading_outside_nav", async () => {
    installFetch(routesU());
    const { container } = renderDialog();
    await loaded();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    const d = dialog();
    expect(d.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("dialog", { name: ru["tasks.create_title"] })).toBe(
      d,
    );
    expect(d.closest("nav")).toBeNull();
    expect(container.querySelector("nav")).toBeNull();
  });

  it("004_ac14_fields_and_buttons_by_labels", async () => {
    installFetch(routesU());
    renderDialog();
    await loaded();
    const d = dialog();
    expect(projectSelect().tagName).toBe("SELECT");
    expect(titleInput().type).toBe("text");
    expect(
      within(d)
        .getByRole("button", { name: ru["tasks.create_submit"] })
        .getAttribute("type"),
    ).toBe("submit");
    expect(
      within(d)
        .getByRole("button", { name: ru["admin.cancel"] })
        .getAttribute("type"),
    ).toBe("button");
  });

  // Изменено по spec 006 §9.2 (004/AC-14 -> 006/AC-33): раньше "полей описания, срока, исполнителя нет".
  // Теперь они есть; поля приоритета по-прежнему нет.
  it("004_ac14_006_ac33_user_has_description_due_fixed_assignee_and_no_priority", async () => {
    installFetch(routesU());
    renderDialog({ session: U });
    await loaded();
    const d = dialog();
    expect(within(d).getByLabelText(exactLabel(ru["tasks.description_label"])).tagName).toBe("TEXTAREA");
    const due = within(d).getByLabelText(exactLabel(ru["tasks.due_label"])) as HTMLInputElement;
    expect(due.type).toBe("date");
    expect(d.querySelector('[name="priority"]')).toBeNull();
    expect(within(d).queryByLabelText(ru["tasks.priority_label"])).toBeNull();
    expect(within(d).queryByRole("combobox", { name: ru["tasks.assignee_label"] })).toBeNull();
    expect(within(d).getAllByRole("combobox")).toHaveLength(1); // только выбор проекта
    expect(d.querySelector('[name="assignee_id"]')).toBeNull();
    expect(d.querySelector('[data-field="fixed-assignee"]')!.textContent).toBe("Исполнитель: ivanov");
    expect(d.querySelectorAll("input,select,textarea")).toHaveLength(4); // проект, название, описание, срок
  });

  it("004_ac14_006_ac33_business_admin_has_assignee_picker_and_no_priority", async () => {
    installFetch(routesBA());
    renderDialog({ session: BA });
    await loaded();
    const d = dialog();
    expect(within(d).getByRole("combobox", { name: ru["tasks.assignee_label"] })).toBeTruthy();
    expect(within(d).getAllByRole("combobox")).toHaveLength(2); // проект и исполнитель
    expect(d.querySelector('[name="priority"]')).toBeNull();
    expect(within(d).queryByLabelText(ru["tasks.priority_label"])).toBeNull();
    expect(d.querySelector('[data-field="fixed-assignee"]')).toBeNull();
  });
});

describe("project list (AC-15..AC-17, FR-9)", () => {
  it("004_ac15_user_sees_alpha_gamma_with_placeholder", async () => {
    installFetch(routesU());
    renderDialog();
    await loaded();
    expect(optionTexts(projectSelect())).toEqual([
      ru["tasks.project_placeholder"],
      "Альфа",
      "Гамма",
    ]);
    expect(Array.from(projectSelect().options).map((o) => o.value)).toEqual([
      "",
      P1,
      P3,
    ]);
  });

  it("004_ac16_business_admin_sees_only_projects_with_create_task", async () => {
    installFetch(routesBA());
    renderDialog({ session: BA });
    await loaded();
    expect(optionTexts(projectSelect())).toEqual([
      ru["tasks.project_placeholder"],
      "Альфа",
      "Гамма",
    ]);
    expect(screen.queryByRole("option", { name: "Бета" })).toBeNull();
  });

  it("004_ac17_projects_of_both_pages_in_server_order", async () => {
    const f = installFetch(routesTwoPages());
    renderDialog();
    await loaded();
    expect(optionTexts(projectSelect())).toEqual([
      ru["tasks.project_placeholder"],
      "Гамма",
      "Альфа",
    ]);
    const lists = f.calls.filter(
      (c) => `${c.method} ${new URL(c.url).pathname}` === LIST,
    );
    expect(lists.map((c) => f.query(c).get("page"))).toEqual(["1", "2"]);
  });
});

describe("loading and errors (AC-18, FR-10)", () => {
  it("004_ac18_loading_shows_status_and_submit_sends_nothing", async () => {
    const gate = deferred<Response>();
    const f = installFetch(routesU({ [LIST]: () => gate.promise }));
    renderDialog();
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe(ru["admin.loading"]);
    expect(
      within(dialog()).queryByLabelText(ru["tasks.project_label"]),
    ).toBeNull();
    fireEvent.change(titleInput(), { target: { value: "Отчёт" } });
    fireEvent.submit(dialog().querySelector("form")!);
    const submit = within(dialog()).getByRole("button", {
      name: ru["tasks.create_submit"],
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(posts(f)).toHaveLength(0);
    gate.resolve(emptyList());
  });

  const cases: [string, string, () => Response][] = [
    ["500", "internal_error", () => err(500, "internal_error")],
    ["503", "service_busy", () => err(503, "service_busy")],
    ["network", "network_error", network],
  ];

  for (const [label, code, make] of cases) {
    it(`004_ac18_list_${label}_shows_one_alert_and_no_create`, async () => {
      const f = installFetch(routesU({ [LIST]: make }));
      renderDialog();
      const alert = await screen.findByRole("alert");
      expect(screen.getAllByRole("alert")).toHaveLength(1);
      expect(dialog().contains(alert)).toBe(true);
      expect(alert.textContent).toBe(errorMessage(code));
      expect(posts(f)).toHaveLength(0);
      expect(
        within(dialog()).queryByLabelText(ru["tasks.project_label"]),
      ).toBeNull();
      expect(
        within(dialog()).getByRole("button", { name: ru["admin.cancel"] }),
      ).toBeTruthy();
    });

    it(`004_ac18_card_${label}_shows_one_alert_without_partial_list`, async () => {
      const f = installFetch(routesBA({ [CARD(P3)]: make }));
      renderDialog({ session: BA });
      const alert = await screen.findByRole("alert");
      expect(screen.getAllByRole("alert")).toHaveLength(1);
      expect(alert.textContent).toBe(errorMessage(code));
      expect(posts(f)).toHaveLength(0);
      expect(
        within(dialog()).queryByLabelText(ru["tasks.project_label"]),
      ).toBeNull();
    });
  }

  it("004_ac18_error_state_can_be_closed_by_cancel", async () => {
    installFetch(routesU({ [LIST]: () => err(500, "internal_error") }));
    const { onClose } = renderDialog();
    await screen.findByRole("alert");
    fireEvent.click(
      within(dialog()).getByRole("button", { name: ru["admin.cancel"] }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("004_ac18_remount_requests_list_again", async () => {
    const f = installFetch(routesU());
    const qc = newQc();
    const first = renderDialog({ qc });
    await loaded();
    expect(f.count(LIST)).toBe(1);
    first.unmount();
    renderDialog({ qc });
    await loaded();
    expect(f.count(LIST)).toBe(2);
    expect(f.count(CARD(P1))).toBe(2);
  });

  it("004_ac18_remount_after_error_requests_list_again_and_drops_old_error", async () => {
    let fail = true;
    const f = installFetch(
      routesU({
        [LIST]: () => (fail ? err(500, "internal_error") : emptyList()),
      }),
    );
    const qc = newQc();
    const first = renderDialog({ qc });
    await screen.findByRole("alert");
    first.unmount();
    fail = false;
    renderDialog({ qc });
    await screen.findByText(ru["tasks.no_creatable_projects"]);
    expect(f.count(LIST)).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("no creatable projects (AC-19, FR-11)", () => {
  async function expectEmptyState(
    f: { calls: Request[] },
    onClose: () => void,
  ) {
    const d = dialog();
    expect(within(d).getByText(ru["tasks.no_creatable_projects"])).toBeTruthy();
    expect(within(d).queryByLabelText(ru["tasks.title_label"])).toBeNull();
    expect(
      within(d).queryByRole("button", { name: ru["tasks.create_submit"] }),
    ).toBeNull();
    expect(d.querySelector("input,select,textarea")).toBeNull();
    const close = within(d).getByRole("button", {
      name: ru["tasks.dialog_close"],
    });
    expect(close.getAttribute("type")).toBe("button");
    await waitFor(() => expect(document.activeElement).toBe(close));
    fireEvent.keyDown(close, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(posts(f)).toHaveLength(0);
  }

  it("004_ac19_user_with_empty_list", async () => {
    const f = installFetch(routesU({ [LIST]: emptyList }));
    const { onClose } = renderDialog();
    await screen.findByText(ru["tasks.no_creatable_projects"]);
    await expectEmptyState(f, onClose);
  });

  it("004_ac19_business_admin_with_all_create_task_false", async () => {
    const f = installFetch(
      dialogRoutes(LIST_BA, { [P1]: false, [P2]: false, [P3]: false }),
    );
    const { onClose } = renderDialog();
    await screen.findByText(ru["tasks.no_creatable_projects"]);
    await expectEmptyState(f, onClose);
  });

  it("004_ac19_close_button_calls_on_close", async () => {
    installFetch(routesU({ [LIST]: emptyList }));
    const { onClose } = renderDialog();
    await screen.findByText(ru["tasks.no_creatable_projects"]);
    fireEvent.click(
      within(dialog()).getByRole("button", { name: ru["tasks.dialog_close"] }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("preselect and initial focus (AC-20, AC-21, AC-41, FR-12, FR-20)", () => {
  it("004_ac20_current_project_available_is_selected_and_title_focused", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    expect(projectSelect().value).toBe(P1);
    await waitFor(() => expect(document.activeElement).toBe(titleInput()));
  });

  it("004_ac20_current_project_unavailable_nothing_selected_project_focused", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P2, session: BA });
    await loaded();
    expect(projectSelect().value).toBe("");
    expect(screen.queryByRole("option", { name: "Бета" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(projectSelect()));
  });

  it("004_ac21_no_current_project_nothing_selected_project_focused", async () => {
    installFetch(routesU());
    renderDialog({ currentProjectId: null });
    await loaded();
    expect(projectSelect().value).toBe("");
    expect(titleInput().value).toBe("");
    await waitFor(() => expect(document.activeElement).toBe(projectSelect()));
  });

  it("004_ac41_single_available_project_selected_and_title_focused", async () => {
    installFetch(dialogRoutes(LIST_ONE));
    renderDialog({ currentProjectId: null });
    await loaded();
    expect(projectSelect().value).toBe(P1);
    await waitFor(() => expect(document.activeElement).toBe(titleInput()));
  });

  it("004_ac41_single_available_selected_when_current_project_unavailable", async () => {
    installFetch(
      routesBA({ [CARD(P3)]: () => j(200, projectCard(P3, "Гамма", false)) }),
    );
    renderDialog({ currentProjectId: P2, session: BA });
    await loaded();
    expect(projectSelect().value).toBe(P1);
    expect(optionTexts(projectSelect())).toEqual([
      ru["tasks.project_placeholder"],
      "Альфа",
    ]);
    await waitFor(() => expect(document.activeElement).toBe(titleInput()));
  });

  it("004_fr20_focus_is_on_dialog_itself_while_loading", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [LIST]: () => gate.promise }));
    renderDialog();
    await screen.findByRole("status");
    expect(dialog().getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(dialog());
    gate.resolve(emptyList());
  });

  it("004_fr20_user_choice_is_kept_after_focus_move", async () => {
    installFetch(routesU());
    renderDialog();
    await loaded();
    await waitFor(() => expect(document.activeElement).toBe(projectSelect()));
    fireEvent.change(projectSelect(), { target: { value: P3 } });
    expect(projectSelect().value).toBe(P3);
  });
});

describe("focus is not stolen from the user (FR-20, M9, M10)", () => {
  const tick = () => act(() => new Promise<void>((r) => setTimeout(r, 20)));

  it("004_fr20_m9_user_focus_on_title_while_loading_is_kept_when_list_arrives", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [LIST]: () => gate.promise }));
    renderDialog({ currentProjectId: null }); // без предвыбора: иначе код сам увёл бы фокус на поле проекта
    await screen.findByRole("status");
    titleInput().focus();
    expect(document.activeElement).toBe(titleInput());
    gate.resolve(
      j(
        200,
        page([listItem(P1, "Альфа"), listItem(P3, "Гамма")], 1, false, 100),
      ),
    );
    await loaded();
    await tick();
    expect(document.activeElement).toBe(titleInput());
    expect(titleInput().value).toBe("");
  });

  it("004_fr20_m9_user_focus_on_cancel_while_loading_is_kept_when_list_arrives_with_preselect", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [LIST]: () => gate.promise }));
    renderDialog({ currentProjectId: P1 });
    await screen.findByRole("status");
    const cancel = within(dialog()).getByRole("button", {
      name: ru["admin.cancel"],
    });
    cancel.focus();
    gate.resolve(
      j(
        200,
        page([listItem(P1, "Альфа"), listItem(P3, "Гамма")], 1, false, 100),
      ),
    );
    await loaded();
    await tick();
    expect(document.activeElement).toBe(cancel);
  });

  it("004_fr20_m10_refetch_does_not_move_focus_again", async () => {
    let n = 0;
    const f = installFetch(
      routesU({
        // второй ответ другой (порядок), чтобы данные сменили ссылку и эффект мог сработать снова
        [LIST]: () =>
          j(
            200,
            page(
              ++n === 1
                ? [listItem(P1, "Альфа"), listItem(P3, "Гамма")]
                : [listItem(P3, "Гамма"), listItem(P1, "Альфа")],
              1,
              false,
              100,
            ),
          ),
      }),
    );
    const { qc } = renderDialog({ currentProjectId: P1 });
    await loaded();
    await waitFor(() => expect(document.activeElement).toBe(titleInput()));
    dialog().focus();
    expect(document.activeElement).toBe(dialog());
    await act(async () => {
      await qc.refetchQueries({ queryKey: ["projects", "creatable"] });
    });
    expect(f.count(LIST)).toBe(2);
    await waitFor(() =>
      expect(optionTexts(projectSelect())).toEqual([ru["tasks.project_placeholder"], "Гамма", "Альфа"]),
    );
    await tick();
    expect(document.activeElement).toBe(dialog());
  });
});

describe("keyboard in the list-error state (AC-33, blocking)", () => {
  async function errorState() {
    installFetch(routesU({ [LIST]: () => err(500, "internal_error") }));
    renderDialog();
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(alert));
    return alert;
  }

  it("004_ac33_error_alert_is_focused_inside_dialog", async () => {
    const alert = await errorState();
    expect(alert.matches('p[role="alert"][tabindex="-1"]')).toBe(true);
    expect(dialog().contains(alert)).toBe(true);
  });

  it("004_ac33_shift_tab_from_error_alert_is_prevented_and_stays_inside_on_last", async () => {
    const alert = await errorState();
    const els = focusables(dialog());
    const last = els[els.length - 1]!;
    expect(last.textContent).toBe(ru["admin.cancel"]);
    const proceed = fireEvent.keyDown(alert, { key: "Tab", shiftKey: true });
    expect(
      proceed,
      "Shift+Tab with focus on the alert must be defaultPrevented",
    ).toBe(false);
    expect(dialog().contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(last);
  });

  it("004_ac33_tab_from_error_alert_stays_inside", async () => {
    const alert = await errorState();
    const proceed = fireEvent.keyDown(alert, { key: "Tab" });
    if (proceed) {
      // событие не отменено: браузер пойдёт к следующему фокусируемому после alert - он обязан быть в окне
      const next = Array.from(
        document.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).find(
        (e) =>
          !(e as HTMLButtonElement).disabled &&
          alert.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
      expect(
        next && dialog().contains(next),
        "natural next focus target is inside the dialog",
      ).toBe(true);
    } else {
      expect(dialog().contains(document.activeElement)).toBe(true);
    }
  });

  it("004_ac33_tab_from_last_element_goes_to_first_in_error_state", async () => {
    await errorState();
    const els = focusables(dialog());
    const first = els[0]!;
    const last = els[els.length - 1]!;
    last.focus();
    const proceed = fireEvent.keyDown(last, { key: "Tab" });
    expect(proceed, "Tab from the last element must be defaultPrevented").toBe(
      false,
    );
    expect(document.activeElement).toBe(first);
    expect(dialog().contains(document.activeElement)).toBe(true);
  });
});

describe("keyboard (AC-32, AC-33, AC-34, FR-20)", () => {
  it("004_ac32_escape_calls_on_close_without_requests", async () => {
    const f = installFetch(routesU());
    const { onClose } = renderDialog();
    await loaded();
    const before = f.calls.length;
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(posts(f)).toHaveLength(0);
    expect(f.calls.length).toBe(before);
  });

  it("004_ac32_escape_works_while_loading", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [LIST]: () => gate.promise }));
    const { onClose } = renderDialog();
    await screen.findByRole("status");
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    gate.resolve(emptyList());
  });

  it("004_ac32_cancel_button_calls_on_close_without_requests", async () => {
    const f = installFetch(routesU());
    const { onClose } = renderDialog();
    await loaded();
    const before = f.calls.length;
    fireEvent.click(
      within(dialog()).getByRole("button", { name: ru["admin.cancel"] }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(f.calls.length).toBe(before);
  });

  it("004_ac33_tab_and_shift_tab_cycle_inside_dialog", async () => {
    installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    await waitFor(() => expect(document.activeElement).toBe(titleInput()));
    const n = focusables(dialog()).length;
    // Изменено по spec 006 §9.2: в круг входят описание и срок (было 4: проект, название, «Создать», «Отмена»).
    expect(n).toBe(6); // проект, название, описание, срок, «Создать задачу», «Отмена»
    const els = focusables(dialog());
    const start = document.activeElement as HTMLElement;
    for (const shift of [false, true]) {
      start.focus(); // отдельный проход с одного и того же фиксированного старта
      expect(document.activeElement).toBe(start);
      const visited = new Set<Element | null>();
      for (let i = 0; i < n; i++) {
        press(shift);
        expect(dialog().contains(document.activeElement)).toBe(true);
        visited.add(document.activeElement);
      }
      // за n нажатий пройдены все n элементов, и фокус вернулся на старт
      expect(visited.size).toBe(n);
      for (const el of els) expect(visited.has(el)).toBe(true);
      expect(document.activeElement).toBe(start);
    }
  });

  it("004_ac33_tab_from_last_goes_to_first_and_shift_tab_from_first_goes_to_last", async () => {
    installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    const els = focusables(dialog());
    els[els.length - 1]!.focus();
    press(false);
    expect(document.activeElement).toBe(els[0]);
    press(true);
    expect(document.activeElement).toBe(els[els.length - 1]);
  });

  it("004_ac33_tab_with_focus_outside_returns_inside", async () => {
    installFetch(routesU());
    renderDialog();
    await loaded();
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();
    fireEvent.keyDown(outside, { key: "Tab" });
    // событие всплывает к окну только изнутри; проверяем и обработчик окна напрямую
    fireEvent.keyDown(dialog(), { key: "Tab" });
    expect(dialog().contains(document.activeElement)).toBe(true);
    outside.remove();
  });

  it("004_ac34_overlay_mousedown_and_click_do_not_close", async () => {
    const f = installFetch(routesU());
    const { container, onClose } = renderDialog();
    await loaded();
    const overlay = container.querySelector<HTMLElement>(".ui-overlay")!;
    expect(overlay).toBeTruthy();
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(posts(f)).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------------------------
// 006 R6-T11: диалог «Новая задача» - описание, срок, исполнитель (FR-20, FR-25; AC-33, AC-34).
// Время: freezeDateForFile() -> 2026-10-19T21:30:00Z (= 2026-10-20 по Москве), TZ среды не важен.
// ---------------------------------------------------------------------------------------------
const descInput = () => within(dialog()).getByLabelText(exactLabel(ru["tasks.description_label"])) as HTMLTextAreaElement;
const dueInput = () => within(dialog()).getByLabelText(exactLabel(ru["tasks.due_label"])) as HTMLInputElement;
const assigneePicker = () =>
  within(dialog()).getByRole("combobox", { name: ru["tasks.assignee_label"] }) as HTMLInputElement;
const selectedLine = () => dialog().querySelector<HTMLElement>('[data-field="selected-assignee"]');
const membersCalls = (f: { calls: Request[] }) =>
  f.calls.filter((c) => c.method === "GET" && /\/projects\/[^/]+\/members$/.test(new URL(c.url).pathname));

describe("006 AC-33: fields, defaults, required marks, no priority", () => {
  it("006_ac33_ba_description_empty_due_today_msk_assignee_self_required_marks_no_priority", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    expect(descInput().value).toBe("");
    expect(dueInput().value).toBe(TODAY);
    expect(selectedLine()!.textContent).toBe("admin");
    for (const [name, el] of [
      ["description", descInput()],
      ["due", dueInput()],
      ["assignee", assigneePicker()],
    ] as const) {
      expect(el.getAttribute("aria-required"), name).toBe("true");
    }
    // видимый признак в подписях: «*» из словаря, скрыт от диктора (006/PD-12)
    for (const el of [descInput(), dueInput()]) {
      const mark = dialog().querySelector(`label[for="${el.id}"] .ui-required`)!;
      expect(mark).toBeTruthy();
      expect(mark.textContent).toBe(ru["tasks.required_mark"]);
      expect(mark.getAttribute("aria-hidden")).toBe("true");
    }
    const assigneeLabel = dialog().querySelector(`label[for="${assigneePicker().id}"] .ui-required`)!;
    expect(assigneeLabel).toBeTruthy();
    expect(assigneeLabel.getAttribute("aria-hidden")).toBe("true");
    expect(dialog().querySelector('[name="priority"]')).toBeNull();
    expect(within(dialog()).queryByLabelText(ru["tasks.priority_label"])).toBeNull();
  });

  it("006_ac33_user_description_due_required_marks_and_fixed_assignee_line", async () => {
    installFetch(routesU());
    renderDialog({ currentProjectId: P1, session: U });
    await loaded();
    expect(descInput().getAttribute("aria-required")).toBe("true");
    expect(dueInput().getAttribute("aria-required")).toBe("true");
    expect(dueInput().value).toBe(TODAY);
    expect(dialog().querySelector(`label[for="${descInput().id}"] .ui-required`)).toBeTruthy();
    expect(dialog().querySelector(`label[for="${dueInput().id}"] .ui-required`)).toBeTruthy();
    expect(dialog().querySelector('[data-field="fixed-assignee"]')!.textContent).toBe("Исполнитель: ivanov");
    expect(selectedLine()).toBeNull();
  });

  it("006_ac33_default_due_is_msk_calendar_day_whatever_the_browser_time_zone", async () => {
    // В поясе UTC-10 календарная дата ещё 2026-10-19, срок всё равно по Москве (006/D-11).
    const prev = process.env.TZ;
    process.env.TZ = "Pacific/Honolulu";
    try {
      installFetch(routesU());
      renderDialog({ currentProjectId: P1, session: U });
      await loaded();
      expect(dueInput().value).toBe(TODAY);
    } finally {
      if (prev === undefined) delete process.env.TZ;
      else process.env.TZ = prev;
    }
  });

  it("006_ac33_project_change_returns_assignee_to_ba_and_picker_text_is_empty", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    fireEvent.change(assigneePicker(), { target: { value: "kuz" } });
    fireEvent.click((await within(await screen.findByRole("listbox")).findAllByRole("option"))[0]!);
    await waitFor(() => expect(selectedLine()!.textContent).toBe("kuznetsov"));
    fireEvent.change(projectSelect(), { target: { value: P3 } });
    await waitFor(() => expect(selectedLine()!.textContent).toBe("admin"));
    expect(assigneePicker().value).toBe("");
  });

  it("006_fr25_members_requested_only_for_ba_and_only_for_a_selected_project", async () => {
    const fu = installFetch(routesU());
    renderDialog({ currentProjectId: P1, session: U });
    await loaded();
    await new Promise((r) => setTimeout(r, 50));
    expect(membersCalls(fu)).toHaveLength(0); // «Пользователь»: запроса участников нет
  });

  it("006_fr25_ba_without_selected_project_has_no_members_request_then_one_after_choice", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: null, session: BA });
    await loaded();
    await new Promise((r) => setTimeout(r, 50));
    expect(projectSelect().value).toBe("");
    expect(membersCalls(f)).toHaveLength(0);
    fireEvent.change(projectSelect(), { target: { value: P1 } });
    await waitFor(() => expect(f.count(MEMBERS_OF(P1))).toBe(1));
    expect(membersCalls(f)).toHaveLength(1);
    expect(f.query(f.last(MEMBERS_OF(P1))).get("page_size")).toBe("100");
  });
});

describe("006 AC-34: assignee candidates are project members only (FR-25)", () => {
  async function offered(typed: string): Promise<string[]> {
    fireEvent.change(assigneePicker(), { target: { value: typed } });
    // дождаться ответа справочника для этого запроса и дать отрисовать варианты
    await new Promise((r) => setTimeout(r, 450));
    // только варианты списка исполнителей (в диалоге есть и выпадающий список проектов)
    return within(dialog())
      .queryAllByRole("listbox")
      .flatMap((l) => within(l).queryAllByRole("option"))
      .map((o) => o.textContent ?? "");
  }

  it("006_ac34_kuznetsov_is_offered", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    fireEvent.change(assigneePicker(), { target: { value: "kuz" } });
    const list = await screen.findByRole("listbox");
    const opts = await within(list).findAllByRole("option");
    expect(opts.map((o) => o.textContent).join("|")).toContain("kuznetsov");
  });

  it("006_ac34_ba_self_is_offered_by_prefix", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    fireEvent.change(assigneePicker(), { target: { value: "adm" } });
    const opts = await within(await screen.findByRole("listbox")).findAllByRole("option");
    expect(opts.map((o) => o.textContent).join("|")).toContain("admin");
  });

  it("006_ac34_blocked_member_and_non_member_are_not_offered", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    await waitFor(() => expect(f.count(MEMBERS_OF(P1))).toBe(1));
    // справочник вернул обоих (ub - заблокированный участник; petrov - не участник), но вариантов нет
    expect(await offered("ub")).toEqual([]);
    expect(f.calls.some((c) => new URL(c.url).pathname === "/api/v1/users" && f.query(c).get("q") === "ub")).toBe(true);
    expect(await offered("pet")).toEqual([]);
    expect(f.calls.some((c) => new URL(c.url).pathname === "/api/v1/users" && f.query(c).get("q") === "pet")).toBe(true);
  });

  it("006_ac34_member_of_another_project_is_not_offered_after_project_change", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    fireEvent.change(projectSelect(), { target: { value: P3 } }); // в P3 нет kuznetsov
    await waitFor(() => expect(f.count(MEMBERS_OF(P3))).toBe(1));
    expect(await offered("kuz")).toEqual([]);
    expect(f.calls.some((c) => c.method === "GET" && f.query(c).get("q") === "kuz")).toBe(true);
  });
});

describe("006 Tab cycle includes the description (DIALOG_FOCUSABLE + textarea)", () => {
  it("006_ac33_tab_from_description_goes_to_due_not_to_the_first_element", async () => {
    installFetch(routesU());
    renderDialog({ currentProjectId: P1, session: U });
    await loaded();
    descInput().focus();
    expect(document.activeElement).toBe(descInput());
    const proceed = fireEvent.keyDown(descInput(), { key: "Tab" });
    // обработчик окна не должен перехватывать Tab из середины круга (браузер сам пойдёт к «Сроку»)
    expect(proceed, "Tab from the description must not be defaultPrevented").toBe(true);
    expect(document.activeElement).toBe(descInput());
    const back = fireEvent.keyDown(descInput(), { key: "Tab", shiftKey: true });
    expect(back, "Shift+Tab from the description must not be defaultPrevented").toBe(true);
  });

  it("006_ac33_dom_order_title_description_due_and_cycle_covers_all_for_ba", async () => {
    installFetch(routesBA());
    renderDialog({ currentProjectId: P1, session: BA });
    await loaded();
    const els = focusables(dialog());
    const idx = (e: Element) => els.indexOf(e as HTMLElement);
    expect(idx(titleInput())).toBeGreaterThanOrEqual(0);
    expect(idx(descInput())).toBe(idx(titleInput()) + 1);
    expect(idx(dueInput())).toBe(idx(descInput()) + 1);
    expect(idx(assigneePicker())).toBeGreaterThan(idx(dueInput()));
    const n = els.length;
    els[0]!.focus();
    const visited = new Set<Element | null>();
    for (let i = 0; i < n; i++) {
      press(false);
      expect(dialog().contains(document.activeElement)).toBe(true);
      visited.add(document.activeElement);
    }
    expect(visited.size).toBe(n);
    expect(document.activeElement).toBe(els[0]);
    // Tab с последнего элемента - на первый, Shift+Tab с первого - на последний
    els[n - 1]!.focus();
    press(false);
    expect(document.activeElement).toBe(els[0]);
    press(true);
    expect(document.activeElement).toBe(els[n - 1]);
  });
});
