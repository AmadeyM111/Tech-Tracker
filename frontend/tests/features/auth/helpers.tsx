// T23: общие помощники тестов экранов авторизации.
//
// Контракт для исполнителя:
//   frontend/src/features/auth/api.ts  (все функции отклоняются ApiError для не-2xx/сети)
//     export function login(body: { login: string; password: string }):
//         Promise<{ user: { id: string; login: string; role: string | null; must_change_password: boolean } }>
//     export function logout(): Promise<void>
//     export function changePassword(body: { current_password: string; new_password: string }): Promise<void>
//   frontend/src/features/auth/LoginPage.tsx           export function LoginPage()
//   frontend/src/features/auth/ChangePasswordPage.tsx  export function ChangePasswordPage()
//   frontend/src/features/auth/NoRolePage.tsx          export function NoRolePage()
//   frontend/src/app/router.tsx   export function AppRoutes()  (только <Routes>, без Router):
//       /login -> LoginPage, /change-password -> ChangePasswordPage, /no-role -> NoRolePage
//   Успешный вход: must_change_password -> /change-password; role === null -> /no-role; иначе "/".
//   Успешная смена пароля -> "/". Выход (успех) -> /login.
//   Поля находятся по autocomplete (username / current-password / new-password), кнопки по
//   type: type="submit" — отправка, type="button" — выход. Тексты — только из словаря.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

export function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search + l.hash}</p>;
}

export function renderAt(path: string, element: ReactElement, routePath = path) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={element} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function field(container: HTMLElement, autocomplete: string, nth = 0): HTMLInputElement {
  const all = container.querySelectorAll<HTMLInputElement>(`input[autocomplete="${autocomplete}"]`);
  const el = all[nth];
  if (!el) throw new Error(`no input[autocomplete=${autocomplete}] #${nth}`);
  return el;
}

export function submitButton(container: HTMLElement): HTMLButtonElement {
  const el = container.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!el) throw new Error("no submit button");
  return el;
}

export function plainButtons(container: HTMLElement): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]'));
}

export function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
