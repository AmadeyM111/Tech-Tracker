// T85: комментарии в карточке задачи.
// AC: UF-6, FR-23/SC-11, FR-29, AC-58 (интерфейс), NFR-5, NFR-6, NFR-7. Контракт разметки - в helpers.tsx.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { errorMessage } from "../../../src/shared/i18n";
import {
  CID1,
  CID2,
  CID3,
  COMMENTS_GET,
  COMMENT_POST,
  CP_ALL,
  CP_NONE,
  C_DELETE,
  C_PATCH,
  act,
  comment,
  createArea,
  createForm,
  d,
  deferred,
  editArea,
  editForm,
  err,
  field,
  fireEvent,
  item,
  j,
  openWithComments,
  page,
  screen,
  setValue,
  slot,
  waitCount,
} from "./helpers";

const bodyOf = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
const NO_CONTENT = () => new Response(null, { status: 204 });
const submit = (el: Element | null) => fireEvent.submit(el!);

describe("list rendering (UF-6, FR-23, AC-58, NFR-5)", () => {
  it("uf6_comments_section_is_mounted_in_task_page_slot", async () => {
    const { container } = await openWithComments([comment(CID1, "Привет")]);
    const s = slot(container);
    expect(s.querySelector('[data-section="comments"]')).not.toBeNull();
    expect(item(s, CID1)).not.toBeNull();
  });

  it("uf6_item_shows_author_text_and_moscow_time", async () => {
    const { container } = await openWithComments([comment(CID1, "Привет")]);
    const el = item(container, CID1)!;
    expect(field(el, "author")!.textContent).toBe("kuznetsov");
    expect(field(el, "body")!.textContent).toBe("Привет");
    // 2026-10-12T21:30:00Z -> 13.10.2026 00:30 MSK (UTC+3), как в журнале аудита.
    expect(field(el, "created_at")!.textContent).toBe("13.10.2026, 00:30");
    expect(field(el, "created_at")!.querySelector("time")!.getAttribute("datetime")).toBe("2026-10-12T21:30:00Z");
  });

  it("uf6_empty_list_shows_empty_text", async () => {
    const { container } = await openWithComments([]);
    expect(slot(container).querySelector('[data-role="empty"]')!.textContent).toBe(d("comments.empty"));
  });

  it("ac58_edited_marker_only_when_edited_at_set", async () => {
    const { container } = await openWithComments([
      comment(CID1, "Первый", { edited_at: "2026-10-13T10:00:00Z" }),
      comment(CID2, "Второй"),
    ]);
    expect(field(item(container, CID1)!, "edited")!.textContent).toBe(d("comments.edited"));
    expect(field(item(container, CID2)!, "edited")).toBeNull();
  });

  it("ac58_deleted_comment_is_stub_with_author_and_time_without_text", async () => {
    const { container } = await openWithComments([
      comment(CID1, null, { is_deleted: true, created_at: "2026-10-12T21:30:00Z" }),
    ]);
    const el = item(container, CID1)!;
    expect(el.getAttribute("data-deleted")).toBe("true");
    expect(field(el, "deleted")!.textContent).toBe(d("comments.deleted"));
    expect(field(el, "author")!.textContent).toBe("kuznetsov");
    expect(field(el, "created_at")!.textContent).toBe("13.10.2026, 00:30");
    expect(field(el, "body")).toBeNull();
    expect(act(el, "edit-comment")).toBeNull();
    expect(act(el, "delete-comment")).toBeNull();
  });

  it("fr23_html_like_text_is_shown_literally_in_pre_wrap_text_node", async () => {
    const raw = '<img src=x onerror="alert(1)"><b>жирный</b>\nвторая строка & <script>1</script>';
    const { container } = await openWithComments([comment(CID1, raw)]);
    const body = field(item(container, CID1)!, "body")!;
    expect(body.style.whiteSpace).toBe("pre-wrap");
    expect(body.textContent).toBe(raw);
    expect(body.children.length).toBe(0);
    expect(slot(container).querySelector("img, b, script")).toBeNull();
  });

  it("fr23_source_has_no_inner_html_or_markdown", () => {
    const src = readFileSync(resolve(__dirname, "../../../src/features/comments/Comments.tsx"), "utf8");
    expect(src).not.toContain("dangerouslySetInnerHTML");
    expect(src).not.toMatch(/markdown/i);
  });
});

describe("permissions (UF-6, NFR-7)", () => {
  it("nfr7_no_permission_means_no_edit_or_delete_elements", async () => {
    const { container } = await openWithComments([comment(CID1, "Чужой", { permissions: CP_NONE })]);
    const el = item(container, CID1)!;
    expect(act(el, "edit-comment")).toBeNull();
    expect(act(el, "delete-comment")).toBeNull();
  });

  it("nfr7_permissions_are_applied_independently_per_action", async () => {
    const { container } = await openWithComments([
      comment(CID1, "Только правка", { permissions: { edit: true, delete: false } }),
      comment(CID2, "Только удаление", { permissions: { edit: false, delete: true } }),
    ]);
    expect(act(item(container, CID1)!, "edit-comment")).not.toBeNull();
    expect(act(item(container, CID1)!, "delete-comment")).toBeNull();
    expect(act(item(container, CID2)!, "edit-comment")).toBeNull();
    expect(act(item(container, CID2)!, "delete-comment")).not.toBeNull();
  });
});

describe("create comment (UF-6, NFR-6, NFR-7)", () => {
  it("uf6_post_has_trimmed_body_form_is_cleared_focused_and_list_refetched", async () => {
    let created = false;
    const list = [comment(CID1, "Старый")];
    const { container, f } = await openWithComments(list, {
      [COMMENT_POST]: () => {
        created = true;
        return j(201, comment(CID2, "Новый\nкомментарий"));
      },
    });
    // GET отдаёт обновлённый список после создания.
    const before = f.count(COMMENTS_GET);
    expect(createArea(container).labels?.length).toBeTruthy();
    expect(createArea(container).labels![0]!.textContent).toBe(d("comments.body_label"));
    setValue(createArea(container), "  Новый\nкомментарий \n");
    list.push(comment(CID2, "Новый\nкомментарий"));
    submit(createForm(container));
    await waitCount(f, COMMENT_POST, 1);
    expect(created).toBe(true);
    expect(await bodyOf(f.last(COMMENT_POST))).toEqual({ body: "Новый\nкомментарий" });
    await waitFor(() => expect(item(container, CID2)).not.toBeNull());
    expect(f.count(COMMENTS_GET)).toBeGreaterThan(before);
    expect(createArea(container).value).toBe("");
    expect(document.activeElement).toBe(createArea(container));
  });

  it.each(["", "   \n  "])("ac56_blank_input_%j_is_not_sent_and_shows_validation_alert", async (v) => {
    const { container, f } = await openWithComments([]);
    setValue(createArea(container), v);
    submit(createForm(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(f.count(COMMENT_POST)).toBe(0);
  });

  it("nfr7_double_submit_sends_single_post", async () => {
    const gate = deferred<Response>();
    const { container, f } = await openWithComments([], { [COMMENT_POST]: () => gate.promise });
    setValue(createArea(container), "Один раз");
    submit(createForm(container));
    submit(createForm(container));
    fireEvent.click(createForm(container)!.querySelector('button[type="submit"]')!);
    await waitCount(f, COMMENT_POST, 1);
    gate.resolve(j(201, comment(CID1, "Один раз")));
    await new Promise((r) => setTimeout(r, 50));
    expect(f.count(COMMENT_POST)).toBe(1);
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
    [422, "validation_error"],
    [503, "service_busy"],
  ])("nfr6_post_error_%i_shows_single_alert_by_code_and_keeps_input", async (status, code) => {
    const { container } = await openWithComments([], { [COMMENT_POST]: () => err(status, code) });
    setValue(createArea(container), "Мой текст");
    submit(createForm(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(createArea(container).value).toBe("Мой текст");
  });
});

describe("edit comment (UF-6, NFR-7)", () => {
  const mine = () => [comment(CID1, "Исходный текст", { permissions: CP_ALL })];

  it("uf6_edit_opens_prefilled_focused_inline_form", async () => {
    const { container } = await openWithComments(mine());
    const el = item(container, CID1)!;
    fireEvent.click(act(el, "edit-comment")!);
    const ta = editArea(el);
    expect(ta.value).toBe("Исходный текст");
    expect(ta.labels![0]!.textContent).toBe(d("comments.edit_label"));
    expect(document.activeElement).toBe(ta);
  });

  it("uf6_edit_submit_sends_patch_trimmed_closes_form_and_shows_new_text", async () => {
    const list = mine();
    const { container, f } = await openWithComments(list, {
      [C_PATCH(CID1)]: () => j(200, comment(CID1, "Новый текст", { permissions: CP_ALL, edited_at: "2026-10-13T10:00:00Z" })),
    });
    const el = item(container, CID1)!;
    fireEvent.click(act(el, "edit-comment")!);
    setValue(editArea(el), "  Новый текст ");
    list[0] = comment(CID1, "Новый текст", { permissions: CP_ALL, edited_at: "2026-10-13T10:00:00Z" });
    submit(editForm(el));
    await waitCount(f, C_PATCH(CID1), 1);
    expect(await bodyOf(f.last(C_PATCH(CID1)))).toEqual({ body: "Новый текст" });
    await waitFor(() => expect(editForm(item(container, CID1)!)).toBeNull());
    await waitFor(() => expect(field(item(container, CID1)!, "body")!.textContent).toBe("Новый текст"));
    expect(field(item(container, CID1)!, "edited")).not.toBeNull();
  });

  it("nfr7_escape_cancels_without_request_and_returns_focus_to_edit_button", async () => {
    const { container, f } = await openWithComments(mine());
    const el = item(container, CID1)!;
    fireEvent.click(act(el, "edit-comment")!);
    setValue(editArea(el), "Черновик");
    fireEvent.keyDown(editArea(el), { key: "Escape" });
    await waitFor(() => expect(editForm(item(container, CID1)!)).toBeNull());
    expect(f.count(C_PATCH(CID1))).toBe(0);
    expect(field(item(container, CID1)!, "body")!.textContent).toBe("Исходный текст");
    expect(document.activeElement).toBe(act(item(container, CID1)!, "edit-comment"));
  });

  it("nfr7_cancel_button_closes_form_without_request", async () => {
    const { container, f } = await openWithComments(mine());
    const el = item(container, CID1)!;
    fireEvent.click(act(el, "edit-comment")!);
    fireEvent.click(act(el, "cancel-edit")!);
    await waitFor(() => expect(editForm(item(container, CID1)!)).toBeNull());
    expect(f.count(C_PATCH(CID1))).toBe(0);
  });

  it("ac96_blank_edit_is_not_sent", async () => {
    const { container, f } = await openWithComments(mine());
    const el = item(container, CID1)!;
    fireEvent.click(act(el, "edit-comment")!);
    setValue(editArea(el), "   ");
    submit(editForm(el));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(f.count(C_PATCH(CID1))).toBe(0);
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
    [422, "validation_error"],
    [503, "service_busy"],
  ])("nfr6_patch_error_%i_single_alert_form_stays_open_input_kept", async (status, code) => {
    const { container } = await openWithComments(mine(), { [C_PATCH(CID1)]: () => err(status, code) });
    const el = item(container, CID1)!;
    fireEvent.click(act(el, "edit-comment")!);
    setValue(editArea(el), "Правка");
    submit(editForm(el));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(editArea(item(container, CID1)!).value).toBe("Правка");
  });
});

describe("delete comment (UF-6, NFR-7)", () => {
  const mine = () => [comment(CID1, "Удаляемый", { permissions: CP_ALL })];

  it("nfr7_delete_needs_confirmation_then_sends_delete_and_refetches", async () => {
    const list = mine();
    const { container, f } = await openWithComments(list, { [C_DELETE(CID1)]: () => NO_CONTENT() });
    fireEvent.click(act(item(container, CID1)!, "delete-comment")!);
    const dlg = await screen.findByRole("alertdialog");
    expect(dlg.textContent).toContain(d("comments.delete_confirm_message"));
    expect(f.count(C_DELETE(CID1))).toBe(0);
    const before = f.count(COMMENTS_GET);
    list[0] = comment(CID1, null, { is_deleted: true });
    fireEvent.click(dlg.querySelector('button[data-action="confirm"]')!);
    await waitCount(f, C_DELETE(CID1), 1);
    await waitFor(() => expect(item(container, CID1)!.getAttribute("data-deleted")).toBe("true"));
    expect(f.count(COMMENTS_GET)).toBeGreaterThan(before);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("nfr7_cancel_sends_no_request_and_keeps_comment", async () => {
    const { container, f } = await openWithComments(mine());
    fireEvent.click(act(item(container, CID1)!, "delete-comment")!);
    const dlg = await screen.findByRole("alertdialog");
    fireEvent.click(dlg.querySelector('button[data-action="cancel"]')!);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(C_DELETE(CID1))).toBe(0);
    expect(field(item(container, CID1)!, "body")!.textContent).toBe("Удаляемый");
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
    [503, "service_busy"],
  ])("nfr6_delete_error_%i_shows_single_alert_by_code", async (status, code) => {
    const { container } = await openWithComments(mine(), { [C_DELETE(CID1)]: () => err(status, code) });
    fireEvent.click(act(item(container, CID1)!, "delete-comment")!);
    const dlg = await screen.findByRole("alertdialog");
    fireEvent.click(dlg.querySelector('button[data-action="confirm"]')!);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });
});

describe("pagination (UF-6)", () => {
  it("uf6_next_page_requests_page_2_and_shows_its_comments", async () => {
    const { container, f } = await openWithComments([], {
      [COMMENTS_GET]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, p === 1 ? page([comment(CID1, "Стр1")], 1, true) : page([comment(CID2, "Стр2")], 2, false));
      },
    });
    await waitFor(() => expect(item(container, CID1)).not.toBeNull());
    fireEvent.click(slot(container).querySelector('button[data-action="next-page"]')!);
    await waitFor(() => expect(f.query(f.last(COMMENTS_GET)).get("page")).toBe("2"));
    await waitFor(() => expect(item(container, CID2)).not.toBeNull());
    expect(item(container, CID1)).toBeNull();
  });
});

describe("polling (FR-29)", () => {
  it("fr29_background_poll_refreshes_list_and_keeps_typed_text", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    const { container, f } = await openWithComments([], {
      [COMMENTS_GET]: () => {
        n += 1;
        return j(200, page(n === 1 ? [] : [comment(CID3, "Пришло с опросом")]));
      },
    });
    expect(f.last(COMMENTS_GET).headers.get("X-GT-Background")).toBeNull();
    setValue(createArea(container), "Мой черновик");
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() => expect(f.last(COMMENTS_GET).headers.get("X-GT-Background")).toBe("1"));
    await waitFor(() => expect(item(container, CID3)).not.toBeNull());
    expect(createArea(container).value).toBe("Мой черновик");
  });
});
