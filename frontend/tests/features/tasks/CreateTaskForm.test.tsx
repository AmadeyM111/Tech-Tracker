// T83: форма создания задачи на вкладке «Задачи».
// AC: UF-3, UF-6, FR-20 (П: поле исполнителя не отправляется; «без исполнителя» - только БА/СМ),
//     FR-26, AC-56, AC-109 (интерфейс), NFR-5 (срок YYYY-MM-DD без пересчёта пояса), NFR-6, NFR-7.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
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

type Role = "business_admin" | "mixed" | "user";

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
const picker = () => screen.getByRole("combobox", { name: ru["tasks.assignee_label"] });
const submit = (form: HTMLFormElement) => fireEvent.submit(form);

function fill(form: HTMLFormElement, title: string) {
  fireEvent.change(input(form, 'input[name="title"]'), { target: { value: title } });
}

describe("create task form", () => {
  it("uf3_form_present_with_fields_when_permission_and_absent_without", async () => {
    const { container } = await open("business_admin", {}, { perms: PERM_MANAGE });
    const form = createForm(container)!;
    expect(form).toBeTruthy();
    expect(input(form, 'input[name="title"]')).toBeTruthy();
    expect(form.querySelector('textarea[name="description"]')).toBeTruthy();
    expect(input(form, 'input[type="date"][name="due_date"]')).toBeTruthy();
    const prio = form.querySelector<HTMLSelectElement>('select[name="priority"]')!;
    expect(Array.from(prio.options).map((o) => o.value)).toEqual(["base", "high"]);
    expect(prio.value).toBe("base");
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
    expect(screen.queryByRole("combobox", { name: ru["tasks.assignee_label"] })).toBeNull();
    fill(form, "  Моя задача  ");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = await body(f.last(PROJ_CREATE));
    expect("assignee_id" in b).toBe(false);
    expect(b.title).toBe("Моя задача");
    expect(b.priority).toBe("base");
  });

  it("fr20_ba_without_choice_sends_no_assignee_or_null_never_self", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    expect(picker()).toBeTruthy();
    fill(createForm(container)!, "Без исполнителя");
    submit(createForm(container)!);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    const b = await body(f.last(PROJ_CREATE));
    expect(b.assignee_id ?? null).toBeNull();
  });

  it("fr20_mixed_role_also_gets_picker", async () => {
    await open("mixed", {}, { perms: PERM_MANAGE });
    expect(picker()).toBeTruthy();
  });

  it("fr20_ba_picks_member_and_assignee_id_is_sent_then_clear_removes_it", async () => {
    const { container, f } = await open(
      "business_admin",
      { [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])) },
      { perms: PERM_MANAGE },
    );
    fireEvent.change(picker(), { target: { value: "kuz" } });
    fireEvent.click((await within(await screen.findByRole("listbox", { name: ru["tasks.assignee_label"] })).findAllByRole("option"))[0]!);
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
    fireEvent.click((await within(await screen.findByRole("listbox", { name: ru["tasks.assignee_label"] })).findAllByRole("option"))[0]!);
    const form = createForm(container)!;
    await waitFor(() => expect(f_(form, "selected-assignee")).toBeTruthy());
    fireEvent.click(form.querySelector('button[data-action="clear-assignee"]')!);
    await waitFor(() => expect(f_(form, "selected-assignee")).toBeNull());
    fill(form, "Снова без");
    submit(form);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect((await body(f.last(PROJ_CREATE))).assignee_id ?? null).toBeNull();
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
    const list = await screen.findByRole("listbox", { name: ru["tasks.assignee_label"] });
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

  it("nfr5_empty_due_date_is_not_sent_as_string", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    fill(createForm(container)!, "Без срока");
    submit(createForm(container)!);
    await waitFor(() => expect(f.count(PROJ_CREATE)).toBe(1));
    expect((await body(f.last(PROJ_CREATE))).due_date ?? null).toBeNull();
  });

  it("ac96_empty_title_blocks_request_and_shows_validation_alert", async () => {
    const { container, f } = await open("business_admin", {}, { perms: PERM_MANAGE });
    fill(createForm(container)!, "   ");
    submit(createForm(container)!);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
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
    for (const l of Array.from(form.querySelectorAll("label"))) expect(dict).toContain(l.textContent);
  });
});
