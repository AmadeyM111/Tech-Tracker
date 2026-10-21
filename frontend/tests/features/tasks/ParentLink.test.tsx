// R6-T03: ссылка «Родительская задача» в карточке подзадачи. spec 006 AC-47..AC-51, FR-32..FR-37; plan §4.8, PD-1.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { errorMessage } from "../../../src/shared/i18n";
import { Where, deferred, err, expectAt } from "../admin/helpers";
import { networkFail } from "./create-dialog-helpers";
import {
  PARENT_GET,
  PARENT_TITLE,
  TASK,
  TID1,
  TID2,
  card,
  d,
  expectTitle,
  installFetch,
  j,
  parentCard,
  subCard,
  subCardRoutes,
  titleNow,
  type Handler,
} from "./taskpage-helpers";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const PARENT_HREF = `/tasks/${TID2}`;

function renderNav(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const nav: { go?: NavigateFunction } = {};
  function Grab() {
    nav.go = useNavigate();
    return null;
  }
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
        <Grab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...out, qc, nav };
}

async function openSub(parentFn?: Handler, over: Record<string, Handler> = {}) {
  const f = installFetch(subCardRoutes(() => subCard(), parentFn, over));
  const view = renderNav(`/tasks/${TID1}`);
  await expectTitle("Шаг 1");
  return { f, ...view };
}

const props = () => document.querySelector<HTMLElement>("dl.ui-props")!;
const parentRow = () => document.querySelector<HTMLElement>('dd[data-field="parent"]');
const parentLink = () => parentRow()?.querySelector<HTMLAnchorElement>("a") ?? null;
const dtTexts = () => Array.from(props().querySelectorAll("dt")).map((e) => e.textContent);
const noAlert = () => expect(screen.queryAllByRole("alert")).toHaveLength(0);

describe("AC-47 ссылка на родителя", () => {
  it("ac47_parent_row_right_after_project_with_named_link", async () => {
    await openSub();
    const label = d("tasks.parent_label");
    expect(label).toBe("Родительская задача");
    const link = await screen.findByRole("link", { name: PARENT_TITLE });
    expect(link.getAttribute("href")).toBe(PARENT_HREF);
    expect(parentRow()!.contains(link)).toBe(true);
    const dts = dtTexts();
    const i = dts.indexOf(d("tasks.col_project"));
    expect(i).toBeGreaterThanOrEqual(0);
    expect(dts[i + 1]).toBe(label);
    // dd строки родителя - сразу после dd проекта
    const projectDd = props().querySelector('dd[data-field="project"]')!;
    expect(projectDd.nextElementSibling?.textContent).toBe(label);
    expect(projectDd.nextElementSibling?.nextElementSibling).toBe(parentRow());
  });
});

describe("AC-48 переход по ссылке", () => {
  it("ac48_click_opens_parent_card_focus_on_h1_back_returns_to_subtask", async () => {
    const { nav } = await openSub();
    fireEvent.click(await screen.findByRole("link", { name: PARENT_TITLE }));
    await expectAt(PARENT_HREF);
    await expectTitle(PARENT_TITLE);
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector("h1")));
    act(() => {
      nav.go!(-1);
    });
    await expectAt(`/tasks/${TID1}`);
    await expectTitle("Шаг 1");
  });
});

describe("AC-49 название родителя недоступно", () => {
  const FALLBACK = () => d("tasks.parent_open");

  function expectFallback() {
    const link = parentLink();
    expect(link).not.toBeNull();
    expect(link!.textContent).toBe(FALLBACK());
    expect(link!.getAttribute("href")).toBe(PARENT_HREF);
    expect(screen.getByRole("link", { name: "Открыть родительскую задачу" })).toBe(link);
    noAlert();
    expect(titleNow()).toBe("Шаг 1");
    expect(dtTexts()).toContain(d("tasks.col_status"));
  }

  it("ac49_pending_title_shows_fallback_then_replaced_by_title", async () => {
    const gate = deferred<Response>();
    await openSub(() => gate.promise);
    await waitFor(() => expect(parentLink()).not.toBeNull());
    expectFallback();
    gate.resolve(j(200, parentCard()));
    await screen.findByRole("link", { name: PARENT_TITLE });
    expect(parentLink()!.getAttribute("href")).toBe(PARENT_HREF);
  });

  it("ac49_http_500_shows_fallback_without_alert", async () => {
    const { f } = await openSub(() => err(500, "internal_error"));
    await waitFor(() => expect(f.count(PARENT_GET)).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(parentLink()).not.toBeNull());
    expectFallback();
    // повторных попыток нет (retry: false)
    expect(f.count(PARENT_GET)).toBe(1);
  });

  it("ac49_network_error_shows_fallback_without_alert", async () => {
    const { f } = await openSub(networkFail);
    await waitFor(() => expect(f.count(PARENT_GET)).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(parentLink()).not.toBeNull());
    expectFallback();
  });
});

describe("AC-50 задача верхнего уровня", () => {
  it("ac50_top_level_card_has_no_parent_row_and_no_parent_request", async () => {
    const f = installFetch(subCardRoutes(() => card({ parent_id: null })));
    renderNav(`/tasks/${TID1}`);
    await expectTitle("Подготовить отчёт");
    await screen.findByText(d("tasks.col_status"));
    expect(dtTexts()).not.toContain(d("tasks.parent_label"));
    expect(parentRow()).toBeNull();
    expect(screen.queryByText(d("tasks.parent_open"))).toBeNull();
    expect(f.count(PARENT_GET)).toBe(0);
  });
});

describe("AC-51 родитель удалён", () => {
  it("ac51_poll_tick_404_shows_not_found", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    const { f } = await openSub(undefined, { [TASK]: () => (n++ === 0 ? j(200, subCard()) : err(404, "not_found")) });
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.count(TASK)).toBeGreaterThan(1));
    await waitFor(() => expect(screen.getAllByText(errorMessage("not_found")).length).toBeGreaterThan(0));
  });

  it("ac51_parent_card_404_shows_not_found_and_no_empty_links", async () => {
    const { f } = await openSub(() => err(404, "not_found"));
    await waitFor(() => expect(f.count(PARENT_GET)).toBe(1));
    const link = await waitFor(() => {
      const l = parentLink();
      expect(l?.textContent).toBe(d("tasks.parent_open"));
      return l!;
    });
    fireEvent.click(link);
    await expectAt(PARENT_HREF);
    await waitFor(() => expect(screen.getAllByText(errorMessage("not_found")).length).toBeGreaterThan(0));
    for (const a of Array.from(document.querySelectorAll("a"))) {
      expect((a.textContent ?? "").trim().length > 0 || a.getAttribute("aria-label") !== null).toBe(true);
    }
  });
});
