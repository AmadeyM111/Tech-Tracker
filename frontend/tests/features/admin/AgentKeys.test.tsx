// R7-T22 (spec 007): ключи агента в «Учётных записях» - перечень, выпуск с однократным показом
// секрета, отзыв с подтверждением. AC: FR-40, FR-6 (интерфейс), FR-7; AC-37 - автотесты
// компонентов (сам AC ручной). Контракт - plan §4.10, PD-17 (секрет только в useState, без
// useMutation и кэша запросов), шапка helpers.tsx.
// Секрет в сообщениях assert не выводится: сравнения через boolean (tasks.md, «Общие условия»).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { errorMessage } from "../../../src/shared/i18n";
import {
  CAPS_ALL,
  ID_AGENT,
  ID_AGENT_BA,
  NO_CONTENT,
  U_ADMIN,
  U_AGENT,
  U_AGENT_BA,
  U_IVANOV,
  action,
  cacheText,
  deferred,
  err,
  installClipboard,
  installFetch,
  j,
  keysUrl,
  meWith,
  mkKey,
  page,
  renderApp,
  revokeUrl,
  row,
  where,
  type Handler,
} from "./helpers";

const LIST = "GET /api/v1/admin/users";
const ME = "GET /api/v1/me";
const KEYS = `GET ${keysUrl(ID_AGENT)}`;
const KEYS_BA = `GET ${keysUrl(ID_AGENT_BA)}`;
const ISSUE = `POST ${keysUrl(ID_AGENT)}`;

// Тексты - литералы plan §4.10.
const T_LIMIT = "У агента уже 5 действующих ключей";
const T_ISSUE = "Выпустить ключ";
const T_WARNING = "Скопируйте ключ сейчас: после закрытия окна он не будет показан";

// Фиктивный секрет формата gtk_ (не настоящий ключ).
const SECRET = "gtk_TESTONLYsecretValue0123456789abcdefghijklmnopq";
const CLOCK = new Date("2026-11-02T07:00:00Z"); // 10:00 по Москве (spec §5)

const K1 = mkKey({
  id: "a1a1a1a1-0000-4000-8000-000000000001",
  name: "claude-laptop",
  last_used_at: "2026-11-02T07:00:00Z",
});
const K2 = mkKey({ id: "a1a1a1a1-0000-4000-8000-000000000002", name: "ci-runner" });
const K3 = mkKey({
  id: "a1a1a1a1-0000-4000-8000-000000000003",
  name: "old-key",
  expires_at: "2026-10-31T08:00:00Z",
  state: "expired",
});
const K4 = mkKey({
  id: "a1a1a1a1-0000-4000-8000-000000000004",
  name: "gone-key",
  revoked_at: "2026-11-02T07:00:00Z",
  state: "revoked",
});
const ISSUED_KEY = mkKey({
  id: "a1a1a1a1-0000-4000-8000-000000000005",
  name: "new-laptop",
  created_at: CLOCK.toISOString(),
  expires_at: "2027-01-31T07:00:00Z",
});

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;
let clip: ReturnType<typeof installClipboard> | null = null;

async function open(over: Record<string, Handler> = {}) {
  f = installFetch({
    [ME]: () => j(200, meWith(CAPS_ALL)),
    [LIST]: () => j(200, page([U_ADMIN, U_IVANOV, U_AGENT, U_AGENT_BA])),
    [KEYS]: () => j(200, page([K1, K2, K3, K4])),
    [KEYS_BA]: () => j(200, page([])),
    ...over,
  });
  const view = renderApp("/admin/users");
  await waitFor(() => expect(view.container.querySelector(`tr[data-user-id="${ID_AGENT}"]`)).toBeTruthy());
  return view;
}

const sections = () => Array.from(document.querySelectorAll<HTMLElement>('section[data-section="agent-keys"]'));

function sectionFor(login: string): HTMLElement | null {
  return sections().find((s) => s.querySelector("h1, h2, h3, h4")?.textContent?.includes(login)) ?? null;
}

/** Открывает раздел ключей агента кнопкой «Ключи» (повторный клик, если кнопка переключает). */
async function openKeys(container: HTMLElement, userId: string, login: string): Promise<HTMLElement> {
  if (sectionFor(login) === null) fireEvent.click(action(row(container, userId), "keys"));
  await waitFor(() => expect(sectionFor(login)).not.toBeNull());
  return sectionFor(login)!;
}

function keyRow(section: HTMLElement, name: string): HTMLElement {
  const tr = Array.from(section.querySelectorAll<HTMLElement>("tbody tr")).find((r) => r.textContent?.includes(name));
  if (!tr) throw new Error(`no key row ${name}`);
  return tr;
}

async function openWithKeys(over: Record<string, Handler> = {}) {
  const view = await open(over);
  const section = await openKeys(view.container, ID_AGENT, "agent.u");
  await waitFor(() => expect(section.querySelectorAll("tbody tr").length).toBeGreaterThan(0));
  return { ...view, section };
}

function issueForm(section: HTMLElement) {
  const ttl = section.querySelector<HTMLSelectElement>('select[name="expires_in_days"]');
  if (!ttl) throw new Error('no select[name="expires_in_days"]');
  const form = ttl.form;
  if (!form) throw new Error("expires_in_days is not inside a form");
  const name = Array.from(form.querySelectorAll<HTMLInputElement>("input")).find(
    (i) => i.type === "text" || i.type === "",
  );
  if (!name) throw new Error("no name input in the issue form");
  const submit = within(form).getByRole("button", { name: T_ISSUE });
  return { form, ttl, name, submit };
}

function issue(section: HTMLElement, name: string, ttl?: string): void {
  const fm = issueForm(section);
  fireEvent.change(fm.name, { target: { value: name } });
  if (ttl !== undefined) fireEvent.change(fm.ttl, { target: { value: ttl } });
  fireEvent.click(fm.submit);
}

function secretInput(dialog: HTMLElement): HTMLInputElement {
  const el = dialog.querySelector<HTMLInputElement>("input");
  if (!el) throw new Error("no secret input in the dialog");
  return el;
}

const issuedOk = () => j(201, { key: ISSUED_KEY, secret: SECRET });

beforeEach(() => {
  vi.stubEnv("TZ", "UTC");
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(CLOCK);
  window.localStorage.clear();
  window.sessionStorage.clear();
  clip = installClipboard();
});

afterEach(() => {
  clip?.restore();
  clip = null;
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("R7-T22 раздел ключей и перечень (FR-7, FR-40)", () => {
  it("007_fr40_keys_button_opens_section_with_heading_and_requests_first_page", async () => {
    const { container } = await open();
    expect(f.count(KEYS)).toBe(0);
    const section = await openKeys(container, ID_AGENT, "agent.u");
    const heading = section.querySelector("h1, h2, h3, h4")!;
    expect(heading.textContent).toContain("Ключи доступа");
    expect(heading.textContent).toContain("agent.u");
    await waitFor(() => expect(f.count(KEYS)).toBe(1));
    expect(f.query(f.last(KEYS)).get("page")).toBe("1");
  });

  it("007_fr7_states_active_expired_revoked_with_moscow_time_and_never_used", async () => {
    const { section } = await openWithKeys();
    const r1 = keyRow(section, "claude-laptop");
    const r2 = keyRow(section, "ci-runner");
    const r3 = keyRow(section, "old-key");
    const r4 = keyRow(section, "gone-key");
    expect(r1.textContent).toMatch(/действует/i);
    expect(r2.textContent).toMatch(/действует/i);
    expect(r3.textContent).toMatch(/истёк/i);
    expect(r3.textContent).not.toMatch(/действует/i);
    expect(r4.textContent).toMatch(/отозван/i);
    expect(r4.textContent).not.toMatch(/действует/i);
    // время отзыва - по Москве: 07:00Z -> 02.11.2026 10:00
    expect(r4.textContent).toContain("02.11.2026");
    expect(r4.textContent).toContain("10:00");
    // последнее использование: время по Москве или «не использовался»
    expect(r1.textContent).toContain("10:00");
    expect(r1.textContent).not.toMatch(/не использовался/i);
    expect(r2.textContent).toMatch(/не использовался/i);
    // кто и когда выпустил, срок (08:00Z -> 11:00 МСК)
    expect(r1.textContent).toContain("admin");
    expect(r1.textContent).toContain("01.10.2026");
    expect(r1.textContent).toContain("30.12.2026");
    for (const r of [r1, r2, r3, r4]) {
      expect(r.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
      expect(r.textContent).not.toContain("07:00");
      expect(r.textContent).not.toMatch(/\b(active|expired|revoked)\b/);
    }
  });

  it("007_fr8_revoke_button_only_for_active_keys", async () => {
    const { section } = await openWithKeys();
    for (const name of ["claude-laptop", "ci-runner"]) {
      expect(within(keyRow(section, name)).getAllByRole("button", { name: /Отозвать/ })).toHaveLength(1);
    }
    for (const name of ["old-key", "gone-key"]) {
      expect(within(keyRow(section, name)).queryByRole("button", { name: /Отозвать/ })).toBeNull();
    }
  });

  it("007_fr7_pagination_requests_next_page_inside_section", async () => {
    const { section } = await openWithKeys({
      [KEYS]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([p === 1 ? K1 : K2], p, p === 1));
      },
    });
    expect(action(section, "prev-page").disabled).toBe(true);
    fireEvent.click(action(section, "next-page"));
    await waitFor(() => expect(f.query(f.last(KEYS)).get("page")).toBe("2"));
    await waitFor(() => expect(keyRow(section, "ci-runner")).toBeTruthy());
    expect(action(section, "next-page").disabled).toBe(true);
    expect(action(section, "prev-page").disabled).toBe(false);
  });

  it("007_fr7_list_never_contains_secret_like_values", async () => {
    const { section } = await openWithKeys();
    expect(section.textContent).not.toContain("gtk_");
  });
});

describe("R7-T22 выпуск ключа (FR-5, FR-9, FR-40)", () => {
  it("007_fr40_issue_form_has_labelled_name_and_ttl_select_with_default_90", async () => {
    const { section } = await openWithKeys();
    const fm = issueForm(section);
    expect(fm.name.labels?.length || fm.name.getAttribute("aria-label")).toBeTruthy();
    expect(fm.ttl.labels?.length || fm.ttl.getAttribute("aria-label")).toBeTruthy();
    expect(Array.from(fm.ttl.options).map((o) => o.value)).toEqual(["30", "90", "180", "365"]);
    expect(fm.ttl.value).toBe("90");
    expect(fm.submit.getAttribute("type") ?? "submit").toBe("submit");
  });

  it("007_fr9_issue_sends_one_post_with_name_and_numeric_expires_in_days_90", async () => {
    const { section } = await openWithKeys({ [ISSUE]: issuedOk });
    issue(section, "new-laptop");
    await waitFor(() => expect(f.count(ISSUE)).toBe(1));
    const body = (await f.last(ISSUE).clone().json()) as Record<string, unknown>;
    // ревью R7-T10: целое число JSON, не строка (сервер strict)
    expect(body).toEqual({ name: "new-laptop", expires_in_days: 90 });
    expect(typeof body["expires_in_days"]).toBe("number");
    expect(new URL(f.last(ISSUE).url).search).toBe("");
    await screen.findByRole("dialog");
    expect(f.count(ISSUE)).toBe(1);
  });

  it.each([["30", 30], ["180", 180], ["365", 365]])(
    "007_fr9_issue_with_ttl_%s_sends_number",
    async (value, sent) => {
      const { section } = await openWithKeys({ [ISSUE]: issuedOk });
      issue(section, "new-laptop", value);
      await waitFor(() => expect(f.count(ISSUE)).toBe(1));
      expect(await f.last(ISSUE).clone().json()).toEqual({ name: "new-laptop", expires_in_days: sent });
    },
  );

  it("007_fr40_double_submit_while_issue_in_flight_sends_one_post", async () => {
    const d = deferred<Response>();
    const { section } = await openWithKeys({ [ISSUE]: () => d.promise });
    const fm = issueForm(section);
    fireEvent.change(fm.name, { target: { value: "new-laptop" } });
    fireEvent.click(fm.submit);
    fireEvent.click(fm.submit);
    fireEvent.submit(fm.form);
    await waitFor(() => expect(f.count(ISSUE)).toBe(1));
    d.resolve(issuedOk());
    await screen.findByRole("dialog");
    expect(f.count(ISSUE)).toBe(1);
  });

  it("007_fr10_422_api_key_limit_reached_is_shown_without_dialog", async () => {
    const { section } = await openWithKeys({ [ISSUE]: () => err(422, "api_key_limit_reached") });
    issue(section, "sixth");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("api_key_limit_reached"));
    expect(alert.textContent).toBe(T_LIMIT);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("007_fr40_list_is_reloaded_after_issue", async () => {
    let issued = false;
    const { section } = await openWithKeys({
      [KEYS]: () => j(200, page(issued ? [ISSUED_KEY, K1] : [K1])),
      [ISSUE]: () => ((issued = true), issuedOk()),
    });
    const before = f.count(KEYS);
    issue(section, "new-laptop");
    await screen.findByRole("dialog");
    await waitFor(() => expect(f.count(KEYS)).toBeGreaterThan(before));
    await waitFor(() => expect(keyRow(sectionFor("agent.u")!, "new-laptop")).toBeTruthy());
  });
});

describe("R7-T22 окно секрета (FR-6, FR-40, PD-17)", () => {
  async function issueAndShow() {
    const view = await openWithKeys({ [ISSUE]: issuedOk });
    const opener = issueForm(view.section).submit;
    opener.focus();
    issue(view.section, "new-laptop");
    const dialog = await screen.findByRole("dialog");
    return { ...view, dialog, opener };
  }

  it("007_fr6_dialog_shows_secret_in_readonly_field_with_warning", async () => {
    const { dialog } = await issueAndShow();
    const input = secretInput(dialog);
    expect(input.value === SECRET).toBe(true);
    expect(input.readOnly).toBe(true);
    expect(input.labels?.length || input.getAttribute("aria-label") || input.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog.textContent).toContain(T_WARNING);
    expect(dialog.getAttribute("aria-labelledby") || dialog.getAttribute("aria-label")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: /Копировать/ })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: /Закрыть/ })).toBeTruthy();
  });

  it("007_fr40_focus_moves_into_dialog_and_returns_to_section_after_close", async () => {
    const { dialog } = await issueAndShow();
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.click(within(dialog).getByRole("button", { name: /Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => {
      const active = document.activeElement;
      expect(active).not.toBe(document.body);
      expect(active !== null && sectionFor("agent.u")!.contains(active)).toBe(true);
    });
  });

  it("007_fr40_copy_writes_exact_secret_to_clipboard_and_announces_copied", async () => {
    const { dialog } = await issueAndShow();
    fireEvent.click(within(dialog).getByRole("button", { name: /Копировать/ }));
    await waitFor(() => expect(clip!.writeText).toHaveBeenCalledTimes(1));
    expect(clip!.writeText.mock.calls[0]?.[0] === SECRET).toBe(true);
    const copied = await within(dialog).findByText(/Скопировано/);
    expect(copied.closest('[role="status"], [aria-live="polite"], [aria-live="assertive"]')).not.toBeNull();
    // окно не закрывается само после копирования
    expect(screen.getByRole("dialog")).toBe(dialog);
  });

  it("007_fr40_clipboard_failure_keeps_dialog_and_secret_and_does_not_log_it", async () => {
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    clip!.restore();
    clip = installClipboard(async () => {
      throw new DOMException("denied", "NotAllowedError");
    });
    const { dialog } = await issueAndShow();
    fireEvent.click(within(dialog).getByRole("button", { name: /Копировать/ }));
    await waitFor(() => expect(clip!.writeText).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("dialog")).toBe(dialog));
    expect(secretInput(dialog).value === SECRET).toBe(true);
    for (const l of logs) expect(JSON.stringify(l.mock.calls).includes(SECRET)).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: /Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("007_pd17_secret_never_in_query_or_mutation_cache_while_open_and_after_close", async () => {
    const { dialog, qc } = await issueAndShow();
    expect(secretInput(dialog).value === SECRET).toBe(true);
    // PD-17: без useMutation (data мутации держит ответ) и без записи в кэш запросов
    expect(cacheText(qc).includes(SECRET)).toBe(false);
    expect(qc.getMutationCache().getAll().some((m) => JSON.stringify(m.state.data ?? null).includes("gtk_"))).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: /Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(cacheText(qc).includes(SECRET)).toBe(false);
  });

  it("007_fr6_after_close_secret_is_nowhere_in_dom_storage_url_or_history", async () => {
    const { dialog, container } = await issueAndShow();
    fireEvent.click(within(dialog).getByRole("button", { name: /Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.body.innerHTML.includes(SECRET)).toBe(false);
    expect(container.innerHTML.includes(SECRET)).toBe(false);
    for (const input of Array.from(document.querySelectorAll("input"))) {
      expect(input.value.includes(SECRET)).toBe(false);
    }
    expect(JSON.stringify({ ...window.localStorage }).includes(SECRET)).toBe(false);
    expect(JSON.stringify({ ...window.sessionStorage }).includes(SECRET)).toBe(false);
    expect((where() ?? "").includes(SECRET)).toBe(false);
    expect(window.location.href.includes(SECRET)).toBe(false);
    expect(JSON.stringify(window.history.state ?? null).includes(SECRET)).toBe(false);
    for (const c of f.calls) expect(c.url.includes(SECRET)).toBe(false);
  });

  it("007_fr40_reopening_keys_section_does_not_show_secret_again", async () => {
    const { dialog, container, qc } = await issueAndShow();
    fireEvent.click(within(dialog).getByRole("button", { name: /Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // переход к ключам другого агента и обратно
    await openKeys(container, ID_AGENT_BA, "agent.ba");
    const again = await openKeys(container, ID_AGENT, "agent.u");
    await waitFor(() => expect(f.count(KEYS)).toBeGreaterThanOrEqual(2));
    expect(again).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.innerHTML.includes(SECRET)).toBe(false);
    expect(cacheText(qc).includes(SECRET)).toBe(false);
  });

  it("007_fr6_new_issue_does_not_show_previous_secret", async () => {
    const SECOND = "gtk_TESTONLYsecondValue9876543210zyxwvutsrqponmlkjih";
    let n = 0;
    const { section } = await openWithKeys({
      [ISSUE]: () => {
        n += 1;
        return j(201, { key: ISSUED_KEY, secret: n === 1 ? SECRET : SECOND });
      },
    });
    issue(section, "new-laptop");
    let dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    issue(sectionFor("agent.u")!, "other");
    dialog = await screen.findByRole("dialog");
    expect(secretInput(dialog).value === SECOND).toBe(true);
    expect(document.body.innerHTML.includes(SECRET)).toBe(false);
  });
});

describe("R7-T22 отзыв ключа (FR-8, FR-40)", () => {
  const REVOKE = `POST ${revokeUrl(ID_AGENT, K1.id)}`;

  function revokeButton(section: HTMLElement): HTMLButtonElement {
    return within(keyRow(section, "claude-laptop")).getByRole("button", { name: /Отозвать/ }) as HTMLButtonElement;
  }

  it("007_fr8_revoke_opens_confirm_dialog_and_cancel_sends_nothing", async () => {
    const { section } = await openWithKeys({ [REVOKE]: NO_CONTENT });
    const opener = revokeButton(section);
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("Отозвать ключ «claude-laptop»?");
    expect(dialog.textContent).toContain("Действие необратимо");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.click(action(dialog, "cancel"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(REVOKE)).toBe(0);
    expect(f.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("007_fr8_confirm_sends_one_revoke_and_row_becomes_revoked", async () => {
    let revoked = false;
    const { section } = await openWithKeys({
      [KEYS]: () =>
        j(200, page([revoked ? { ...K1, state: "revoked", revoked_at: "2026-11-02T07:00:00Z" } : K1, K2])),
      [REVOKE]: () => ((revoked = true), NO_CONTENT()),
    });
    const before = f.count(KEYS);
    fireEvent.click(revokeButton(section));
    const confirm = action(await screen.findByRole("alertdialog"), "confirm");
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(f.count(REVOKE)).toBe(1));
    await waitFor(() => expect(f.count(KEYS)).toBeGreaterThan(before));
    await waitFor(() => expect(keyRow(sectionFor("agent.u")!, "claude-laptop").textContent).toMatch(/отозван/i));
    const r = keyRow(sectionFor("agent.u")!, "claude-laptop");
    expect(r.textContent).not.toMatch(/действует/i);
    expect(within(r).queryByRole("button", { name: /Отозвать/ })).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(f.count(REVOKE)).toBe(1);
    expect(f.calls.filter((c) => c.method === "POST").map((c) => new URL(c.url).pathname)).toEqual([
      revokeUrl(ID_AGENT, K1.id),
    ]);
  });

  it("007_fr8_revoke_error_is_shown_via_error_message", async () => {
    const { section } = await openWithKeys({ [REVOKE]: () => err(404, "not_found") });
    fireEvent.click(revokeButton(section));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("not_found"));
  });
});
