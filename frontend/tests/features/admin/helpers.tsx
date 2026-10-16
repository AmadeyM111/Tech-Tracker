// T24: общие помощники тестов экранов администрирования.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (тесты привязаны к нему; строки интерфейса - только из словаря).
//
// Модули:
//   frontend/src/features/admin/api.ts  (всё поверх getAppClient(); не-2xx и сеть -> ApiError;
//     запросы пользователя идут БЕЗ X-GT-Background)
//     listUsers(p: { page: number; pageSize?: number }): Promise<Page<AdminUser>>
//         GET /api/v1/admin/users?page=&page_size=   (page_size только если передан)
//     createUser(b: { login: string; one_time_password: string }): Promise<AdminUser>   POST /admin/users
//     blockUser(id) / unblockUser(id) / revokeSessions(id): Promise<void>
//         POST /admin/users/{id}/block | unblock | revoke-sessions
//     resetPassword(id, b: { one_time_password: string }): Promise<void>  POST .../reset-password
//     setRole(id, role: Role | null): Promise<AdminUser>   PUT .../role  тело { role }
//     listAudit(p: { page: number; pageSize?: number; entityType?: EntityType; actorId?: string }):
//         Promise<Page<AuditEntry>>   GET /api/v1/admin/audit?page&page_size&entity_type&actor_id
//         (параметр в запросе только если задан)
//   frontend/src/features/admin/UsersPage.tsx  export function UsersPage()
//   frontend/src/features/admin/AuditPage.tsx  export function AuditPage()
//
// Маршруты в AppRoutes (router.tsx), оба за guard сессии как у Root (замечание ревью T23 п.1):
//   /admin/users  (UsersPage)  - нужна capability manage_accounts
//   /admin/audit  (AuditPage)  - нужна capability view_audit
//   Состояние me: 401 -> /login, 403 password_change_required -> /change-password,
//   403 no_role -> /no-role (по ошибке запроса me, не только по колбэку клиента).
//   Нет нужной capability -> остаётся на маршруте и показывает role="alert" с
//   errorMessage("forbidden"); запросов к /admin/* при этом нет.
//   Главная ("/"): ссылки <a href="/admin/users"> и <a href="/admin/audit"> только при
//   соответствующих capabilities (manage_accounts / view_audit).
//
// Разметка UsersPage:
//   список: строки <tr data-user-id="<uuid>"> с ячейками [data-field="login"|"role"|"status"];
//     текст role/status - из словаря (роль null тоже имеет текст из словаря), status различает
//     активную и заблокированную запись;
//   пагинация: button[data-action="next-page"] (disabled при has_next=false),
//     button[data-action="prev-page"] (disabled на странице 1); запрос ?page=N;
//   действия строки (type="button"): [data-action="block"] (если не заблокирован) /
//     [data-action="unblock"] (если заблокирован), [data-action="reset-password"],
//     [data-action="revoke-sessions"]; роль: select[name="role"] (значения "", tech_admin,
//     business_admin, user; "" = без роли; 002 FR-21: значения mixed нет) + [data-action="set-role"] - только при
//     capability assign_roles; select и кнопки имеют доступное имя (label/aria-label);
//   подтверждение: block, reset-password, revoke-sessions и снятие роли (select = "") открывают
//     [role="alertdialog"] с логином пользователя, button[data-action="confirm"] и
//     button[data-action="cancel"]; фокус уходит в диалог, Escape = отмена; запрос уходит
//     только после confirm; unblock и назначение/смена роли - без диалога;
//   создание: form с input[name="login"][autocomplete="username"] (label, подсказка формата
//     FR-73 через aria-describedby, текст из словаря) и button[type="submit"]. Пароль
//     в форме НЕ вводится: клиент генерирует его при отправке;
//   одноразовый пароль (создание и сброс): после успешного POST показывается в
//     [data-role="one-time-password"] ровно отправленный в запросе пароль, рядом
//     button[data-action="close-password"]; после закрытия пароль нигде в DOM не присутствует;
//   ошибка: p[role="alert"] с errorMessage(code), получает фокус (ErrorAlert);
//   повторная отправка при летящем запросе блокируется (один POST).
//
// Разметка AuditPage:
//   фильтры: form с select[name="entity_type"] ("" + user, project, task, comment, attachment,
//     stage, deal), input[name="actor_id"] (UUID автора), button[type="submit"] (применить, страница
//     сбрасывается на 1), button[data-action="reset-filters"];
//   строки <tr data-entry-id="<id>"> с [data-field="occurred_at"|"actor"|"action"|"entity_type"|
//     "entity_id"|"changed_fields"]; пагинация как у пользователей.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { expect, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";

export const j = (s: number, b: unknown) =>
  new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
export const err = (s: number, code: string) => j(s, { detail: code, code });
export const NO_CONTENT = () => new Response(null, { status: 204 });

export function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

export const ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const ID_IVANOV = "11111111-1111-4111-8111-111111111111";
export const ID_PETROV = "22222222-2222-4222-8222-222222222222";

export const CAPS_ALL = ["manage_accounts", "assign_roles", "view_audit"];

export function meWith(capabilities: string[], role = "tech_admin") {
  return { id: ADMIN_ID, login: "admin", role, must_change_password: false, capabilities };
}

export interface UserFx {
  id: string;
  login: string;
  role: string | null;
  is_blocked: boolean;
  must_change_password: boolean;
  created_at: string;
}

export function mkUser(over: Partial<UserFx> & Pick<UserFx, "id" | "login">): UserFx {
  return {
    role: null,
    is_blocked: false,
    must_change_password: true,
    created_at: "2026-10-01T08:00:00Z",
    ...over,
  };
}

export const U_IVANOV = mkUser({ id: ID_IVANOV, login: "ivanov" });
export const U_PETROV = mkUser({ id: ID_PETROV, login: "petrov", role: "user", is_blocked: true, must_change_password: false });
export const U_ADMIN = mkUser({ id: ADMIN_ID, login: "admin", role: "tech_admin", must_change_password: false });

export function page<T>(items: T[], p = 1, hasNext = false, size = 50) {
  return { items, page: p, page_size: size, has_next: hasNext };
}

export type Handler = (req: Request) => Response | Promise<Response>;

/** Общая подмена fetch: ключ "METHOD /path" (без query); неизвестный запрос - громкая ошибка. */
export function installFetch(routes: Record<string, Handler>) {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => {
      calls.push(r);
      const key = `${r.method} ${new URL(r.url).pathname}`;
      const h = routes[key];
      if (!h) throw new Error(`unexpected request ${key}`);
      return h(r);
    }),
  );
  return {
    calls,
    count: (key: string) =>
      calls.filter((c) => `${c.method} ${new URL(c.url).pathname}` === key).length,
    last: (key: string) => {
      const all = calls.filter((c) => `${c.method} ${new URL(c.url).pathname}` === key);
      const r = all[all.length - 1];
      if (!r) throw new Error(`no request ${key}`);
      return r;
    },
    query: (r: Request) => new URL(r.url).searchParams,
  };
}

export function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...out, qc };
}

export const where = () => screen.getByTestId("where").textContent;
export const expectAt = (p: string) => waitFor(() => expect(where()).toBe(p));

export function row(container: HTMLElement, id: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(`tr[data-user-id="${id}"]`);
  if (!el) throw new Error(`no row for ${id}`);
  return el;
}

export function action(scope: ParentNode, name: string): HTMLButtonElement {
  const el = scope.querySelector<HTMLButtonElement>(`button[data-action="${name}"]`);
  if (!el) throw new Error(`no button[data-action=${name}]`);
  return el;
}

export function cell(scope: ParentNode, name: string): HTMLElement {
  const el = scope.querySelector<HTMLElement>(`[data-field="${name}"]`);
  if (!el) throw new Error(`no [data-field=${name}]`);
  return el;
}

export function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

/** Спай Math.random, фиксирующий вызовы из файлов приложения (src/, вне node_modules).
 * Вызовы из node_modules (openapi-fetch randomID) допустимы. */
export function spyMathRandomFromApp(): { appCalls: string[] } {
  const appCalls: string[] = [];
  vi.spyOn(Math, "random").mockImplementation(() => {
    const stack = new Error().stack ?? "";
    // Кадры "at ...": пропускаем сам мок (helpers) и vitest; первый оставшийся -
    // непосредственный вызывающий Math.random. App-код (src/ вне node_modules) -> нарушение.
    const frames = stack.split("\n").filter((l) => l.trim().startsWith("at "));
    const caller =
      frames.find(
        (l) =>
          !l.includes("tests/features/admin/helpers") &&
          !l.includes("/vitest/") &&
          !l.includes("@vitest"),
      ) ?? "";
    if (caller.includes("/src/") && !caller.includes("node_modules")) appCalls.push(caller.trim());
    return 0.5;
  });
  return { appCalls };
}
