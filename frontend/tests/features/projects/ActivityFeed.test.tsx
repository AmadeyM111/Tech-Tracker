// Лента проекта (FR-38, ADR-0015): вкладка «Лента» карточки проекта.
// Контракт API - GET /api/v1/projects/{id}/activity (plan §10.3); строки - из словаря ru.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../../src/shared/i18n";
import {
  ID_IVANOV,
  PID,
  R_IVANOV,
  BOARD_GET,
  BUSINESS,
  installFetch,
  j,
  page,
  projectRoutes,
  renderApp,
  emptyBoard,
  type Handler,
} from "./helpers";

const ACTIVITY = `GET /api/v1/projects/${PID}/activity`;

type Item = Record<string, unknown>;

function item(id: number, over: Item): Item {
  return {
    id,
    occurred_at: "2026-11-03T10:00:00Z",
    actor: { kind: "user", id: ID_IVANOV, login: R_IVANOV.login },
    action: "task.updated",
    entity: { type: "task", id: "99999999-9999-4999-8999-999999999999", deleted: false, title: "Новое" },
    changed_fields: ["status", "title"],
    changes: [{ field: "status", old: "todo", new: "done" }],
    ...over,
  };
}

async function openActivityTab() {
  await screen.findByRole("tablist");
  const tab = document.querySelector<HTMLElement>('[role="tab"][data-tab="activity"]');
  if (!tab) throw new Error("no activity tab");
  fireEvent.click(tab);
  await waitFor(() => expect(tab.getAttribute("aria-selected")).toBe("true"));
  return tab;
}

function activityRoutes(handler: Handler): Record<string, Handler> {
  return projectRoutes(BUSINESS, { [ACTIVITY]: handler, [BOARD_GET]: () => j(200, emptyBoard()) });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("лента проекта (FR-38)", () => {
  it("activity_tab_lists_events_in_order_with_dictionary_texts", async () => {
    installFetch(
      activityRoutes(() =>
        j(
          200,
          page([
            item(3, {
              action: "comment.deleted",
              changed_fields: [],
              changes: null,
              entity: { type: "comment", id: "c-1", deleted: true, title: null },
            }),
            item(2, {
              action: "project.updated",
              changed_fields: ["name"],
              changes: null,
              entity: { type: "project", id: PID, deleted: false, title: "Альфа" },
            }),
            item(1, {
              action: "task.created",
              actor: { kind: "system", id: null, login: null },
              changed_fields: [],
              changes: null,
            }),
          ]),
        ),
      ),
    );
    renderApp(`/projects/${PID}`);
    await openActivityTab();

    const rows = await waitFor(() => {
      const found = document.querySelectorAll<HTMLElement>('[data-field="activity-list"] > li');
      if (found.length === 0) throw new Error("feed not rendered yet");
      return found;
    });
    expect(rows.length).toBe(3);

    expect(rows[0]?.textContent).toContain(ru["activity.deleted"]);
    expect(rows[0]?.textContent).toContain(ru["activity.action.comment.deleted"]);
    expect(rows[1]?.textContent).toContain(ru["activity.action.project.updated"]);
    expect(rows[1]?.textContent).toContain("Альфа");
    expect(rows[1]?.textContent).toContain(ru["activity.field.name"]);
    expect(rows[2]?.textContent).toContain(ru["activity.system"]);
  });

  it("activity_status_change_shows_dictionary_labels_for_values", async () => {
    installFetch(activityRoutes(() => j(200, page([item(1, {})]))));
    renderApp(`/projects/${PID}`);
    await openActivityTab();

    const changes = await waitFor(() => {
      const el = document.querySelector<HTMLElement>('[data-field="changes"]');
      if (!el) throw new Error("no changes yet");
      return el;
    });
    expect(changes.textContent).toContain(ru["tasks.status.todo"]);
    expect(changes.textContent).toContain(ru["tasks.status.done"]);
    expect(changes.textContent).not.toContain("todo");
  });

  it("activity_empty_page_shows_empty_text", async () => {
    installFetch(activityRoutes(() => j(200, page([]))));
    renderApp(`/projects/${PID}`);
    await openActivityTab();
    expect(await screen.findByText(ru["activity.empty"])).toBeTruthy();
  });

  it("activity_forbidden_shows_error_alert", async () => {
    installFetch(activityRoutes(() => j(403, { detail: "нет доступа", code: "forbidden" })));
    renderApp(`/projects/${PID}`);
    await openActivityTab();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.forbidden"]);
  });

  it("activity_next_page_requests_page_two", async () => {
    const seen: string[] = [];
    installFetch(
      activityRoutes((r) => {
        seen.push(new URL(r.url).searchParams.get("page") ?? "");
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([item(p, {})], p, p === 1));
      }),
    );
    renderApp(`/projects/${PID}`);
    await openActivityTab();
    const next = await waitFor(() => {
      const b = document.querySelector<HTMLButtonElement>('[data-action="next-page"]');
      if (!b || b.disabled) throw new Error("next not ready");
      return b;
    });
    fireEvent.click(next);
    await waitFor(() => expect(seen).toContain("2"));
    expect(seen[0]).toBe("1");
  });
});

// Аудит #9: пустая лента - без пагинации; непустая - с пагинацией.
describe("пагинация ленты при пустом списке (аудит #9)", () => {
  it("empty_feed_has_no_pagination", async () => {
    installFetch(activityRoutes(() => j(200, page([]))));
    const { container } = renderApp(`/projects/${PID}`);
    await openActivityTab();
    expect(await screen.findByText(ru["activity.empty"])).toBeTruthy();
    expect(container.querySelector(".ui-pagination")).toBeNull();
    expect(container.querySelector('[data-action="next-page"]')).toBeNull();
  });

  it("non_empty_feed_single_page_hides_pagination", async () => {
    installFetch(activityRoutes(() => j(200, page([item(1, {})]))));
    const { container } = renderApp(`/projects/${PID}`);
    await openActivityTab();
    await waitFor(() => expect(container.querySelector('[data-field="activity-list"]')).toBeTruthy());
    expect(container.querySelector(".ui-pagination")).toBeNull();
  });
});
