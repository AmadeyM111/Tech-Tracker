// 011/AC-11: блок «Файлы» карточки задачи — список, права на удаление, загрузка сырым телом.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    created_at: "2026-11-08T09:00:00Z",
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
  return { ...out, alert };
}

afterEach(() => vi.unstubAllGlobals());

describe("Attachments", () => {
  it("lists_files_with_download_links_and_delete_only_by_rights", async () => {
    installFetch({
      [LIST]: () =>
        j(200, page([att("a1"), att("a2", { name: "скрин.png", kind: "png", inline: true, can_delete: true })])),
    });
    const { container } = mount();
    const pdf = await screen.findByRole("link", { name: "протокол.pdf" });
    expect(pdf.getAttribute("href")).toBe("/api/v1/attachments/a1/content");
    expect(pdf.getAttribute("download")).toBe("протокол.pdf");
    const png = screen.getByRole("link", { name: "скрин.png" });
    expect(png.getAttribute("target")).toBe("_blank");
    expect(container.querySelector('li[data-attachment-id="a1"] [data-action="delete-attachment"]')).toBeNull();
    expect(container.querySelector('li[data-attachment-id="a2"] [data-action="delete-attachment"]')).not.toBeNull();
    expect(screen.getAllByText(/2,0 КБ · ivanov/)).toHaveLength(2);
  });

  it("uploads_raw_body_with_name_query", async () => {
    const f = installFetch({
      [LIST]: () => j(200, page([])),
      [UPLOAD]: () => j(201, att("a3")),
    });
    mount();
    await screen.findByText("Файлов пока нет");
    const input = screen.getByLabelText("Прикрепить файл");
    const file = new File(["%PDF-1.4"], "отчёт.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(f.count(UPLOAD)).toBe(1));
    const req = f.last(UPLOAD);
    expect(decodeURIComponent(req.headers.get("x-file-name") ?? "")).toBe("отчёт.pdf");
    expect(f.query(req).get("name")).toBeNull();
    expect(req.headers.get("content-type")).toBe("application/octet-stream");
    expect(await req.text()).toBe("%PDF-1.4");
  });

  it("too_large_file_is_refused_without_a_request", async () => {
    const f = installFetch({ [LIST]: () => j(200, page([])) });
    const { alert } = mount();
    await screen.findByText("Файлов пока нет");
    const big = new File(["x"], "big.pdf");
    Object.defineProperty(big, "size", { value: 10 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByLabelText("Прикрепить файл"), { target: { files: [big] } });
    expect(alert.show).toHaveBeenCalledWith("Файл больше 10 МБ");
    expect(f.count(UPLOAD)).toBe(0);
  });

  it("server_refusal_is_shown_in_card_alert", async () => {
    installFetch({
      [LIST]: () => j(200, page([])),
      [UPLOAD]: () => j(422, { detail: "x", code: "attachment_type_not_allowed" }),
    });
    const { alert } = mount();
    await screen.findByText("Файлов пока нет");
    fireEvent.change(screen.getByLabelText("Прикрепить файл"), {
      target: { files: [new File(["<svg/>"], "logo.svg")] },
    });
    await waitFor(() => expect(alert.show).toHaveBeenCalled());
    expect(alert.show.mock.calls[0]?.[0]).toContain("Такой тип файла нельзя прикрепить");
  });

  it("formats_sizes", () => {
    expect(formatSize(512)).toBe("512 Б");
    expect(formatSize(10 * 1024 * 1024)).toBe("10,0 МБ");
  });
});
