// T83: форма создания задачи на вкладке «Задачи».
// AC: UF-3, UF-6, FR-20 (П: поле исполнителя не отправляется; «без исполнителя» - только БА/СМ),
//     FR-26, AC-56, AC-109 (интерфейс), NFR-5 (срок YYYY-MM-DD без пересчёта пояса), NFR-6, NFR-7.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { ADMIN_ID } from "../admin/helpers";
import { ID_PETROV, ID_SIDOROV, M_KUZNETSOV, M_OWNER, M_PETROV, M_SIDOROV } from "../projects/helpers";
import {
  ID_KUZNETSOV,
  MEMBERS,
  PERM_MANAGE,
  PERM_READ,
  PID,
  PROJ_CREATE,
  PROJ_TASKS,
  T1,
  TID1,
  USERS,
  createForm,
  deferred,
  err,
  f_,
  installFetch,
  j,
  openTasksTab,
  page,
  renderApp,
  taskDetail,
  taskRoutes,
  taskRow,
  type Handler,
} from "./helpers";

type Role = "business_admin" | "user" | "tech_admin";

async function open(role: Role, over: Record<string, Handler> = {}, opts: { perms?: Record<string, boolean> } = {}) {
  const f = installFetch(
    taskRoutes(role, { [PROJ_CREATE]: () => j(201, taskDetail()), ...over }, { items: [T1], ...opts }),
  );
  const view = renderApp(`/projects/${PID}`);
  await screen.findByRole("heading", { level: 1, name: "Альфа" });
  await openTasksTab();
  await waitFor(() => expect(createForm(view.container) ?? taskRow(view.container, TID1)).toBeTruthy());
  return { f, ...view };
}

const body = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
const input = (c: ParentNode, sel: string) => c.querySelector<HTMLInputElement>(sel)!;
// Имя combobox начинается с подписи (006/PD-12: в подписи может быть «*»).
const ASSIGNEE_NAME = ru["tasks.assignee_label"];
const picker = () => screen.getByRole("combobox", { name: ASSIGNEE_NAME });
const submit = (form: HTMLFormElement) => fireEvent.submit(form);

function fill(form: HTMLFormElement, title: string, description = "Описание") {
  fireEvent.change(input(form, 'input[name="title"]'), { target: { value: title } });
  // 006/FR-19: описание и срок обязательны; срок уже стоит по умолчанию (сегодня по Москве).
  fireEvent.change(form.querySelector('textarea[name="description"]')!, { target: { value: description } });
}

const VALIDATION = errorMessage("validation_error");
const field = (form: HTMLFormElement, name: string) =>
  form.querySelector<HTMLElement>(`[name="${name}"]`)!;
const MSG = {
  title: "Введите название задачи",
  description: "Введите описание задачи",
  due: "Укажите срок",
  past: "Срок не может быть раньше сегодняшнего дня",
  assignee: "Выберите исполнителя",
};
/** Сообщение, на которое указывает aria-describedby поля (null, если связки нет). */
function describedText(el: HTMLElement): string | null {
  const ids = (el.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
  const texts = ids.map((id) => document.getElementById(id)?.textContent ?? "");
  return ids.length === 0 ? null : texts.join(" ");
}

afterEach(() => {
  vi.useRealTimers();
});

describe("create task form", () => {
  it("uf3_form_present_with_fields_when_permission_and_absent_without", async () => {
    const { container } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    expect(form).toBeTruthy();
    expect(input(form, 'input[name="title"]')).toBeTruthy();
    expect(form.querySelector('textarea[name="description"]')).toBeTruthy();
    expect(input(form, 'input[type="date"][name="due_date"]')).toBeTruthy();
    const prio = form.querySelector<HTMLSelectElement>('select[name="priority"]')!;
    expect(Array.from(prio.options).map((o) => o.value)).toEqual(["low", "medium", "high"]);
    expect(prio.value).toBe("medium");
    // нет меток (plan §11)
    expect(form.querySelector('[name="labels"]')).toBeNull();
    for (const el of Array.from(form.querySelectorAll("input,select,textarea"))) {
      expect(el.getAttribute("aria-label") || (el as HTMLInputElement).labels?.length, el.outerHTML).toBeTruthy();
    }
  });

  it("uf3_no_form_without_create_task_permission", async () => {
    const { container } = await open("business_admin", {}, { perms: { ...PERM_READ, create_task: false } });
    expect(createForm(container)).toBeNull();
  });

  it("fr20_user_role_has_no_assignee_picker_and_body_has_no_assignee_key", async () => {
    const { container, f } = await open("user", {}, { perms: PERM_READ });
    const form = createForm(container)!;
    expect(screen.queryByRole("combobox", { name: ASSIGNEE_NAME })).toBeNull();
    fill(form, "  Моя задача  ");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = await body(f.last(PROJ_CREATE));
    expect("assignee_id" in b).toBe(false);
    expect(b.title).toBe("Моя задача");
    expect(b.priority).toBe("medium");
  });

  // Изменено по 006 AC-31 / PD-13: исполнитель по умолчанию - сам БА, тело всегда содержит
  // assignee_id (раньше без выбора ключа не было).
  it("006_ac31_fr20_ba_without_choice_sends_own_id_as_assignee", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    expect(picker()).toBeTruthy();
    fill(createForm(container)!, "По умолчанию");
    submit(createForm(container)!);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = await body(f.last(PROJ_CREATE));
    expect(b.assignee_id).toBe(ADMIN_ID);
  });

  // Тест про смешанную роль (fr20, выбор исполнителя) удалён (002 FR-9, FR-21): такой роли больше нет;
  // заменён тестом 002_fr9_ba_gets_assignee_picker_user_does_not.
  it("002_fr9_ba_gets_assignee_picker_user_does_not", async () => {
    const ba = await open("business_admin", {}, { perms: PERM_MANAGE });
    expect(picker()).toBeTruthy();
    expect(createForm(ba.container)).toBeTruthy();
    ba.unmount();
    document.body.innerHTML = "";
    window.history.pushState({}, "", "/");
    const usr = await open("user", {}, { perms: PERM_READ });
    expect(createForm(usr.container)).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: ASSIGNEE_NAME })).toBeNull();
  });

  it("002_fr9_tech_admin_role_has_no_assignee_picker", async () => {
    const { container } = await open("tech_admin", {}, { perms: PERM_MANAGE });
    expect(createForm(container)).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: ASSIGNEE_NAME })).toBeNull();
  });

  it("fr20_ba_picks_member_and_assignee_id_is_sent_then_clear_removes_it", async () => {
    const { container, f } = await open(
      "business_admin",
      { [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])) },
      { perms: PERM_MANAGE },
    );
    fireEvent.change(picker(), { target: { value: "kuz" } });
    fireEvent.click((await within(await screen.findByRole("listbox", { name: ASSIGNEE_NAME })).findAllByRole("option"))[0]!);
    const form = createForm(container)!;
    await waitFor(() => expect(f_(form, "selected-assignee")!.textContent).toBe("kuznetsov"));
    fill(form, "С исполнителем");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect((await body(f.last(PROJ_CREATE))).assignee_id).toBe(ID_KUZNETSOV);
  });

  it("fr20_clear_assignee_button_drops_selection", async () => {
    const { container, f } = await open(
      "business_admin",
      { [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])) },
      { perms: PERM_MANAGE },
    );
    fireEvent.change(picker(), { target: { value: "kuz" } });
    fireEvent.click((await within(await screen.findByRole("listbox", { name: ASSIGNEE_NAME })).findAllByRole("option"))[0]!);
    const form = createForm(container)!;
    await waitFor(() => expect(f_(form, "selected-assignee")).toBeTruthy());
    fireEvent.click(form.querySelector('button[data-action="clear-assignee"]')!);
    await waitFor(() => expect(f_(form, "selected-assignee")).toBeNull());
    // Изменено по 006 AC-30 / PD-13: пустой выбор не уходит на сервер (раньше - задача без исполнителя).
    fill(form, "Снова без");
    submit(form);
    expect(await screen.findByText(MSG.assignee)).toBeTruthy();
    expect(f.count(PROJ_CREATE)).toBe(0);
  });

  it("fr20_picker_does_not_offer_blocked_or_roleless_members", async () => {
    const { container } = await open(
      "business_admin",
      {
        [MEMBERS]: () => j(200, page([M_OWNER, M_KUZNETSOV, M_PETROV, M_SIDOROV])),
        [USERS]: () =>
          j(
            200,
            page([
              { id: ID_KUZNETSOV, login: "kuznetsov", role: "user" },
              { id: ID_PETROV, login: "petrov", role: "user" },
              { id: ID_SIDOROV, login: "sidorov", role: "user" },
            ]),
          ),
      },
      { perms: PERM_MANAGE },
    );
    expect(container).toBeTruthy();
    fireEvent.change(picker(), { target: { value: "o" } });
    const list = await screen.findByRole("listbox", { name: ASSIGNEE_NAME });
    await waitFor(() => {
      const texts = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
      expect(texts.some((t) => t.includes("kuznetsov"))).toBe(true);
    });
    const texts = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
    expect(texts.some((t) => t.includes("petrov"))).toBe(false);
    expect(texts.some((t) => t.includes("sidorov"))).toBe(false);
  });

  it("nfr6_not_project_member_422_single_dictionary_alert_and_keeps_input", async () => {
    const { container } = await open(
      "business_admin",
      { [PROJ_CREATE]: () => err(422, "not_project_member") },
      { perms: PERM_MANAGE },
    );
    const form = createForm(container)!;
    fill(form, "Сохранится");
    submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("not_project_member"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(input(createForm(container)!, 'input[name="title"]').value).toBe("Сохранится");
  });

  it("nfr5_due_date_sent_as_entered_ymd_and_priority_high", async () => {
    freezeTime(); // 006/FR-19: срок не в прошлом, результат не зависит от реальной даты
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "Со сроком");
    fireEvent.change(input(form, 'input[name="due_date"]'), { target: { value: "2026-12-31" } });
    fireEvent.change(form.querySelector('select[name="priority"]')!, { target: { value: "high" } });
    fireEvent.change(form.querySelector('textarea[name="description"]')!, { target: { value: "Описание" } });
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = await body(f.last(PROJ_CREATE));
    expect(b.due_date).toBe("2026-12-31");
    expect(b.priority).toBe("high");
    expect(b.description).toBe("Описание");
    expect(b.title).toBe("Со сроком");
  });

  // Изменено по 006 AC-30 / FR-19: срок обязателен; пустой срок не уходит на сервер ни строкой, ни null.
  it("nfr5_empty_due_date_blocks_request_not_sent_as_string", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "Без срока");
    fireEvent.change(input(form, 'input[name="due_date"]'), { target: { value: "" } });
    submit(form);
    expect(await screen.findByText(MSG.due)).toBeTruthy();
    expect(f.count(PROJ_CREATE)).toBe(0);
  });

  // Изменено по 006 AC-30 / FR-19: сообщение у поля названия, а не общее validation_error.
  it("ac96_empty_title_blocks_request_and_shows_field_message_not_validation_alert", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    fill(createForm(container)!, "   ");
    submit(createForm(container)!);
    expect(await screen.findByText(MSG.title)).toBeTruthy();
    expect(screen.queryByText(VALIDATION)).toBeNull();
    expect(f.count(PROJ_CREATE)).toBe(0);
  });

  it("uf6_success_resets_form_refetches_list_and_keeps_focus", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const before = f.count(PROJ_TASKS);
    const form = createForm(container)!;
    fill(form, "Новая");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_TASKS)).toBeGreaterThan(before));
    await waitFor(() => expect(input(createForm(container)!, 'input[name="title"]').value).toBe(""));
    expect(document.activeElement).toBe(input(createForm(container)!, 'input[name="title"]'));
    expect(f.last(PROJ_TASKS).headers.get("X-GT-Background")).toBeNull();
  });

  it("nfr6_server_error_shows_dictionary_alert_and_keeps_input", async () => {
    freezeTime(); // 006/FR-19: срок не в прошлом, результат не зависит от реальной даты
    const { container } = await open(
      "business_admin",
      { [PROJ_CREATE]: () => err(403, "forbidden") },
      { perms: PERM_MANAGE },
    );
    const form = createForm(container)!;
    fill(form, "Останется");
    fireEvent.change(input(form, 'input[name="due_date"]'), { target: { value: "2026-11-01" } });
    submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(input(createForm(container)!, 'input[name="title"]').value).toBe("Останется");
    expect(input(createForm(container)!, 'input[name="due_date"]').value).toBe("2026-11-01");
  });

  it("nfr7_double_submit_while_in_flight_sends_one_post", async () => {
    const d = deferred<Response>();
    const { container, f } = await open(
      "business_admin",
      { [PROJ_CREATE]: () => d.promise },
      { perms: PERM_MANAGE },
    );
    const form = createForm(container)!;
    fill(form, "Дубль");
    submit(form);
    submit(form);
    fireEvent.click(form.querySelector('button[type="submit"]')!);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    d.resolve(j(201, taskDetail()));
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
  });

  it("nfr6_labels_come_from_dictionary", async () => {
    const { container } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    const dict = Object.values(ru) as string[];
    expect(dict).toContain(form.querySelector('button[type="submit"]')!.textContent);
    // 006/PD-12: в подписи после текста стоит «*» из словаря (aria-hidden) - сравниваем текст без неё.
    for (const l of Array.from(form.querySelectorAll("label"))) {
      const mark = l.querySelector(".ui-required")?.textContent ?? "";
      if (mark !== "") expect(dict).toContain(mark);
      expect(dict).toContain((l.textContent ?? "").slice(0, (l.textContent ?? "").length - mark.length));
    }
  });
});

// ---------------------------------------------------------------------------------------------
// 006 R6-T10: форма вкладки «Задачи» - обязательные поля, умолчания, сообщения у полей.
// Время фиксируется fake timers (только Date): 2026-10-19T21:30:00Z = 2026-10-20 00:30 по Москве
// при любом поясе среды (в UTC тот же результат по календарю Москвы, а не браузера).
// ---------------------------------------------------------------------------------------------
const NOW = new Date("2026-10-19T21:30:00Z");
const TODAY = "2026-10-20";
const YESTERDAY = "2026-10-19";

function freezeTime(): void {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
}

const DUE = 'input[name="due_date"]';
const alertTexts = () => screen.queryAllByRole("alert").map((a) => a.textContent);

describe("006 form defaults and required marks (FR-19)", () => {
  it("006_ac28_ba_defaults_today_msk_self_medium_empty_texts_and_required_marks", async () => {
    freezeTime();
    const { container } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    expect(input(form, DUE).value).toBe(TODAY);
    expect(f_(form, "selected-assignee")!.textContent).toBe("admin");
    expect(form.querySelector<HTMLSelectElement>('select[name="priority"]')!.value).toBe("medium");
    expect(input(form, 'input[name="title"]').value).toBe("");
    expect(form.querySelector<HTMLTextAreaElement>('textarea[name="description"]')!.value).toBe("");

    // видимый признак: «*» в подписи четырёх обязательных полей, скрыт от диктора (PD-12)
    for (const name of ["title", "description", "due_date"]) {
      const el = field(form, name);
      expect(el.getAttribute("aria-required"), name).toBe("true");
      const label = form.querySelector(`label[for="${el.id}"]`)!;
      const mark = label.querySelector(".ui-required")!;
      expect(mark, name).toBeTruthy();
      expect(mark.textContent).toBe("*");
      expect(mark.getAttribute("aria-hidden")).toBe("true");
    }
    expect(picker().getAttribute("aria-required")).toBe("true");
    expect(form.querySelectorAll(".ui-required")).toHaveLength(4);
    // приоритет не обязательный
    expect(field(form, "priority").getAttribute("aria-required")).toBeNull();
  });

  it("006_ac29_user_role_fixed_assignee_line_msk_today_medium_no_picker", async () => {
    freezeTime();
    const { container, f } = await open("user", {}, { perms: PERM_READ });
    const form = createForm(container)!;
    expect(screen.queryByRole("combobox", { name: ASSIGNEE_NAME })).toBeNull();
    expect(f_(form, "fixed-assignee")!.textContent).toBe("Исполнитель: admin");
    expect(input(form, DUE).value).toBe(TODAY);
    expect(form.querySelector<HTMLSelectElement>('select[name="priority"]')!.value).toBe("medium");
    expect(form.querySelectorAll(".ui-required")).toHaveLength(3);
    fill(form, "Моя");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect(await body(f.last(PROJ_CREATE))).toEqual({
      title: "Моя",
      description: "Описание",
      due_date: TODAY,
      priority: "medium",
    });
  });

  it("006_ac28_defaults_do_not_depend_on_browser_time_zone", async () => {
    // В среде с поясом, где календарная дата уже 2026-10-19 (UTC-10), срок всё равно по Москве.
    const prev = process.env.TZ;
    process.env.TZ = "Pacific/Honolulu";
    try {
      freezeTime();
      const { container } = await open("business_admin", {}, { perms: PERM_MANAGE });
      expect(input(createForm(container)!, DUE).value).toBe(TODAY);
    } finally {
      if (prev === undefined) delete process.env.TZ;
      else process.env.TZ = prev;
    }
  });
});

describe("006 validation before sending (AC-30)", () => {
  it("006_ac30_empty_title_and_description_two_messages_linked_focus_on_title_no_request", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    submit(form);
    expect(await screen.findByText(MSG.title)).toBeTruthy();
    expect(screen.getByText(MSG.description)).toBeTruthy();
    expect(f.count(PROJ_CREATE)).toBe(0);
    const title = field(form, "title");
    const desc = field(form, "description");
    expect(title.getAttribute("aria-invalid")).toBe("true");
    expect(desc.getAttribute("aria-invalid")).toBe("true");
    expect(describedText(title)).toBe(MSG.title);
    expect(describedText(desc)).toBe(MSG.description);
    // остальные поля верны: без пометок
    expect(field(form, "due_date").getAttribute("aria-invalid")).toBeNull();
    expect(picker().getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(title);
    // ровно два сообщения, общего validation_error нет
    expect(alertTexts().sort()).toEqual([MSG.title, MSG.description].sort());
    expect(screen.queryByText(VALIDATION)).toBeNull();
  });

  it("006_ac30_whitespace_only_title_and_description_are_empty", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "  \t ", " \n ");
    submit(form);
    expect(await screen.findByText(MSG.title)).toBeTruthy();
    expect(screen.getByText(MSG.description)).toBeTruthy();
    expect(f.count(PROJ_CREATE)).toBe(0);
  });

  it("006_ac30_cleared_due_date_shows_due_required_and_focuses_date", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "Задача");
    fireEvent.change(input(form, DUE), { target: { value: "" } });
    submit(form);
    expect(await screen.findByText(MSG.due)).toBeTruthy();
    const due = field(form, "due_date");
    expect(due.getAttribute("aria-invalid")).toBe("true");
    expect(describedText(due)).toBe(MSG.due);
    expect(document.activeElement).toBe(due);
    expect(f.count(PROJ_CREATE)).toBe(0);
    expect(screen.queryByText(VALIDATION)).toBeNull();
  });

  it("006_ac30_yesterday_msk_is_past_today_is_accepted", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "Задача");
    fireEvent.change(input(form, DUE), { target: { value: YESTERDAY } });
    submit(form);
    expect(await screen.findByText(MSG.past)).toBeTruthy();
    expect(describedText(field(form, "due_date"))).toBe(MSG.past);
    expect(f.count(PROJ_CREATE)).toBe(0);
    expect(screen.queryByText(VALIDATION)).toBeNull();
    // сегодня (по Москве) - не ошибка
    fireEvent.change(input(form, DUE), { target: { value: TODAY } });
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
  });

  it("006_ac30_cleared_assignee_shows_choose_assignee_and_focuses_picker", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "Задача");
    fireEvent.click(form.querySelector('button[data-action="clear-assignee"]')!);
    await waitFor(() => expect(f_(form, "selected-assignee")).toBeNull());
    submit(form);
    expect(await screen.findByText(MSG.assignee)).toBeTruthy();
    expect(picker().getAttribute("aria-invalid")).toBe("true");
    expect(describedText(picker())).toBe(MSG.assignee);
    expect(document.activeElement).toBe(picker());
    expect(f.count(PROJ_CREATE)).toBe(0);
    expect(screen.queryByText(VALIDATION)).toBeNull();
  });

  it("006_ac30_first_invalid_in_form_order_gets_focus_and_fixed_field_clears_its_message", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fireEvent.change(input(form, 'input[name="title"]'), { target: { value: "Есть" } });
    submit(form);
    expect(await screen.findByText(MSG.description)).toBeTruthy();
    expect(document.activeElement).toBe(field(form, "description"));
    // исправили и отправили снова: сообщение ушло, запрос один
    fireEvent.change(field(form, "description"), { target: { value: "Текст" } });
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect(screen.queryByText(MSG.description)).toBeNull();
  });
});

describe("006 request body and reset (AC-31)", () => {
  it("006_ac31_body_has_trimmed_title_description_due_priority_and_own_assignee_one_request", async () => {
    freezeTime();
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    fill(form, "  Отчёт  ", "Собрать данные");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect(await body(f.last(PROJ_CREATE))).toEqual({
      title: "Отчёт",
      description: "Собрать данные",
      due_date: TODAY,
      priority: "medium",
      assignee_id: ADMIN_ID,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(f.count(PROJ_CREATE)).toBe(1);
  });

  it("006_ac31_chosen_member_id_goes_to_body_and_after_201_form_returns_to_defaults", async () => {
    freezeTime();
    const { container, f } = await open(
      "business_admin",
      { [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])) },
      { perms: PERM_MANAGE },
    );
    const form = createForm(container)!;
    fireEvent.change(picker(), { target: { value: "kuz" } });
    fireEvent.click(
      (await within(await screen.findByRole("listbox", { name: ASSIGNEE_NAME })).findAllByRole("option"))[0]!,
    );
    await waitFor(() => expect(f_(form, "selected-assignee")!.textContent).toBe("kuznetsov"));
    fill(form, "Отчёт", "Собрать данные");
    fireEvent.change(input(form, DUE), { target: { value: "2026-10-25" } });
    fireEvent.change(field(form, "priority"), { target: { value: "high" } });
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect(await body(f.last(PROJ_CREATE))).toEqual({
      title: "Отчёт",
      description: "Собрать данные",
      due_date: "2026-10-25",
      priority: "high",
      assignee_id: ID_KUZNETSOV,
    });
    // после 201 - значения по умолчанию (AC-28)
    await waitFor(() => expect(input(createForm(container)!, 'input[name="title"]').value).toBe(""));
    const after = createForm(container)!;
    expect(after.querySelector<HTMLTextAreaElement>('textarea[name="description"]')!.value).toBe("");
    expect(input(after, DUE).value).toBe(TODAY);
    expect(after.querySelector<HTMLSelectElement>('select[name="priority"]')!.value).toBe("medium");
    await waitFor(() => expect(f_(after, "selected-assignee")?.textContent).toBe("admin"));
    expect(alertTexts()).toEqual([]);
  });
});

describe("006 due date in the past from server (AC-32, FR-21)", () => {
  it("006_ac32_422_due_date_in_past_message_at_due_field_values_kept_resubmit_sends_new_request", async () => {
    freezeTime();
    let n = 0;
    const { container, f } = await open(
      "business_admin",
      { [PROJ_CREATE]: () => (n++ === 0 ? err(422, "due_date_in_past") : j(201, taskDetail())) },
      { perms: PERM_MANAGE },
    );
    const form = createForm(container)!;
    fill(form, "Отчёт", "Собрать данные");
    fireEvent.change(field(form, "priority"), { target: { value: "high" } });
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect(await screen.findByText(MSG.past)).toBeTruthy();
    const due = field(createForm(container)!, "due_date");
    expect(due.getAttribute("aria-invalid")).toBe("true");
    expect(describedText(due)).toBe(MSG.past);
    // единственное сообщение - у поля срока, общей области нет
    expect(alertTexts()).toEqual([MSG.past]);
    // введённое сохранено
    const kept = createForm(container)!;
    expect(input(kept, 'input[name="title"]').value).toBe("Отчёт");
    expect(kept.querySelector<HTMLTextAreaElement>('textarea[name="description"]')!.value).toBe("Собрать данные");
    expect(input(kept, DUE).value).toBe(TODAY);
    expect(kept.querySelector<HTMLSelectElement>('select[name="priority"]')!.value).toBe("high");
    expect(f_(kept, "selected-assignee")!.textContent).toBe("admin");
    // исправили срок - повторная отправка уходит новым запросом
    fireEvent.change(input(kept, DUE), { target: { value: "2026-10-21" } });
    submit(kept);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(2));
    expect((await body(f.last(PROJ_CREATE))).due_date).toBe("2026-10-21");
    await waitFor(() => expect(screen.queryByText(MSG.past)).toBeNull());
  });

  it("006_ac32_other_server_errors_still_go_to_common_alert_not_to_fields", async () => {
    freezeTime();
    const { container } = await open(
      "business_admin",
      { [PROJ_CREATE]: () => err(403, "forbidden") },
      { perms: PERM_MANAGE },
    );
    const form = createForm(container)!;
    fill(form, "Задача");
    submit(form);
    expect((await screen.findByRole("alert")).textContent).toBe(errorMessage("forbidden"));
    expect(field(createForm(container)!, "due_date").getAttribute("aria-invalid")).toBeNull();
  });
});
