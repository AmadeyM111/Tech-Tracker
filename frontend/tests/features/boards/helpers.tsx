// T91 (доработка доски; тесты BoardCreate/BoardOptimistic/BoardFilter .test.tsx). КОНТРАКТ:
//
// Новые ключи ru.ts (значения для проверок точные только там, где указаны):
//   boards.add_task "Добавить задачу"; boards.create_form_label "Новая задача в колонке «{status}»";
//   boards.create_title_label (подпись поля названия); boards.create_submit; boards.create_cancel;
//   boards.filter_label (подпись select); boards.filter_all "Все исполнители";
//   boards.filter_none "Без исполнителя".
// Создание. BoardView получает от ProjectPage право permissions.create_task (проп на усмотрение
//   исполнителя; тесты идут через ProjectPage + GET /projects/{id}). Без права - ни кнопок, ни форм.
//   В каждой section[data-column] при праве: button[type=button][data-action="add-task"] (текст
//   ru["boards.add_task"]). Клик -> кнопка заменяется на form[data-form="board-create-task"]
//   (aria-label = t("boards.create_form_label",{status})) внутри ТОЙ ЖЕ колонки: input[name="title"]
//   (label = ru["boards.create_title_label"], фокус сразу на нём), button[type=submit]
//   (ru["boards.create_submit"]), button[type=button][data-action="cancel-create"]
//   (ru["boards.create_cancel"]). Escape в поле или клик «Отмена» -> форма исчезает, фокус на
//   кнопке add-task этой колонки, запросов нет. Пустое/пробельное название -> запроса нет, один
//   role="alert" errorMessage("validation_error"), форма открыта. Двойная отправка -> один POST.
//   Тело POST /projects/{id}/tasks строго {title: <trim>} (никаких assignee_id/priority/... - для
//   любой роли). Цель не todo -> после 201 клиент шлёт POST /tasks/{newId}/move {status: цель}
//   без after/before (или null). Цель todo -> move НЕ вызывается. Ошибка создания -> один alert
//   errorMessage(code), форма открыта, введённое сохранено, move нет. Ошибка move -> один alert
//   errorMessage(code), задача остаётся в «К выполнению», доска перечитана. Успех -> форма
//   закрыта, фокус на кнопке add-task колонки, доска перечитана, карточка видна в целевой колонке.
// Оптимистичность: после опускания до ответа POST /move карточка уже в новой колонке/позиции;
//   на ошибку (403/422/503/сеть) - порядок сервера и ровно один alert errorMessage(code); опрос
//   во время запроса оптимистичное состояние не затирает; после успеха - перечитывание.
// Фильтр: select[name="board-assignee"] с подписью ru["boards.filter_label"] над колонками (внутри
//   [data-role="board"]); опции по порядку: value "" (boards.filter_all), value "none"
//   (boards.filter_none), затем уникальные исполнители, присутствующие на карточках ДОСКИ (без
//   доп. запроса; value = user id, текст = login, сортировка по login по возрастанию). Фильтрация
//   клиентская: колонки остаются, чужие карточки не рендерятся (в колонке без совпадений -
//   [data-role="empty"]); h3 не меняется. Выбор живёт в состоянии компонента (ни URL, ни
//   localStorage/sessionStorage); опрос его не сбрасывает. Соседи для move считаются по ПОЛНОМУ
//   порядку колонки: перенос на место перед первой видимой карточкой X -> before = X, after = её
//   непосредственный предшественник в полном порядке; в колонку, где видимых нет, но скрытые
//   есть -> в конец полного порядка (after = последняя, before = null).
//   Счётчиков в заголовках колонок в доске нет - их не вводим.
//
// T86: общие помощники тестов канбан-доски.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (тесты привязаны к нему; строки интерфейса - только из словаря,
// новые ключи добавляются в src/shared/i18n/ru.ts).
//
// Зависимости (plan D-61): @dnd-kit/core ^6.3, @dnd-kit/sortable ^10, @dnd-kit/utilities ^3.2.
//
// src/features/boards/dnd.ts
//   neighborsAfterDrop(columnTaskIds: readonly string[], movedId: string, targetIndex: number)
//       : { after_task_id: string | null; before_task_id: string | null }
//     columnTaskIds - карточки целевой колонки в показанном порядке (movedId может входить);
//     карточка из списка исключается; targetIndex - итоговый индекс в списке без неё, с
//     прижатием к 0..n; after - сосед сверху, before - сосед снизу; нет соседа -> null. Чистая.
//
//   pickDropColumn(columnRects: readonly { status: string; left: number; top: number;
//       right: number; bottom: number }[], pointer: { x: number; y: number }): string | null
//     (B2) зона сброса - ВСЯ колонка (прямоугольник секции колонки, а не высота её списка):
//     status колонки, чей прямоугольник содержит указатель (left <= x < right, top <= y < bottom);
//     вне всех колонок - null. Чистая.
//   dropIndexInColumn(overIndex: number, activeCenterY: number, overCenterY: number,
//       sameColumn: boolean): number
//     (B3) итоговый индекс (в списке колонки; вызывающий дальше приводит его через
//     neighborsAfterDrop): sameColumn -> overIndex; иначе overIndex + 1, если центр
//     перетаскиваемой карточки НИЖЕ центра карточки под ней (строго), иначе overIndex (ровно по
//     центру - над ней); overIndex < 0 (под указателем нет карточки, пустая колонка) -> 0.
//   nearestCardIndex(cardRects: readonly { top: number; bottom: number }[], pointerY: number): number
//     (R2) индекс карточки, чей вертикальный отрезок [top, bottom] ближе всего к pointerY
//     (внутри отрезка расстояние 0; при равенстве - меньший индекс); пустой список -> -1. Чистая.
//   Правила сброса указателем внутри колонки, но не на карточке (промежуток между карточками,
//     заголовок h3, зазор под списком): место сброса определяется по ближайшей по вертикали
//     карточке ЭТОЙ колонки (nearestCardIndex) и положению центра перетаскиваемой карточки
//     относительно неё (dropIndexInColumn / итоговый порядок), т.е. карточка встаёт ровно в
//     промежуток (между соседями); на заголовок - индекс 0 (before = первая карточка колонки);
//     «конец колонки» - только для пустой колонки и точки ниже последней карточки (M4).
//     Если итоговое место и колонка те же - запрос не уходит.
//   Заморозка (R3): пока идёт клавиатурный перенос, тик опроса не меняет DOM доски; после
//     Escape/опускания показывается новый порядок. Блокировка (R4): пока POST переноса в полёте,
//     второй перенос не отправляет запрос; после ответа (успеха или ошибки) переносы проходят.
//   Правила разметки поведения: (B1) Enter/Space на ссылке названия внутри карточки не начинает
//     перенос (keydown не defaultPrevented, без объявления о взятии); Space на самой карточке - да.
//     (M4) сброс на список/колонку непустой колонки ниже последней карточки -> в конец колонки.
//     (M13) объявление при взятии содержит название и не содержит «над карточкой «<её название>»».
//
// src/features/boards/api.ts (поверх getAppClient(); не-2xx и сеть -> ApiError)
//   getBoard(projectId, opts?: { headers?, signal? }): Promise<Board>   GET /api/v1/projects/{id}/board
//   moveTask(taskId, b: TaskMove): Promise<void>   POST /api/v1/tasks/{id}/move  тело
//     { status, after_task_id, before_task_id } (204; соседи null или не передаются)
//
// src/features/boards/BoardView.tsx  export function BoardView({ projectId })  - содержимое
//   вкладки «Доска» (ProjectPage, [role="tab"][data-tab="board"]; вкладка выбрана по умолчанию).
//   Доска читается через usePolledQuery (FR-29): тики опроса несут X-GT-Background: 1, первая
//   загрузка и инвалидация после переноса - нет. Ключ запроса начинается с "board" или "projects"
//   (тесты инвалидацию проверяют по числу GET, а не по ключу).
//
// Разметка:
//   [data-role="board"] - корень; 4 колонки в порядке API (todo, in_progress, review, done):
//   section[data-column="<status>"] c aria-labelledby -> id заголовка (h3) с текстом
//     ru["tasks.status.<status>"]; список карточек - ul/ol[data-role="column-cards"] внутри колонки
//     с aria-label (из словаря, содержит название колонки); при пустой колонке в ней
//     [data-role="empty"] с ru["boards.empty_column"] (и сама колонка остаётся сбрасываемой);
//   карточка: li[data-task-id="<uuid>"] - ЕЁ ЖЕ элемент и есть перетаскиваемый (атрибуты/слушатели
//     useSortable на нём, tabIndex=0 у карточки, фокус клавиатуры - на ней); внутри:
//     [data-field="title"] c <a href="/tasks/<id>"> (текст = название),
//     [data-field="priority"] (ru["tasks.priority.<p>"]),
//     [data-field="due_date"] - пусто -> ru["tasks.due_none"], иначе time[datetime="YYYY-MM-DD"]
//       с текстом DD.MM.YYYY (без Date/пояса),
//     [data-field="assignee"] - login или ru["tasks.assignee_none"],
//     [data-field="progress"] - null -> ru["tasks.progress_none"], число N ->
//       t("tasks.progress_value", { percent: N });
//   доступность dnd: у карточки aria-roledescription = ru["boards.card_roledescription"],
//     aria-describedby -> элемент с текстом ru["boards.dnd_instructions"] (DndContext
//     accessibility.screenReaderInstructions); DndContext accessibility.announcements - только
//     русские строки из словаря, без id задач (названием задачи); сенсоры Pointer + Keyboard
//     (sortableKeyboardCoordinates); id колонки как droppable - на усмотрение исполнителя.
//   Клавиатура: Space на карточке - взять, стрелки - переместить (вверх/вниз внутри колонки,
//     влево/вправо между колонками), Space - опустить, Escape - отмена (без запроса).
//   После опускания: POST /tasks/{id}/move { status: целевая колонка, after_task_id,
//     before_task_id } (null или без ключа); запрос не уходит, если место и колонка те же.
//     Успех (204) -> инвалидация доски (новый GET без X-GT-Background). Ошибка (403/422/503) ->
//     ровно один role="alert" с errorMessage(code) (ErrorAlert) и перечитывание доски; на экране -
//     порядок сервера. После переноса document.activeElement - карточка с тем же data-task-id.
//   Ошибка загрузки доски: ровно один role="alert" с errorMessage(code), колонок нет.
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { PROJ_CREATE, USER_CAPS, taskDetail } from "../tasks/helpers";
import {
  BUSINESS,
  ME,
  MEMBERS,
  M_ME,
  M_OWNER,
  NO_CONTENT,
  ONE,
  PERM_READ,
  PID,
  R_KUZNETSOV,
  R_ME,
  detail,
  j,
  meWith,
  page,
  type Handler,
} from "../projects/helpers";

export * from "../projects/helpers";
export { ru };

export const BOARD = `GET /api/v1/projects/${PID}/board`;
export const PROJ_TASKS_GET = `GET /api/v1/projects/${PID}/tasks`;
export const MOVE = (id: string) => `POST /api/v1/tasks/${id}/move`;

export const STATUSES = ["todo", "in_progress", "review", "done"] as const;
export type Status = (typeof STATUSES)[number];

const tid = (n: number) => `b${n}b${n}b${n}b${n}-0000-4000-8000-00000000000${n}`;
export const TA = tid(1);
export const TB = tid(2);
export const TC = tid(3);
export const TD = tid(4);
export const TE = tid(5);

export function card(id: string, title: string, status: Status, position: number, over: Record<string, unknown> = {}) {
  return {
    id,
    title,
    status,
    priority: "base",
    due_date: null,
    assignee: null,
    progress: null,
    subtask_count: 0,
    position,
    ...over,
  };
}

export const CA = card(TA, "Подготовить отчёт", "todo", 10, {
  priority: "high",
  due_date: "2026-12-31",
  assignee: R_KUZNETSOV,
  progress: 50,
  subtask_count: 2,
});
export const CB = card(TB, "Согласовать бюджет", "todo", 20);
export const CC = card(TC, "Проверить договор", "todo", 30, { due_date: "2026-01-05", progress: 0, subtask_count: 1 });
export const CD = card(TD, "Запустить рассылку", "in_progress", 10, { assignee: R_ME });
export const CE = card(TE, "Архивировать", "done", 10);

export function boardBody(columns: Record<Status, unknown[]>) {
  return {
    project: { id: PID, name: "Альфа" },
    columns: STATUSES.map((s) => ({ status: s, tasks: columns[s] })),
  };
}

export const INITIAL = { todo: [CA, CB, CC], in_progress: [CD], review: [], done: [CE] };

export function boardRoutes(
  over: Record<string, Handler> = {},
  columns: Record<Status, unknown[]> = INITIAL,
): Record<string, Handler> {
  return {
    [ME]: () => j(200, meWith(BUSINESS, "business_admin")),
    [ONE]: () => j(200, detail({ permissions: PERM_READ })),
    [MEMBERS]: () => j(200, page([M_OWNER, M_ME])),
    [PROJ_TASKS_GET]: () => j(200, page([])),
    [BOARD]: () => j(200, boardBody(columns)),
    ...over,
  };
}

export const column = (c: ParentNode, status: string) =>
  c.querySelector<HTMLElement>(`[data-column="${status}"]`);
export const cardEl = (c: ParentNode, id: string) => c.querySelector<HTMLElement>(`[data-task-id="${id}"]`);
export const idsIn = (c: ParentNode, status: string) =>
  Array.from(column(c, status)?.querySelectorAll<HTMLElement>("[data-task-id]") ?? []).map(
    (e) => e.dataset.taskId,
  );

/** Новое значение ключа словаря; падает громко, если исполнитель его не добавил. */
export function dict(key: string): string {
  const v = (ru as Record<string, string | undefined>)[key];
  if (typeof v !== "string") throw new Error(`нет ключа словаря ${key}`);
  return v;
}

/**
 * jsdom не считает раскладку: даём колонкам и карточкам прямоугольники по data-атрибутам
 * (колонки - слева направо, карточки - сверху вниз), иначе sortableKeyboardCoordinates слеп.
 * Также ResizeObserver-заглушка (dnd-kit измеряет элементы через него).
 */
export function installLayout() {
  if (typeof globalThis.ResizeObserver === "undefined") {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  }
  const rect = (x: number, y: number, w: number, h: number): DOMRect =>
    ({ x, y, left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, toJSON() {} }) as DOMRect;
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const el = this as HTMLElement;
    const col = el.closest("[data-column]") as HTMLElement | null;
    if (!col) return rect(0, 0, 0, 0);
    const ci = STATUSES.indexOf(col.dataset.column as Status);
    const x = Math.max(ci, 0) * 300;
    // Секция колонки тянется на всю высоту сетки (600), список карточек - только по содержимому.
    if (el === col) return rect(x, 0, 280, 600);
    const c = el.closest("[data-task-id]") as HTMLElement | null;
    const siblings = Array.from(col.querySelectorAll("[data-task-id]"));
    if (c) return rect(x, 40 + siblings.indexOf(c) * 60, 280, 50);
    if (el.matches('[data-role="column-cards"]')) return rect(x, 40, 280, Math.max(siblings.length, 1) * 60);
    return rect(x, 0, 280, 40);
  });
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

/** Клавиатурный перенос: Space на карточке, стрелки, Space. Возвращает после опускания. */
export async function keyboardDrag(el: HTMLElement, arrows: string[], drop = " ") {
  el.focus();
  fireEvent.keyDown(el, { key: " ", code: "Space" });
  await tick();
  for (const a of arrows) {
    fireEvent.keyDown(document.activeElement ?? el, { key: a, code: a });
    await tick();
  }
  fireEvent.keyDown(document.activeElement ?? el, { key: drop, code: drop === " " ? "Space" : drop });
  await tick();
}

/** Перенос указателем: pointerdown на карточке, два pointermove (первый > 5 px), pointerup. */
export async function pointerDrag(
  el: HTMLElement,
  from: { x: number; y: number },
  to: { x: number; y: number },
) {
  const fire = (target: EventTarget, type: string, p: { x: number; y: number }) => {
    const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: p.x, clientY: p.y, button: 0 });
    Object.defineProperty(ev, "isPrimary", { value: true });
    Object.defineProperty(ev, "pointerId", { value: 1 });
    act(() => {
      target.dispatchEvent(ev);
    });
  };
  fire(el, "pointerdown", from);
  await tick();
  fire(document, "pointermove", { x: from.x + 10, y: from.y + 10 });
  await tick();
  fire(document, "pointermove", to);
  await tick();
  fire(document, "pointerup", to);
  await tick();
}

export async function openBoard(over: Record<string, Handler> = {}, columns: Record<Status, unknown[]> = INITIAL) {
  const { installFetch, renderApp } = await import("../projects/helpers");
  const f = installFetch(boardRoutes(over, columns));
  const view = renderApp(`/projects/${PID}`);
  await screen.findByRole("heading", { level: 1, name: "Альфа" });
  await waitFor(() => expect(cardEl(view.container, TA)).toBeTruthy());
  return { f, ...view };
}

// ---- T91 ----

export { PROJ_CREATE, USER_CAPS, taskDetail };

export const TN = "b6b6b6b6-0000-4000-8000-000000000006";
export const NEW_TITLE = "Новая задача";

export const addBtn = (c: ParentNode, status: string) =>
  column(c, status)?.querySelector<HTMLElement>('button[data-action="add-task"]') ?? null;
export const createForm = (c: ParentNode, status: string) =>
  column(c, status)?.querySelector<HTMLFormElement>('form[data-form="board-create-task"]') ?? null;
export const titleInput = (form: HTMLFormElement) => form.querySelector<HTMLInputElement>('input[name="title"]')!;
export const filterSelect = () =>
  screen.getByRole("combobox", { name: dict("boards.filter_label") }) as HTMLSelectElement;
export const pickFilter = (value: string) => fireEvent.change(filterSelect(), { target: { value } });

export function openCreate(c: ParentNode, status: string) {
  const b = addBtn(c, status);
  if (!b) throw new Error(`нет кнопки добавления в ${status}`);
  fireEvent.click(b);
  const form = createForm(c, status);
  if (!form) throw new Error("форма не открылась");
  return form;
}

/**
 * Серверная доска с состоянием: POST создания добавляет карточку TN в конец todo,
 * POST move TN переносит её в конец колонки status. GET board отдаёт текущее состояние.
 */
export function liveBoard(base: Record<Status, unknown[]> = INITIAL) {
  const cols: Record<Status, unknown[]> = {
    todo: [...base.todo],
    in_progress: [...base.in_progress],
    review: [...base.review],
    done: [...base.done],
  };
  const routes: Record<string, Handler> = {
    [BOARD]: () => j(200, boardBody(cols)),
    [PROJ_CREATE]: async (r) => {
      const b = (await r.clone().json()) as { title: string };
      cols.todo.push(card(TN, b.title, "todo", 1000));
      return j(201, taskDetail({ id: TN, title: b.title, status: "todo" }));
    },
    [MOVE(TN)]: async (r) => {
      const b = (await r.clone().json()) as { status: Status };
      for (const s of STATUSES) cols[s] = cols[s].filter((c) => (c as { id: string }).id !== TN);
      cols[b.status].push(card(TN, NEW_TITLE, b.status, 1000));
      return NO_CONTENT();
    },
  };
  return { cols, routes };
}
