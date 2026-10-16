// T81: UserPicker (выбор пользователя из справочника GET /users).
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ
//   src/features/users/api.ts
//     export type DirectoryUser = { id: string; login: string; role: Role }
//     listDirectory(p: { q?: string; page?: number; pageSize?: number }): Promise<Page<DirectoryUser>>
//       GET /api/v1/users?q=&page=&page_size= (параметр только если задан; пустой q не передаётся);
//       не-2xx и сеть -> ApiError; заголовка X-GT-Background нет.
//   src/shared/ui/UserPicker.tsx
//     export function UserPicker(props: {
//       label: string;                       // видимая подпись поля (label for=input)
//       onSelect: (user: DirectoryUser) => void;
//       allowedIds?: readonly string[];      // если задан - показываются только эти id (участники)
//       disabled?: boolean;
//     })
//   Разметка: input[role="combobox"] с доступным именем = label, aria-autocomplete="list",
//     aria-expanded ("true" пока список открыт), aria-controls -> id элемента role="listbox",
//     aria-activedescendant -> id активного role="option" (атрибута нет, пока активного нет).
//     Активный option имеет aria-selected="true", остальные "false"; текст option содержит login.
//   Поиск: ввод текста -> GET /api/v1/users?q=<введённое> с дебаунсом (запросы на промежуточные
//     значения при быстром наборе не уходят; последнее значение - ровно один запрос).
//   Клавиши: ArrowDown открывает список/двигает активный вниз (первый раз - первый option);
//     ArrowUp - вверх; Enter выбирает активный (onSelect(user)); без активного - ничего;
//     Escape закрывает список без выбора; клик по option выбирает.
//     После выбора: список закрыт, в input - login, фокус на input.
//   allowedIds: фильтр на клиенте по id из ответа; q на сервер при этом уходит как обычно.
//   Пусто (после фильтра тоже): нет option, показан [role="status"] с текстом из словаря.
//   Ошибка запроса: p[role="alert"] с errorMessage(code), option нет, поле остаётся рабочим.
// AC: FR-10 (получатели - только из справочника), NFR-6, NFR-7 (клавиатура, aria).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { listDirectory } from "../../src/features/users/api";
import { errorMessage, ru } from "../../src/shared/i18n";
import { UserPicker } from "../../src/shared/ui/UserPicker";
import { deferred, err, installFetch, j, page } from "../features/admin/helpers";

const DICT = Object.values(ru) as string[];
const USERS = "GET /api/v1/users";
const A = { id: "11111111-1111-4111-8111-111111111111", login: "ivanov", role: "user" };
const B = { id: "22222222-2222-4222-8222-222222222222", login: "ivanova", role: "business_admin" };
const C = { id: "33333333-3333-4333-8333-333333333333", login: "petrov", role: "business_admin" };

function setup(props: Partial<ComponentProps<typeof UserPicker>> = {}) {
  const onSelect = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <UserPicker label="Исполнитель" onSelect={onSelect} {...props} />
    </QueryClientProvider>,
  );
  const input = screen.getByRole("combobox", { name: "Исполнитель" });
  return { input, onSelect };
}

const type = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } });
const key = (input: HTMLElement, k: string) => fireEvent.keyDown(input, { key: k });
const options = () => screen.queryAllByRole("option");

describe("listDirectory (api)", () => {
  it("ac_api_sends_q_and_paging_without_background_header", async () => {
    const f = installFetch({ [USERS]: () => j(200, page([A])) });
    const res = await listDirectory({ q: "iv", page: 2, pageSize: 20 });
    expect(res.items).toEqual([A]);
    const r = f.last(USERS);
    const q = f.query(r);
    expect(q.get("q")).toBe("iv");
    expect(q.get("page")).toBe("2");
    expect(q.get("page_size")).toBe("20");
    expect(r.headers.get("X-GT-Background")).toBeNull();
  });

  it("ac_api_omits_unset_params", async () => {
    const f = installFetch({ [USERS]: () => j(200, page([])) });
    await listDirectory({});
    expect(f.query(f.last(USERS)).has("q")).toBe(false);
  });

  it("ac_api_error_is_api_error_with_code", async () => {
    installFetch({ [USERS]: () => err(403, "no_role") });
    await expect(listDirectory({ q: "x" })).rejects.toMatchObject({ status: 403, code: "no_role" });
  });
});

describe("UserPicker search", () => {
  it("ac_search_debounces_rapid_typing_into_one_request", async () => {
    const f = installFetch({ [USERS]: () => j(200, page([A, B])) });
    const { input } = setup();
    type(input, "i");
    type(input, "iv");
    type(input, "iva");
    await waitFor(() => expect(f.count(USERS)).toBe(1));
    expect(f.query(f.last(USERS)).get("q")).toBe("iva");
    await new Promise((r) => setTimeout(r, 600));
    expect(f.count(USERS)).toBe(1);
  });

  it("ac_search_shows_options_with_logins", async () => {
    installFetch({ [USERS]: () => j(200, page([A, B])) });
    const { input } = setup();
    type(input, "iv");
    await screen.findAllByRole("option");
    expect(options().map((o) => o.textContent)).toEqual([
      expect.stringContaining("ivanov"),
      expect.stringContaining("ivanova"),
    ]);
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-autocomplete")).toBe("list");
    const listbox = screen.getByRole("listbox");
    expect(listbox.id).not.toBe("");
    expect(input.getAttribute("aria-controls")).toBe(listbox.id);
    expect(within(listbox).getAllByRole("option").length).toBe(2);
  });

  it("ac_search_empty_result_shows_dictionary_status_and_no_options", async () => {
    installFetch({ [USERS]: () => j(200, page([])) });
    const { input } = setup();
    type(input, "zzz");
    await waitFor(() => expect(DICT).toContain(screen.getByRole("status").textContent));
    expect(screen.getByRole("status").textContent).toBe(ru["user_picker.empty"]);
    expect(options()).toEqual([]);
  });

  it("ac_search_error_uses_error_message_and_keeps_field_usable", async () => {
    let fail = true;
    installFetch({ [USERS]: () => (fail ? err(500, "internal_error") : j(200, page([A]))) });
    const { input } = setup();
    type(input, "iv");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("internal_error"));
    expect(options()).toEqual([]);
    fail = false;
    type(input, "ivan");
    await screen.findAllByRole("option");
  });

  it("ac_search_network_error_message_from_dictionary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("boom");
      }),
    );
    const { input } = setup();
    type(input, "iv");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("network_error"));
  });
});

describe("UserPicker keyboard and aria (NFR-7)", () => {
  async function open() {
    installFetch({ [USERS]: () => j(200, page([A, B, C])) });
    const ctx = setup();
    ctx.input.focus();
    type(ctx.input, "i");
    await screen.findAllByRole("option");
    return ctx;
  }

  it("ac_keys_arrows_move_activedescendant_and_aria_selected", async () => {
    const { input } = await open();
    expect(input.getAttribute("aria-activedescendant")).toBeNull();
    key(input, "ArrowDown");
    const [o1, o2] = options();
    expect(input.getAttribute("aria-activedescendant")).toBe(o1!.id);
    expect(o1!.getAttribute("aria-selected")).toBe("true");
    key(input, "ArrowDown");
    expect(input.getAttribute("aria-activedescendant")).toBe(o2!.id);
    expect(o1!.getAttribute("aria-selected")).toBe("false");
    key(input, "ArrowUp");
    expect(input.getAttribute("aria-activedescendant")).toBe(o1!.id);
    expect(new Set(options().map((o) => o.id)).size).toBe(3);
  });

  it("ac_keys_enter_selects_active_option", async () => {
    const { input, onSelect } = await open();
    key(input, "ArrowDown");
    key(input, "ArrowDown");
    key(input, "Enter");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(B);
    expect((input as HTMLInputElement).value).toBe("ivanova");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(input);
  });

  it("ac_keys_enter_without_active_option_selects_nothing", async () => {
    const { input, onSelect } = await open();
    key(input, "Enter");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("ac_keys_escape_closes_without_selection_and_keeps_focus", async () => {
    const { input, onSelect } = await open();
    key(input, "ArrowDown");
    key(input, "Escape");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(input.getAttribute("aria-activedescendant")).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(input);
  });

  it("ac_click_selects_option", async () => {
    const { input, onSelect } = await open();
    fireEvent.click(options()[2]!);
    expect(onSelect).toHaveBeenCalledWith(C);
    expect((input as HTMLInputElement).value).toBe("petrov");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("ac_reselect_after_new_search_calls_on_select_again", async () => {
    const { input, onSelect } = await open();
    key(input, "ArrowDown");
    key(input, "Enter");
    expect(onSelect).toHaveBeenLastCalledWith(A);
    type(input, "pet");
    await screen.findAllByRole("option");
    key(input, "ArrowDown");
    key(input, "ArrowDown");
    key(input, "ArrowDown");
    key(input, "Enter");
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onSelect).toHaveBeenLastCalledWith(C);
  });
});

describe("UserPicker allowedIds (project members)", () => {
  it("ac_allowed_ids_filters_options_to_the_given_set", async () => {
    installFetch({ [USERS]: () => j(200, page([A, B, C])) });
    const { input } = setup({ allowedIds: [A.id, C.id] });
    type(input, "i");
    await screen.findAllByRole("option");
    const texts = options().map((o) => o.textContent ?? "");
    expect(texts.length).toBe(2);
    expect(texts.some((x) => x.includes("ivanov") && !x.includes("ivanova"))).toBe(true);
    expect(texts.some((x) => x.includes("petrov"))).toBe(true);
    expect(texts.some((x) => x.includes("ivanova"))).toBe(false);
  });

  it("ac_allowed_ids_no_match_shows_empty_status", async () => {
    installFetch({ [USERS]: () => j(200, page([B])) });
    const { input } = setup({ allowedIds: [A.id] });
    type(input, "iv");
    await waitFor(() => expect(DICT).toContain(screen.getByRole("status").textContent));
    expect(options()).toEqual([]);
  });

  it("ac_allowed_ids_empty_set_allows_nobody", async () => {
    installFetch({ [USERS]: () => j(200, page([A])) });
    const { input, onSelect } = setup({ allowedIds: [] });
    type(input, "iv");
    await waitFor(() => expect(DICT).toContain(screen.getByRole("status").textContent));
    key(input, "ArrowDown");
    key(input, "Enter");
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("UserPicker review T81 fixes (NFR-7)", () => {
  const status = () => document.querySelector<HTMLElement>('div[role="status"]');

  it("ac_field_has_max_length_64", () => {
    const { input } = setup();
    expect((input as HTMLInputElement).maxLength).toBe(64);
  });

  it("ac_live_region_is_permanent_div_with_stable_identity", async () => {
    installFetch({ [USERS]: () => j(200, page([A, B])) });
    const { input } = setup();
    const region = status();
    expect(region).toBeTruthy();
    expect(region!.tagName).toBe("DIV");
    expect(region!.textContent).toBe("");
    expect(document.querySelectorAll('[role="status"]').length).toBe(1);
    type(input, "iv");
    await screen.findAllByRole("option");
    expect(status()).toBe(region);
    expect(document.querySelectorAll('[role="status"]').length).toBe(1);
  });

  it("ac_live_region_announces_result_count", async () => {
    installFetch({ [USERS]: () => j(200, page([A, B])) });
    const { input } = setup();
    type(input, "iv");
    await screen.findAllByRole("option");
    await waitFor(() => expect(status()!.textContent).toMatch(/2/));
  });

  it("ac_live_region_announces_loading", async () => {
    const d = deferred<Response>();
    installFetch({ [USERS]: () => d.promise });
    const { input } = setup();
    type(input, "iv");
    await waitFor(() => expect(status()!.textContent).not.toBe(""));
    expect(DICT).toContain(status()!.textContent);
    d.resolve(j(200, page([A])));
    await screen.findAllByRole("option");
  });

  it("ac_live_region_announces_nothing_found", async () => {
    installFetch({ [USERS]: () => j(200, page([])) });
    const { input } = setup();
    type(input, "zzz");
    await waitFor(() => expect(status()!.textContent).toBe(ru["user_picker.empty"]));
  });

  it("ac_escape_with_open_list_does_not_bubble_to_parent", async () => {
    installFetch({ [USERS]: () => j(200, page([A, B])) });
    const parentKey = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <div onKeyDown={(e) => parentKey(e.key)}>
          <UserPicker label="Исполнитель" onSelect={vi.fn()} />
        </div>
      </QueryClientProvider>,
    );
    const input = screen.getByRole("combobox", { name: "Исполнитель" });
    type(input, "iv");
    await screen.findAllByRole("option");
    key(input, "Escape");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(parentKey).not.toHaveBeenCalledWith("Escape");
    // список закрыт: Escape всплывает дальше (закрывает окно-владельца)
    key(input, "Escape");
    expect(parentKey).toHaveBeenCalledWith("Escape");
  });

  it("ac_has_next_with_no_visible_options_asks_to_refine_query", async () => {
    installFetch({ [USERS]: () => j(200, page([B], 1, true)) });
    const { input } = setup({ allowedIds: [A.id] });
    type(input, "iv");
    await waitFor(() => expect(status()!.textContent).toMatch(/уточн/i));
    expect(DICT).toContain(status()!.textContent);
    expect(status()!.textContent).not.toBe(ru["user_picker.empty"]);
    expect(options()).toEqual([]);
  });

  it("ac_active_option_has_visible_outline_for_forced_colors", async () => {
    installFetch({ [USERS]: () => j(200, page([A, B])) });
    const { input } = setup();
    type(input, "i");
    await screen.findAllByRole("option");
    key(input, "ArrowDown");
    const active = options()[0]!;
    expect(active.getAttribute("aria-selected")).toBe("true");
    expect(active.style.outline).toMatch(/\S/);
    expect(active.style.outline).not.toMatch(/^none|^0(px)?\b/);
  });
});
