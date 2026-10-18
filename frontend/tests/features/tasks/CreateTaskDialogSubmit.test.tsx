// 004 / R5-T03: диалог «Новая задача» - отправка, ошибки, повторная отправка, закрытие во время запроса.
// AC: 22, 23, 24, 25, 28, 30, 31 (Escape и «Отмена»), 26 (onCreated с задачей), 6 (CreateTaskForm.test.tsx без правок);
// FR-13..FR-18. Роли: BA - routesBA, U - routesU (spec §5). Переход на карточку и фокус (AC-26 путь) - R5-T05.
import { QueryObserver } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import { LIST, listItem } from "../projects/helpers";
import {
  CREATE_IN,
  P1,
  P3,
  T_NEW,
  deferred,
  err,
  installFetch,
  j,
  networkFail,
  page,
  readBody,
  renderDialog,
  routesBA,
  routesU,
} from "./create-dialog-helpers";

const dialog = () => screen.getByRole("dialog");
const projectSelect = () => within(dialog()).getByLabelText(ru["tasks.project_label"]) as HTMLSelectElement;
const titleInput = () => within(dialog()).getByLabelText(ru["tasks.title_label"]) as HTMLInputElement;
const submitBtn = () =>
  within(dialog()).getByRole("button", { name: ru["tasks.create_submit"] }) as HTMLButtonElement;
const cancelBtn = () => within(dialog()).getByRole("button", { name: ru["admin.cancel"] }) as HTMLButtonElement;
const form = () => dialog().querySelector("form") as HTMLFormElement;
const loaded = () => screen.findByLabelText(ru["tasks.project_label"]);
const posts = (f: { calls: Request[] }) => f.calls.filter((c) => c.method === "POST");
const type = (v: string) => fireEvent.change(titleInput(), { target: { value: v } });
const pick = (id: string) => fireEvent.change(projectSelect(), { target: { value: id } });

describe("validation (AC-23, AC-24, FR-13)", () => {
  for (const [label, value] of [
    ["empty", ""],
    ["spaces", "   "],
  ] as const) {
    it(`004_ac23_${label}_title_sends_nothing_one_validation_alert`, async () => {
      const f = installFetch(routesU());
      renderDialog({ currentProjectId: P1 });
      await loaded();
      type(value);
      fireEvent.submit(form());
      const alert = await screen.findByRole("alert");
      expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
      expect(alert.textContent).toBe(errorMessage("validation_error"));
      expect(posts(f)).toHaveLength(0);
      expect(projectSelect().value).toBe(P1);
      expect(screen.getByRole("dialog")).toBeTruthy();
    });
  }

  it("004_ac24_no_project_sends_nothing_keeps_title", async () => {
    const f = installFetch(routesBA());
    const { onClose, onCreated } = renderDialog({ currentProjectId: null });
    await loaded();
    expect(projectSelect().value).toBe("");
    type("Отчёт");
    fireEvent.click(submitBtn());
    const alert = await screen.findByRole("alert");
    expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(posts(f)).toHaveLength(0);
    expect(titleInput().value).toBe("Отчёт");
    expect(onClose).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe("request (AC-22, AC-25, FR-14, FR-15)", () => {
  it("004_ac22_changed_project_gets_the_request", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    expect(projectSelect().value).toBe(P1);
    pick(P3);
    type("Х");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    expect(f.count(CREATE_IN(P1))).toBe(0);
    expect(posts(f)).toHaveLength(1);
  });

  it("004_ac25_user_body_is_exactly_trimmed_title_no_move", async () => {
    const f = installFetch(routesU());
    renderDialog({ currentProjectId: null });
    await loaded();
    pick(P3);
    type("  Отчёт  ");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    expect(await readBody(f.last(CREATE_IN(P3)))).toStrictEqual({ title: "Отчёт" });
    expect(posts(f)).toHaveLength(1);
    expect(f.calls.some((c) => new URL(c.url).pathname.endsWith("/move"))).toBe(false);
  });

  it("004_ac25_business_admin_body_is_exactly_title_without_assignee", async () => {
    const f = installFetch(routesBA());
    renderDialog({ currentProjectId: P1 });
    await loaded();
    pick(P3);
    type("  Отчёт  ");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(1));
    const body = await readBody(f.last(CREATE_IN(P3)));
    expect(body).toStrictEqual({ title: "Отчёт" });
    expect("assignee_id" in body).toBe(false);
    expect(posts(f)).toHaveLength(1);
    expect(f.calls.some((c) => new URL(c.url).pathname.includes("/move"))).toBe(false);
  });

  it("004_ac26_created_task_goes_to_on_created_dialog_not_closed_by_itself", async () => {
    installFetch(routesU());
    const { onCreated, onClose } = renderDialog({ currentProjectId: P1 });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated).toHaveBeenCalledWith(T_NEW);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_fr15_invalidations_of_three_keys_are_called_before_on_created", async () => {
    installFetch(routesU());
    const { qc, onCreated } = renderDialog({ currentProjectId: P1 });
    let seq = 0;
    const invalidated = new Map<string, number>();
    const orig = qc.invalidateQueries.bind(qc);
    vi.spyOn(qc, "invalidateQueries").mockImplementation(((filters: { queryKey?: unknown }, ...rest: unknown[]) => {
      invalidated.set(JSON.stringify(filters?.queryKey), ++seq);
      return (orig as (...a: unknown[]) => Promise<void>)(filters, ...rest);
    }) as typeof qc.invalidateQueries);
    let createdAt = 0;
    onCreated.mockImplementation(() => {
      createdAt = ++seq;
    });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    for (const key of [["tasks", "project", P1], ["board", P1], ["tasks", "mine"]]) {
      const at = invalidated.get(JSON.stringify(key));
      expect(at, `invalidate ${JSON.stringify(key)}`).toBeDefined();
      expect(at as number).toBeLessThan(createdAt);
    }
  });

  it("004_fr15_on_created_does_not_wait_for_refetch_of_active_board", async () => {
    installFetch(routesU());
    const { qc, onCreated } = renderDialog({ currentProjectId: P1 });
    const gate = deferred<string>();
    let fetches = 0;
    const observer = new QueryObserver(qc, {
      queryKey: ["board", P1],
      queryFn: () => (++fetches === 1 ? Promise.resolve("first") : gate.promise),
      retry: false,
    });
    const unsubscribe = observer.subscribe(() => undefined);
    try {
      await waitFor(() => expect(fetches).toBe(1));
      await loaded();
      type("Отчёт");
      fireEvent.submit(form());
      // перезапрос Доски стартовал и висит; onCreated не должен ждать его завершения
      await waitFor(() => expect(fetches).toBe(2));
      await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1), { timeout: 800 });
      expect(onCreated).toHaveBeenCalledWith(T_NEW);
      expect(cancelBtn().disabled).toBe(false);
      expect(submitBtn().getAttribute("aria-busy")).toBeNull();
    } finally {
      gate.resolve("second");
      unsubscribe();
    }
  });

  it("004_fr15_on_created_throwing_shows_no_create_error_and_no_second_post", async () => {
    const f = installFetch(routesU());
    const { onCreated } = renderDialog({ currentProjectId: P1 });
    onCreated.mockImplementation(() => {
      throw new Error("navigation failed");
    });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 50));
    // задача уже создана: сообщения «ошибка создания» нет
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    // повторная отправка не создаёт дубликат
    fireEvent.submit(form());
    await new Promise((r) => setTimeout(r, 50));
    expect(f.count(CREATE_IN(P1))).toBe(1);
    expect(posts(f)).toHaveLength(1);
  });

  it("004_fr15_invalidation_targets_the_chosen_project_not_the_page_project", async () => {
    installFetch(routesU());
    const { qc, onCreated } = renderDialog({ currentProjectId: P1 });
    const spy = vi.spyOn(qc, "invalidateQueries");
    await loaded();
    pick(P3);
    type("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    const keys = spy.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey?: unknown })?.queryKey));
    expect(keys).toContain(JSON.stringify(["tasks", "project", P3]));
    expect(keys).toContain(JSON.stringify(["board", P3]));
    expect(keys).not.toContain(JSON.stringify(["tasks", "project", P1]));
  });
});

describe("create errors (AC-28, FR-16)", () => {
  const cases: [string, string, () => Response][] = [
    ["403", "forbidden", () => err(403, "forbidden")],
    ["404", "not_found", () => err(404, "not_found")],
    ["422", "validation_error", () => err(422, "validation_error")],
    ["503", "service_busy", () => err(503, "service_busy")],
    ["network", "network_error", networkFail],
  ];
  for (const [label, code, make] of cases) {
    it(`004_ac28_${label}_one_alert_input_kept_retry_sends_second_request`, async () => {
      const f = installFetch(routesU({ [CREATE_IN(P3)]: make }));
      const { onClose, onCreated } = renderDialog({ currentProjectId: null });
      await loaded();
      pick(P3);
      type("Отчёт");
      fireEvent.submit(form());
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toBe(errorMessage(code));
      expect(within(dialog()).getAllByRole("alert")).toHaveLength(1);
      expect(f.count(CREATE_IN(P3))).toBe(1);
      expect(screen.getByRole("dialog")).toBeTruthy();
      expect(projectSelect().value).toBe(P3);
      expect(titleInput().value).toBe("Отчёт");
      expect(onCreated).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      // busy снят: повторная отправка уходит
      await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
      fireEvent.submit(form());
      await waitFor(() => expect(f.count(CREATE_IN(P3))).toBe(2));
      await waitFor(() => expect(within(dialog()).getAllByRole("alert")).toHaveLength(1));
      expect(onCreated).not.toHaveBeenCalled();
    });
  }

  it("004_ac28_retry_after_error_can_succeed", async () => {
    let n = 0;
    const f = installFetch(
      routesU({ [CREATE_IN(P1)]: () => (++n === 1 ? err(503, "service_busy") : j(201, T_NEW)) }),
    );
    const { onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await screen.findByRole("alert");
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
    fireEvent.submit(form());
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
    expect(f.count(CREATE_IN(P1))).toBe(2);
  });

  it("004_ac28_new_attempt_clears_previous_error_alert", async () => {
    const gate = deferred<Response>();
    let n = 0;
    installFetch(routesU({ [CREATE_IN(P1)]: () => (++n === 1 ? err(503, "service_busy") : gate.promise) }));
    renderDialog({ currentProjectId: P1 });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await screen.findByRole("alert");
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).not.toBe("true"));
    fireEvent.submit(form());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    expect(within(dialog()).queryByRole("alert")).toBeNull();
    gate.resolve(j(201, T_NEW));
  });
});

describe("double submit (AC-30, FR-17)", () => {
  it("004_ac30_two_submits_and_click_send_one_request_aria_busy_until_response", async () => {
    const gate = deferred<Response>();
    const f = installFetch(routesU({ [CREATE_IN(P1)]: () => gate.promise }));
    const { onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    type("Отчёт");
    expect(submitBtn().getAttribute("aria-busy")).not.toBe("true");
    fireEvent.submit(form());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    expect(submitBtn().disabled).toBe(false);
    fireEvent.submit(form());
    fireEvent.click(submitBtn());
    expect(f.count(CREATE_IN(P1))).toBe(1);
    gate.resolve(j(201, T_NEW));
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBeNull());
    expect(f.count(CREATE_IN(P1))).toBe(1);
  });
});

describe("close during request (AC-31, FR-18)", () => {
  it("004_ac31_escape_during_request_keeps_dialog_then_created", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [CREATE_IN(P1)]: () => gate.promise }));
    const { onClose, onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    fireEvent.keyDown(titleInput(), { key: "Escape" });
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    gate.resolve(j(201, T_NEW));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_ac31_cancel_is_disabled_during_request_and_click_does_not_close", async () => {
    const gate = deferred<Response>();
    installFetch(routesU({ [CREATE_IN(P1)]: () => gate.promise }));
    const { onClose, onCreated } = renderDialog({ currentProjectId: P1 });
    await loaded();
    expect(cancelBtn().disabled).toBe(false);
    type("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(cancelBtn().disabled).toBe(true));
    fireEvent.click(cancelBtn());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    gate.resolve(j(201, T_NEW));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(T_NEW));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_ac31_escape_and_cancel_work_again_after_error", async () => {
    installFetch(routesU({ [CREATE_IN(P1)]: () => err(503, "service_busy") }));
    const { onClose } = renderDialog({ currentProjectId: P1 });
    await loaded();
    type("Отчёт");
    fireEvent.submit(form());
    await screen.findByRole("alert");
    await waitFor(() => expect(cancelBtn().disabled).toBe(false));
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(cancelBtn());
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("loading: early exit of the handler (AC-18, R5-T02 remainder)", () => {
  it("004_ac18_submit_while_list_loads_exits_early_even_if_disabled_removed_via_dom", async () => {
    const gate = deferred<Response>();
    const f = installFetch(routesU({ [LIST]: () => gate.promise }));
    renderDialog({ currentProjectId: P1 });
    await screen.findByRole("status");
    type("Отчёт");
    // Снимаем disabled через DOM: защита должна быть и в обработчике, а не только в атрибуте.
    submitBtn().removeAttribute("disabled");
    expect(submitBtn().disabled).toBe(false);
    fireEvent.click(submitBtn());
    fireEvent.submit(form());
    expect(posts(f)).toHaveLength(0);
    expect(within(dialog()).queryByRole("alert")).toBeNull(); // выход без сообщения
    expect(titleInput().value).toBe("Отчёт");
    // после загрузки списка та же форма работает: ранний выход не «ломает» отправку
    gate.resolve(j(200, page([listItem(P1, "Альфа")], 1, false, 100)));
    await loaded();
    expect(projectSelect().value).toBe(P1);
    expect(titleInput().value).toBe("Отчёт");
    fireEvent.submit(form());
    await waitFor(() => expect(f.count(CREATE_IN(P1))).toBe(1));
  });
});
