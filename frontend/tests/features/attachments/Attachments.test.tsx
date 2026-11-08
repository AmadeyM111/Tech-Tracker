// 011/AC-11 и макеты (утверждены 2026-11-08): список, «Открыть»/«Скачать», «Удалить» по правам с
// подтверждением, счётчик и лимит, загрузка сырым телом, ошибки внутри раздела.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Attachments, formatSize } from "../../../src/features/attachments/Attachments";
import { installFetch, j } from "../admin/helpers";

const TASK = "d1d1d1d1-0000-4000-8000-000000000001";
const LIST = `GET /api/v1/tasks/${TASK}/attachments`;
const UPLOAD = `POST /api/v1/tasks/${TASK}/attachments`;

function att(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    task_id: TASK,
    name: "протокол.pdf",
    kind: "pdf",
    content_type: "application/pdf",
    size_bytes: 2048,
    created_at: "2026-11-08T07:14:00Z",
    author: { id: "u1", login: "ivanov" },
    inline: false,
    can_delete: false,
    ...over,
  };
}

const page = (items: unknown[]) => ({ items, page: 1, page_size: 50, has_next: false });

function mount() {
  const alert = { message: null as string | null, seq: 0, show: vi.fn(), clear: vi.fn() };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const out = render(
    <QueryClientProvider client={qc}>
      <Attachments taskId={TASK} alert={alert} />
    </QueryClientProvider>,
  );
  const fileInput = () => out.container.querySelector<HTMLInputElement>('input[type="file"]')!;
  return { ...out, alert, fileInput };
}

afterEach(() => vi.unstubAllGlobals());

describe("Attachments", () => {
  it("list_open_before_download_delete_only_by_rights_and_counter", async () => {
    installFetch({
      [LIST]: () =>
        j(200, page([att("a1"), att("a2", { name: "скрин.png", kind: "png", inline: true, can_delete: true })])),
    });
    const { container } = mount();
    await screen.findByText("протокол.pdf");
    const pdfRow = container.querySelector<HTMLElement>('li[data-attachment-id="a1"]')!;
    expect(within(pdfRow).queryByRole("link", { name: "Открыть" })).toBeNull();
    const pdfDownload = within(pdfRow).getByRole("link", { name: "Скачать" });
    expect(pdfDownload.getAttribute("href")).toBe("/api/v1/attachments/a1/content");
    expect(pdfDownload.getAttribute("download")).toBe("протокол.pdf");
    expect(within(pdfRow).queryByRole("button", { name: "Удалить" })).toBeNull();
    const pngRow = container.querySelector<HTMLElement>('li[data-attachment-id="a2"]')!;
    const actions = Array.from(pngRow.querySelectorAll("[data-action]")).map((e) => e.textContent);
    expect(actions).toEqual(["Открыть", "Скачать", "Удалить"]);
    expect(within(pngRow).getByRole("link", { name: "Открыть" }).getAttribute("target")).toBe("_blank");
    expect(pdfRow.querySelector(".att-kind")?.textContent).toBe("PDF");
    expect(pdfRow.querySelector(".att-meta")?.textContent).toBe("2 КБ · ivanov · 08.11, 10:14");
    expect(screen.getByText("Вложений: 2 из 20")).toBeTruthy();
    expect(screen.getByText("Удалить вложение может его автор или тот, кто полностью правит задачу.")).toBeTruthy();
  });

  it("uploads_raw_body_with_name_header", async () => {
    const f = installFetch({ [LIST]: () => j(200, page([])), [UPLOAD]: () => j(201, att("a3")) });
    const { fileInput } = mount();
    await screen.findByText("Вложений: 0 из 20");
    expect(screen.getByRole("button", { name: "Выбрать файл" })).toBeTruthy();
    const file = new File(["%PDF-1.4"], "отчёт.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput(), { target: { files: [file] } });
    await waitFor(() => expect(f.count(UPLOAD)).toBe(1));
    const req = f.last(UPLOAD);
    expect(decodeURIComponent(req.headers.get("x-file-name") ?? "")).toBe("отчёт.pdf");
    expect(f.query(req).get("name")).toBeNull();
    expect(req.headers.get("content-type")).toBe("application/octet-stream");
    expect(await req.text()).toBe("%PDF-1.4");
  });

  it("too_large_file_is_refused_in_section_without_a_request", async () => {
    const f = installFetch({ [LIST]: () => j(200, page([])) });
    const { fileInput } = mount();
    await screen.findByText("Вложений: 0 из 20");
    const big = new File(["x"], "big.pdf");
    Object.defineProperty(big, "size", { value: 10 * 1024 * 1024 + 1 });
    fireEvent.change(fileInput(), { target: { files: [big] } });
    expect(screen.getByRole("alert").textContent).toBe(
      "Файл больше 10 МБ. Выберите файл меньше или разбейте его на части.",
    );
    expect(f.count(UPLOAD)).toBe(0);
  });

  it.each([
    ["attachment_type_not_allowed", 422, "Этот тип файла не принимается"],
    ["storage_full", 507, "На сервере мало места"],
  ])("server_error_%s_is_shown_in_section", async (code, status, text) => {
    installFetch({ [LIST]: () => j(200, page([])), [UPLOAD]: () => j(status, { detail: "x", code }) });
    const { fileInput } = mount();
    await screen.findByText("Вложений: 0 из 20");
    fireEvent.change(fileInput(), { target: { files: [new File(["<svg/>"], "logo.svg")] } });
    expect((await screen.findByRole("alert")).textContent).toContain(text);
  });

  it("limit_reached_disables_upload", async () => {
    const items = Array.from({ length: 20 }, (_, i) => att(`a${i}`));
    installFetch({ [LIST]: () => j(200, page(items)) });
    const { container } = mount();
    await screen.findByText("Вложений: 20 из 20");
    expect(screen.getByText("Достигнут лимит: 20 вложений у задачи")).toBeTruthy();
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("delete_asks_confirmation_with_30_days_text", async () => {
    const f = installFetch({
      [LIST]: () => j(200, page([att("a1", { can_delete: true })])),
      "DELETE /api/v1/attachments/a1": () => new Response(null, { status: 204 }),
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Удалить вложение?")).toBeTruthy();
    expect(within(dialog).getByText("Файл «протокол.pdf» станет недоступен. Окончательно он удалится через 30 дней.")).toBeTruthy();
    expect(f.count("DELETE /api/v1/attachments/a1")).toBe(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(f.count("DELETE /api/v1/attachments/a1")).toBe(1));
  });

  it("not_member_sees_one_line", async () => {
    installFetch({ [LIST]: () => j(403, { detail: "x", code: "forbidden" }) });
    mount();
    expect(await screen.findByText("Вложения видны участникам проекта.")).toBeTruthy();
  });

  it("formats_sizes_like_mockup", () => {
    expect(formatSize(512)).toBe("512 Б");
    expect(formatSize(240 * 1024)).toBe("240 КБ");
    expect(formatSize(1.2 * 1024 * 1024)).toBe("1,2 МБ");
  });
});
