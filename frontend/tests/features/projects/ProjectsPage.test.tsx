// T82: экран /projects (контракт разметки - в шапке helpers.tsx).
// AC: UF-3, FR-14 (создание, AC-51), FR-17 (список без статуса, AC-55), NFR-6, NFR-7.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectsPage } from "../../../src/features/projects/ProjectsPage";
import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  BUSINESS,
  BUSINESS_NO_CREATE,
  CREATE,
  LIST,
  ME,
  ONE,
  MEMBERS,
  PID,
  PID2,
  R_PETROV,
  action,
  cell,
  deferred,
  detail,
  err,
  expectAt,
  installFetch,
  j,
  listItem,
  meWith,
  page,
  renderApp,
  where,
  wraps,
  type Handler,
} from "./helpers";

const DICT = Object.values(ru) as string[];
type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

const ITEMS = [listItem(PID, "Альфа", undefined, 3), listItem(PID2, "Бета", R_PETROV, 0)];

function setup(over: Record<string, Handler> = {}, caps: string[] = BUSINESS) {
  f = installFetch({
    [ME]: () => j(200, meWith(caps, "business_admin")),
    [LIST]: () => j(200, page(ITEMS)),
    ...over,
  });
}

async function open(over: Record<string, Handler> = {}, caps: string[] = BUSINESS) {
  setup(over, caps);
  const view = renderApp("/projects");
  await waitFor(() => expect(view.container.querySelector("tr[data-project-id]")).toBeTruthy());
  return view;
}

const form = (c: HTMLElement) => c.querySelector<HTMLFormElement>('form[data-form="create-project"]');
function fill(c: HTMLElement, name: string, description = "") {
  fireEvent.change(c.querySelector('input[name="name"]')!, { target: { value: name } });
  fireEvent.change(c.querySelector('textarea[name="description"]')!, { target: { value: description } });
}
const submit = (c: HTMLElement) => fireEvent.submit(form(c)!);
const body = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("module (T82)", () => {
  it("projects_page_is_exported", () => {
    expect(typeof ProjectsPage).toBe("function");
  });
});

describe("list and pagination (AC-55, FR-17)", () => {
  it("ac55_lists_projects_with_name_owner_and_task_count_without_status", async () => {
    const { container } = await open();
    const rows = container.querySelectorAll<HTMLElement>("tr[data-project-id]");
    expect(rows.length).toBe(2);
    const a = container.querySelector<HTMLElement>(`tr[data-project-id="${PID}"]`)!;
    const b = container.querySelector<HTMLElement>(`tr[data-project-id="${PID2}"]`)!;
    expect(cell(a, "name").textContent).toBe("Альфа");
    expect(cell(a, "owner").textContent).toBe("ivanov");
    expect(cell(a, "task_count").textContent).toBe("3");
    expect(cell(b, "owner").textContent).toBe("petrov");
    expect(cell(b, "task_count").textContent).toBe("0");
    const link = within(cell(a, "name")).getByRole("link");
    expect(link.getAttribute("href")).toBe(`/projects/${PID}`);
    expect(a.querySelector('[data-field="status"]')).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(ru["projects.title"]);
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
  });

  it("uf3_project_name_link_opens_the_card", async () => {
    const { container } = await open({
      [ONE]: () => j(200, detail()),
      [MEMBERS]: () => j(200, page([])),
    });
    fireEvent.click(within(cell(container.querySelector(`tr[data-project-id="${PID}"]`)!, "name")).getByRole("link"));
    await expectAt(`/projects/${PID}`);
  });

  it("pagination_next_and_prev_request_pages_and_respect_has_next", async () => {
    const { container } = await open({
      [LIST]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([p === 1 ? ITEMS[0] : ITEMS[1]], p, p === 1));
      },
    });
    expect(action(container, "prev-page").disabled).toBe(true);
    expect(action(container, "next-page").disabled).toBe(false);
    fireEvent.click(action(container, "next-page"));
    await waitFor(() => expect(container.querySelector(`tr[data-project-id="${PID2}"]`)).toBeTruthy());
    expect(f.query(f.last(LIST)).get("page")).toBe("2");
    expect(action(container, "next-page").disabled).toBe(true);
    fireEvent.click(action(container, "prev-page"));
    await waitFor(() => expect(container.querySelector(`tr[data-project-id="${PID}"]`)).toBeTruthy());
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
  });

  it("list_error_is_shown_via_error_message_in_alert", async () => {
    setup({ [LIST]: () => err(500, "internal_error") });
    const { container } = renderApp("/projects");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("internal_error"));
    expect(container.querySelector("tr[data-project-id]")).toBeNull();
  });

  it("fr59_user_requests_never_carry_background_header", async () => {
    await open();
    for (const c of f.calls) expect(c.headers.get("X-GT-Background")).toBeNull();
  });
});

describe("create form (FR-14, AC-51)", () => {
  it("ac51_form_has_labelled_fields_with_name_limit_255", async () => {
    const { container } = await open();
    expect(form(container)).toBeTruthy();
    const name = screen.getByLabelText(/./, { selector: 'input[name="name"]' }) as HTMLInputElement;
    expect(name.maxLength).toBe(255);
    expect(screen.getByLabelText(/./, { selector: 'textarea[name="description"]' })).toBeTruthy();
    expect(form(container)!.querySelector('button[type="submit"]')).toBeTruthy();
  });

  it("without_project_create_there_is_no_form_but_list_remains", async () => {
    const { container } = await open({}, BUSINESS_NO_CREATE);
    expect(form(container)).toBeNull();
    expect(container.querySelector('input[name="name"]')).toBeNull();
    expect(container.querySelector("tr[data-project-id]")).toBeTruthy();
  });

  it("ac51_submit_posts_name_and_description_and_opens_new_project", async () => {
    const created = detail({ id: PID2, name: "Гамма", description: "Про гамму" });
    const { container } = await open({
      [CREATE]: () => j(201, created),
      [`GET /api/v1/projects/${PID2}`]: () => j(200, created),
      [`GET /api/v1/projects/${PID2}/members`]: () => j(200, page([])),
    });
    fill(container, "Гамма", "Про гамму");
    submit(container);
    await expectAt(`/projects/${PID2}`);
    expect(await body(f.last(CREATE))).toMatchObject({ name: "Гамма", description: "Про гамму" });
    expect(f.count(CREATE)).toBe(1);
  });

  it("ac51_empty_name_sends_nothing_and_shows_validation_alert", async () => {
    const { container } = await open({ [CREATE]: () => j(201, detail()) });
    fill(container, "   ", "x");
    submit(container);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(f.count(CREATE)).toBe(0);
  });

  it.each([
    [422, "validation_error"],
    [400, "bad_request"],
    [403, "forbidden"],
  ])("ac51_create_error_%s_%s_is_shown_and_input_kept", async (status, code) => {
    const { container } = await open({ [CREATE]: () => err(status, code) });
    fill(container, "Дельта", "текст");
    submit(container);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(DICT).toContain(alert.textContent);
    expect(where()).toBe("/projects");
    expect((container.querySelector('input[name="name"]') as HTMLInputElement).value).toBe("Дельта");
    expect((container.querySelector('textarea[name="description"]') as HTMLTextAreaElement).value).toBe("текст");
  });

  it("double_submit_while_in_flight_sends_one_post", async () => {
    const d = deferred<Response>();
    const { container } = await open({ [CREATE]: () => d.promise });
    fill(container, "Эпсилон");
    submit(container);
    submit(container);
    fireEvent.click(form(container)!.querySelector('button[type="submit"]')!);
    await waitFor(() => expect(f.count(CREATE)).toBe(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(f.count(CREATE)).toBe(1);
    d.resolve(j(422, { detail: "validation_error", code: "validation_error" }));
    await screen.findByRole("alert");
  });
});

describe("review T82 attempt 2", () => {
  it("nfr7_pagination_busy_keeps_focusable_buttons_with_aria_disabled", async () => {
    const d = deferred<Response>();
    const { container } = await open({
      [LIST]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return p === 1 ? j(200, page([ITEMS[0]], 1, true)) : d.promise;
      },
    });
    const next = action(container, "next-page");
    next.focus();
    fireEvent.click(next);
    await waitFor(() => expect(f.count(LIST)).toBe(2));
    expect(next.disabled).toBe(false);
    expect(next.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(next);
    fireEvent.click(next);
    await new Promise((r) => setTimeout(r, 30));
    expect(f.count(LIST)).toBe(2);
    d.resolve(j(200, page([ITEMS[1]], 2, false)));
    await waitFor(() => expect(container.querySelector(`tr[data-project-id="${PID2}"]`)).toBeTruthy());
    expect(document.activeElement).not.toBe(document.body);
  });

  it("nfr7_focus_is_not_lost_after_create_and_navigation", async () => {
    const created = detail({ id: PID2, name: "Гамма" });
    const { container } = await open({
      [CREATE]: () => j(201, created),
      [`GET /api/v1/projects/${PID2}`]: () => j(200, created),
      [`GET /api/v1/projects/${PID2}/members`]: () => j(200, page([])),
    });
    fill(container, "Гамма");
    fireEvent.click(form(container)!.querySelector('button[type="submit"]')!);
    await expectAt(`/projects/${PID2}`);
    await screen.findByRole("heading", { level: 1, name: "Гамма" });
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
  });

  it("nfr6_long_unbroken_name_wraps_in_heading_and_table_cells", async () => {
    const long = "Ж".repeat(200);
    const { container } = await open({ [LIST]: () => j(200, page([listItem(PID, long)])) });
    expect(wraps(screen.getByRole("heading", { level: 1 }))).toBe(true);
    const c = cell(container.querySelector("tr[data-project-id]")!, "name");
    expect(wraps(c)).toBe(true);
  });
});
