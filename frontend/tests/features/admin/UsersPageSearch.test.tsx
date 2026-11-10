// Поиск на экране учётных записей (макет ta-accounts-search): поле над таблицей, запрос с q на
// сервер, счётчик «Найдено учётных записей: N», пустое состояние с подсказкой и кнопкой «Сбросить».
// Тексты - только из словаря ru (кириллица в тестах не нужна).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { t, ru } from "../../../src/shared/i18n";
import {
  CAPS_ALL,
  ID_IVANOV,
  ID_PETROV,
  U_ADMIN,
  U_IVANOV,
  U_PETROV,
  installFetch,
  j,
  meWith,
  page,
  renderApp,
  type Handler,
} from "./helpers";

const LIST = "GET /api/v1/admin/users";
const ME = "GET /api/v1/me";
const ALL = [U_ADMIN, U_IVANOV, U_PETROV];

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

/** Сервер: без q - все записи; q=ivan - одна; любой другой q - пусто. */
const listFor: Handler = (req) => {
  const q = new URL(req.url).searchParams.get("q");
  if (q === null) return j(200, { ...page(ALL), total: ALL.length });
  if (q === "ivan") return j(200, { ...page([U_IVANOV]), total: 1 });
  return j(200, { ...page([]), total: 0 });
};

async function open(list: Handler = listFor) {
  f = installFetch({ [ME]: () => j(200, meWith(CAPS_ALL)), [LIST]: list });
  const view = renderApp("/admin/users");
  await waitFor(() =>
    expect(view.container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy(),
  );
  return view;
}

const searchInput = (): HTMLInputElement =>
  screen.getByRole("searchbox", { name: ru["admin.users.search_label"] }) as HTMLInputElement;

const searchForm = (): HTMLFormElement => {
  const form = searchInput().closest("form");
  if (form === null) throw new Error("search input is not inside a form");
  return form;
};

const resetButton = () => screen.getByRole("button", { name: ru["admin.users.search_reset"] });

const counter = (container: HTMLElement) => container.querySelector('[data-field="search-count"]');

const countText = (n: number) => t("admin.users.search_count", { count: n });

const rows = (container: HTMLElement) => container.querySelectorAll("tr[data-user-id]");

const lastQ = () => f.query(f.last(LIST)).get("q");

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("UsersPage: поиск учётных записей", () => {
  it("поле поиска есть: тип search, подпись из словаря, внутри формы role=search", async () => {
    await open();

    expect(searchInput().getAttribute("type")).toBe("search");
    expect(searchForm().getAttribute("role")).toBe("search");
  });

  it("пустое поле: полный список без q и без счётчика", async () => {
    const { container } = await open();

    expect(searchInput().value).toBe("");
    expect(lastQ()).toBeNull();
    expect(rows(container)).toHaveLength(ALL.length);
    expect(counter(container)).toBeNull();
  });

  it("ввод уходит на сервер с q после задержки; счётчик и найденная строка", async () => {
    const { container } = await open();

    fireEvent.change(searchInput(), { target: { value: "ivan" } });

    await waitFor(() => expect(lastQ()).toBe("ivan"));
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
    await waitFor(() => expect(counter(container)?.textContent).toBe(countText(1)));
    expect(rows(container)).toHaveLength(1);
    expect(container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy();
    expect(container.querySelector(`tr[data-user-id="${ID_PETROV}"]`)).toBeNull();
  });

  it("q обрезается по краям; поле из одних пробелов - без фильтра", async () => {
    const { container } = await open();

    fireEvent.change(searchInput(), { target: { value: "  ivan  " } });
    await waitFor(() => expect(lastQ()).toBe("ivan"));

    fireEvent.change(searchInput(), { target: { value: "   " } });
    await waitFor(() => expect(lastQ()).toBeNull());
    await waitFor(() => expect(rows(container)).toHaveLength(ALL.length));
  });

  it("debounce: быстрый ввод даёт один запрос с полным значением", async () => {
    await open();
    const before = f.count(LIST);

    fireEvent.change(searchInput(), { target: { value: "i" } });
    fireEvent.change(searchInput(), { target: { value: "iv" } });
    fireEvent.change(searchInput(), { target: { value: "ivan" } });
    // Синхронно после ввода запроса ещё нет: ожидание задержки.
    expect(f.count(LIST)).toBe(before);

    await waitFor(() => expect(lastQ()).toBe("ivan"));
    const intermediate = f.calls.filter((c) => {
      const v = f.query(c).get("q");
      return v === "i" || v === "iv";
    });
    expect(intermediate).toHaveLength(0);
    expect(f.count(LIST)).toBe(before + 1);
  });

  it("Enter отправляет поиск сразу, не дожидаясь задержки", async () => {
    await open();

    fireEvent.change(searchInput(), { target: { value: "ivan" } });
    fireEvent.submit(searchForm());

    // Задержка debounce 300 мс: без Enter запроса за 200 мс не было бы.
    await waitFor(() => expect(lastQ()).toBe("ivan"), { timeout: 200 });
  });

  it("ничего не найдено: текст, подсказка и кнопка «Сбросить»; счётчика и таблицы нет", async () => {
    const { container } = await open();

    fireEvent.change(searchInput(), { target: { value: "zzz" } });

    await waitFor(() =>
      expect(screen.getByText(ru["admin.users.search_none"])).toBeTruthy(),
    );
    expect(screen.getByText(ru["admin.users.search_none_hint"])).toBeTruthy();
    expect(resetButton()).toBeTruthy();
    expect(rows(container)).toHaveLength(0);
    expect(counter(container)).toBeNull();
    expect(screen.queryByText(ru["admin.users.empty"])).toBeNull();
  });

  it("«Сбросить» очищает поле и возвращает полный список", async () => {
    const { container } = await open();
    fireEvent.change(searchInput(), { target: { value: "zzz" } });
    await waitFor(() =>
      expect(screen.getByText(ru["admin.users.search_none"])).toBeTruthy(),
    );

    fireEvent.click(resetButton());

    await waitFor(() => expect(rows(container)).toHaveLength(ALL.length));
    expect(searchInput().value).toBe("");
    expect(lastQ()).toBeNull();
    expect(screen.queryByText(ru["admin.users.search_none"])).toBeNull();
    expect(counter(container)).toBeNull();
  });

  it("фокус остаётся в поле поиска при обновлении списка", async () => {
    const { container } = await open();
    searchInput().focus();

    fireEvent.change(searchInput(), { target: { value: "ivan" } });
    await waitFor(() => expect(counter(container)?.textContent).toBe(countText(1)));

    expect(document.activeElement).toBe(searchInput());
  });

  it("поиск по странице: смена q возвращает на первую страницу", async () => {
    const { container } = await open((req) => {
      const url = new URL(req.url);
      const q = url.searchParams.get("q");
      if (q === null) return j(200, { ...page(ALL, 1, true, 2), total: 30 });
      return j(200, { ...page([U_IVANOV]), total: 1 });
    });
    await waitFor(() => expect(container.querySelector('button[data-action="next-page"]')).toBeTruthy());
    fireEvent.click(container.querySelector<HTMLButtonElement>('button[data-action="next-page"]')!);
    await waitFor(() => expect(f.query(f.last(LIST)).get("page")).toBe("2"));

    fireEvent.change(searchInput(), { target: { value: "ivan" } });

    await waitFor(() => expect(lastQ()).toBe("ivan"));
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
  });
});
