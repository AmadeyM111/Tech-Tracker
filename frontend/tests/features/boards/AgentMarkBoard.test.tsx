// R7-T20: метка «ИИ» на карточке доски и в списке задач проекта (007/FR-31, AC-37 - автотесты компонентов).
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../../src/shared/i18n";
import { ID_KUZNETSOV, PID, TA, TB, TC, CA, CB, CC, INITIAL, R_ME, cardEl, filterSelect, openBoard, ref } from "./helpers";
import { TID1, TID2, TID3, installFetch, openTasksTab, renderApp, taskItem, taskRoutes, taskRow } from "../tasks/helpers";

const BOT = { ...ref("99999999-9999-4999-8999-999999999991", "bot-agent"), is_agent: true };
const HUMAN = { ...ref(ID_KUZNETSOV, "kuznetsov"), is_agent: false };
const MARK = "abbr.ui-agent-mark";
const marks = (el: ParentNode) => Array.from(el.querySelectorAll<HTMLElement>(MARK));
const asg = (el: ParentNode) => el.querySelector<HTMLElement>('[data-field="assignee"]')!;

describe("R7-T20 доска", () => {
  const columns = {
    ...INITIAL,
    todo: [
      { ...CA, assignee: BOT },
      { ...CB, assignee: HUMAN },
      { ...CC, assignee: null },
    ],
  };

  it("007_fr31_board_card_mark_only_for_agent_assignee", async () => {
    const { container } = await openBoard({}, columns);
    const a = asg(cardEl(container, TA)!);
    expect(marks(a)).toHaveLength(1);
    expect(marks(a)[0]!.textContent).toBe("ИИ");
    expect(marks(a)[0]!.getAttribute("title")).toBe("ИИ-агент");
    expect(a.textContent!.replace("ИИ", "").trim()).toBe("bot-agent");
    const h = asg(cardEl(container, TB)!);
    expect(h.textContent).toBe("kuznetsov");
    expect(marks(h)).toHaveLength(0);
  });

  it("007_fr31_board_unassigned_has_no_mark", async () => {
    const { container } = await openBoard({}, columns);
    const n = asg(cardEl(container, TC)!);
    expect(n.textContent).toBe(ru["tasks.assignee_none"]);
    expect(marks(n)).toHaveLength(0);
  });

  it("007_fr31_board_filter_options_unchanged_plain_login_without_mark", async () => {
    const { container } = await openBoard({}, columns);
    await waitFor(() => expect(cardEl(container, TA)).toBeTruthy());
    const sel = filterSelect();
    const opts = Array.from(sel.options).map((o) => [o.value, o.textContent]);
    expect(opts).toEqual([
      ["", ru["boards.filter_all"]],
      ["none", ru["boards.filter_none"]],
      [R_ME.id, "admin"],
      [BOT.id, "bot-agent"],
      [HUMAN.id, "kuznetsov"],
    ]);
    expect(marks(sel)).toHaveLength(0);
  });
});

describe("R7-T20 список задач проекта", () => {
  const items = [
    taskItem(TID1, "Задача агента", { assignee: BOT }),
    taskItem(TID2, "Задача человека", { assignee: HUMAN }),
    taskItem(TID3, "Без исполнителя", { assignee: null }),
  ];

  async function open() {
    installFetch(taskRoutes("business_admin", {}, { items }));
    const view = renderApp(`/projects/${PID}`);
    await screen.findByRole("heading", { level: 1, name: "Альфа" });
    await openTasksTab();
    await waitFor(() => expect(taskRow(view.container, TID1)).toBeTruthy());
    return view;
  }
  const cellOf = (c: ParentNode, id: string) => taskRow(c, id)!.querySelector<HTMLElement>('td[data-field="assignee"]')!;

  it("007_fr31_task_list_mark_only_for_agent_assignee", async () => {
    const { container } = await open();
    const a = cellOf(container, TID1);
    expect(marks(a)).toHaveLength(1);
    expect(marks(a)[0]!.textContent).toBe("ИИ");
    expect(marks(a)[0]!.getAttribute("title")).toBe("ИИ-агент");
    expect(a.textContent!.replace("ИИ", "").trim()).toBe("bot-agent");
    const h = cellOf(container, TID2);
    expect(h.textContent).toBe("kuznetsov");
    expect(marks(h)).toHaveLength(0);
  });

  it("007_fr31_task_list_unassigned_has_no_mark", async () => {
    const { container } = await open();
    const n = cellOf(container, TID3);
    expect(n.textContent).toBe(ru["tasks.assignee_none"]);
    expect(marks(n)).toHaveLength(0);
  });
});
