// R7-T21 (spec 007): создание учётной записи агента и метка «ИИ» в «Учётных записях».
// AC: FR-40 (создание агента), FR-31 (метка), FR-2 (нет роли ТА у агента), FR-1 (нет сброса
// пароля); AC-37 - автотесты компонентов (сам AC ручной). Контракт - plan §4.10, шапка helpers.tsx.
// Заметки ревью: R7-T08 п.3 (роль ТА в форме агента не предлагается), R7-T19/T20 (пробел перед
// abbr: textContent «логин ИИ»).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  CAPS_ALL,
  ID_AGENT,
  ID_IVANOV,
  U_ADMIN,
  U_AGENT,
  U_IVANOV,
  U_PETROV,
  action,
  agentsUrl,
  cell,
  err,
  installFetch,
  j,
  meWith,
  mkUser,
  page,
  renderApp,
  row,
  type Handler,
} from "./helpers";

const DICT = Object.values(ru) as string[];
const LIST = "GET /api/v1/admin/users";
const ME = "GET /api/v1/me";
const CREATE_USER = "POST /api/v1/admin/users";
const CREATE_AGENT = `POST ${agentsUrl}`;
const MARK = "abbr.ui-agent-mark";

// Тексты - литералы plan §4.10 (словарь R7-T21).
const T_AGENT_LABEL = "Учётная запись ИИ-агента";
const T_AGENT_CREATED = "Учётная запись агента создана";
const T_KEYS = "Ключи";
const T_ROLE_NOT_ALLOWED = "Агенту нельзя назначить роль технического администратора";

const NEW_AGENT = mkUser({
  id: "99999999-9999-4999-8999-999999999999",
  login: "agent.new",
  role: "user",
  is_agent: true,
  must_change_password: false,
});

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

async function open(over: Record<string, Handler> = {}, caps: string[] = CAPS_ALL) {
  f = installFetch({
    [ME]: () => j(200, meWith(caps)),
    [LIST]: () => j(200, page([U_ADMIN, U_IVANOV, U_PETROV, U_AGENT])),
    ...over,
  });
  const view = renderApp("/admin/users");
  await waitFor(() => expect(view.container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy());
  return view;
}

function createForm(c: HTMLElement): HTMLFormElement {
  const form = c.querySelector<HTMLInputElement>('input[name="login"]')?.form;
  if (!form) throw new Error("no create form");
  return form;
}

function agentBox(c: HTMLElement): HTMLInputElement {
  const el = createForm(c).querySelector<HTMLInputElement>('input[type="checkbox"][name="is_agent"]');
  if (!el) throw new Error('no input[type=checkbox][name="is_agent"] in the create form');
  return el;
}

function formRole(c: HTMLElement): HTMLSelectElement | null {
  return createForm(c).querySelector<HTMLSelectElement>('select[name="role"]');
}

function submitAgent(c: HTMLElement, login: string, role?: string) {
  const box = agentBox(c);
  if (!box.checked) fireEvent.click(box);
  fireEvent.change(createForm(c).querySelector('input[name="login"]') as HTMLInputElement, {
    target: { value: login },
  });
  if (role !== undefined) {
    const sel = formRole(c);
    if (!sel) throw new Error("no role select in the agent form");
    fireEvent.change(sel, { target: { value: role } });
  }
  const submit = createForm(c).querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!submit) throw new Error("no submit");
  fireEvent.click(submit);
}

const shownPassword = () => document.querySelector('[data-role="one-time-password"]');
const actions = (r: HTMLElement) =>
  Array.from(r.querySelectorAll<HTMLButtonElement>("button[data-action]")).map((b) => b.dataset["action"]);

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("R7-T21 метка «ИИ» в «Учётных записях» (FR-31)", () => {
  it("007_fr31_agent_row_login_has_mark_with_space_human_rows_have_none", async () => {
    const { container } = await open();
    const login = cell(row(container, ID_AGENT), "login");
    const marks = login.querySelectorAll(MARK);
    expect(marks).toHaveLength(1);
    expect(marks[0]!.textContent).toBe("ИИ");
    expect(marks[0]!.getAttribute("title")).toBe("ИИ-агент");
    // ревью R7-T19/T20 п.2: логин и метка разделены пробелом (скринридеры)
    expect(login.textContent).toBe("agent.u ИИ");
    for (const id of [ID_IVANOV, U_PETROV.id, U_ADMIN.id]) {
      expect(cell(row(container, id), "login").querySelector(MARK)).toBeNull();
    }
    expect(cell(row(container, ID_IVANOV), "login").textContent).toBe("ivanov");
  });
});

describe("R7-T21 форма создания агента (FR-40, FR-2)", () => {
  it("007_fr40_agent_checkbox_has_label_and_shows_role_select_without_tech_admin", async () => {
    const { container } = await open();
    const box = agentBox(container);
    expect(box.checked).toBe(false);
    expect(box.labels?.[0]?.textContent).toBe(T_AGENT_LABEL);
    // без флажка - прежняя форма человека: выбора роли нет
    expect(formRole(container)).toBeNull();
    fireEvent.click(box);
    await waitFor(() => expect(formRole(container)).not.toBeNull());
    const sel = formRole(container)!;
    // ревью R7-T08 п.3: только П, БА и «без роли»; П по умолчанию
    expect(Array.from(sel.options).map((o) => o.value).sort()).toEqual(["", "business_admin", "user"]);
    expect(sel.value).toBe("user");
    for (const o of Array.from(sel.options)) expect(DICT).toContain(o.textContent);
    expect(sel.labels?.length || sel.getAttribute("aria-label")).toBeTruthy();
    // пароля у агента нет: ни поля, ни раскрытия
    expect(createForm(container).querySelector('input[type="password"]')).toBeNull();
    // флажок снят - выбора роли снова нет
    fireEvent.click(box);
    await waitFor(() => expect(formRole(container)).toBeNull());
  });

  it("007_fr40_submit_sends_exactly_one_post_admin_agents_with_login_and_role_user", async () => {
    const { container } = await open({ [CREATE_AGENT]: () => j(201, NEW_AGENT) });
    submitAgent(container, "agent.new");
    await waitFor(() => expect(f.count(CREATE_AGENT)).toBe(1));
    const req = f.last(CREATE_AGENT);
    expect(new URL(req.url).search).toBe("");
    expect(await req.clone().json()).toEqual({ login: "agent.new", role: "user" });
    expect(f.count(CREATE_USER)).toBe(0);
    await waitFor(() => expect(screen.getByText(T_AGENT_CREATED)).toBeTruthy());
    expect(f.count(CREATE_AGENT)).toBe(1);
  });

  it.each([
    ["business_admin", "business_admin"],
    ["", null],
  ])("007_fr2_role_%s_is_sent_as_selected", async (value, sent) => {
    const { container } = await open({ [CREATE_AGENT]: () => j(201, { ...NEW_AGENT, role: sent }) });
    submitAgent(container, "agent.new", value);
    await waitFor(() => expect(f.count(CREATE_AGENT)).toBe(1));
    expect(await f.last(CREATE_AGENT).clone().json()).toEqual({ login: "agent.new", role: sent });
  });

  it("007_fr40_success_shows_status_message_without_password_panel_and_reloads_list_with_mark", async () => {
    let created = false;
    const { container } = await open({
      [LIST]: () => j(200, page(created ? [U_ADMIN, U_IVANOV, NEW_AGENT] : [U_ADMIN, U_IVANOV])),
      [CREATE_AGENT]: () => ((created = true), j(201, NEW_AGENT)),
    });
    const before = f.count(LIST);
    submitAgent(container, "agent.new");
    const msg = await screen.findByText(T_AGENT_CREATED);
    // сообщение об успехе объявляется (aria-live / role="status"), а не как ошибка
    expect(msg.closest('[role="status"], [aria-live="polite"], [aria-live="assertive"]')).not.toBeNull();
    expect(msg.closest('[role="alert"]')).toBeNull();
    expect(shownPassword()).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(f.count(LIST)).toBeGreaterThan(before));
    await waitFor(() => expect(container.querySelector(`tr[data-user-id="${NEW_AGENT.id}"]`)).toBeTruthy());
    const login = cell(row(container, NEW_AGENT.id), "login");
    expect(login.querySelectorAll(MARK)).toHaveLength(1);
    expect(login.textContent).toBe("agent.new ИИ");
  });

  it.each([
    ["agent_role_not_allowed", T_ROLE_NOT_ALLOWED],
    ["login_taken", ru["error.login_taken"]],
  ])("007_fr40_422_%s_is_shown_via_error_message", async (code, text) => {
    const { container } = await open({ [CREATE_AGENT]: () => err(422, code) });
    submitAgent(container, "agent.new");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(alert.textContent).toBe(text);
    expect(alert.textContent).not.toBe(ru["error.unknown"]);
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(screen.queryByText(T_AGENT_CREATED)).toBeNull();
    expect(shownPassword()).toBeNull();
  });

  it("007_fr40_human_create_without_checkbox_is_unchanged", async () => {
    const created = { ...U_IVANOV, id: "33333333-3333-4333-8333-333333333333", login: "sidorov" };
    const { container } = await open({ [CREATE_USER]: () => j(201, created) });
    expect(agentBox(container).checked).toBe(false);
    fireEvent.change(createForm(container).querySelector('input[name="login"]') as HTMLInputElement, {
      target: { value: "sidorov" },
    });
    fireEvent.click(createForm(container).querySelector('button[type="submit"]') as HTMLButtonElement);
    await waitFor(() => expect(f.count(CREATE_USER)).toBe(1));
    const body = (await f.last(CREATE_USER).clone().json()) as Record<string, string>;
    expect(Object.keys(body).sort()).toEqual(["login", "one_time_password"]);
    expect(f.count(CREATE_AGENT)).toBe(0);
    await waitFor(() => expect(shownPassword()).not.toBeNull());
  });
});

describe("R7-T21 строка агента (FR-1, FR-2, FR-40)", () => {
  it("007_fr1_agent_row_has_no_reset_password_and_has_keys_button", async () => {
    const { container } = await open();
    const r = row(container, ID_AGENT);
    expect(r.querySelector('button[data-action="reset-password"]')).toBeNull();
    const keys = action(r, "keys");
    expect(keys.type).toBe("button");
    expect(keys.textContent?.trim()).toBe(T_KEYS);
    // кнопка не заглушка: не отключена (R7-T21)
    expect(keys.disabled).toBe(false);
    expect(action(r, "block")).toBeTruthy();
    expect(action(r, "revoke-sessions")).toBeTruthy();
  });

  it("007_fr2_agent_row_role_select_has_no_tech_admin", async () => {
    const { container } = await open();
    const sel = row(container, ID_AGENT).querySelector<HTMLSelectElement>('select[name="role"]');
    expect(sel).not.toBeNull();
    expect(Array.from(sel!.options).map((o) => o.value).sort()).toEqual(["", "business_admin", "user"]);
    expect(sel!.value).toBe("user");
    expect(sel!.getAttribute("aria-label") ?? sel!.labels?.[0]?.textContent).toBeTruthy();
  });

  it("007_fr40_human_rows_unchanged_no_keys_button_and_tech_admin_offered", async () => {
    const { container } = await open();
    for (const id of [ID_IVANOV, U_PETROV.id, U_ADMIN.id]) {
      const r = row(container, id);
      expect(r.querySelector('button[data-action="keys"]')).toBeNull();
      expect(action(r, "reset-password")).toBeTruthy();
      const sel = r.querySelector<HTMLSelectElement>('select[name="role"]')!;
      expect(Array.from(sel.options).map((o) => o.value).sort()).toEqual([
        "",
        "business_admin",
        "tech_admin",
        "user",
      ]);
    }
  });

  it("007_fr40_keys_button_present_with_manage_accounts_only", async () => {
    const { container } = await open({}, ["manage_accounts"]);
    const r = row(container, ID_AGENT);
    expect(action(r, "keys").textContent?.trim()).toBe(T_KEYS);
    expect(r.querySelector('select[name="role"]')).toBeNull();
    expect(actions(r)).not.toContain("reset-password");
  });
});

describe("R7-T21 доступность (NFR-7)", () => {
  it("007_fr40_every_control_with_agent_row_and_agent_form_has_accessible_name", async () => {
    const { container } = await open();
    fireEvent.click(agentBox(container));
    await waitFor(() => expect(formRole(container)).not.toBeNull());
    for (const el of Array.from(container.querySelectorAll("input, select"))) {
      const named =
        (el as HTMLInputElement).labels?.length ||
        el.getAttribute("aria-label") ||
        el.getAttribute("aria-labelledby");
      expect(named, el.outerHTML).toBeTruthy();
    }
    for (const b of Array.from(container.querySelectorAll<HTMLButtonElement>("button"))) {
      expect(b.textContent?.trim() || b.getAttribute("aria-label"), b.outerHTML).toBeTruthy();
      expect(["button", "submit"]).toContain(b.type);
    }
  });
});
