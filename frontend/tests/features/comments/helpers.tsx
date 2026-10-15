// T85: помощники тестов комментариев в карточке задачи.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (строки - только из src/shared/i18n/ru.ts; перечисленные ключи
// добавляются в словарь, тесты падают при их отсутствии).
//
// src/features/comments/api.ts (поверх getAppClient(); не-2xx и сеть -> ApiError)
//   listComments(taskId, { page, pageSize?, headers?, signal? }) GET   /api/v1/tasks/{id}/comments?page=&page_size=
//   createComment(taskId, body)                                  POST  /api/v1/tasks/{id}/comments {body}
//   updateComment(id, body)                                      PATCH /api/v1/comments/{id}       {body}
//   deleteComment(id)                                            DELETE /api/v1/comments/{id}
//   Список - usePolledQuery (FR-29): тик опроса несёт X-GT-Background: 1, первая загрузка и
//   перечитывание после мутации - нет.
//
// src/features/comments/Comments.tsx: компонент подключён в TaskPage внутри [data-slot="comments"]
//   (slot остаётся контейнером; внутри него section[data-section="comments"]).
//   h2 = ru["comments.title"].
//   Список: элемент на комментарий с [data-comment-id="<uuid>"]:
//     [data-field="author"]     текст = login автора
//     [data-field="created_at"] текст "DD.MM.YYYY, HH:MM" в Europe/Moscow (как AuditPage; Intl ru-RU),
//                               внутри time[datetime="<created_at как пришло>"]
//     [data-field="edited"]     есть ТОЛЬКО при edited_at != null; текст = ru["comments.edited"]
//     [data-field="body"]       обычный текстовый узел, style.whiteSpace === "pre-wrap";
//                               HTML не интерпретируется, дочерних элементов нет
//     удалённый (is_deleted): атрибут data-deleted="true", [data-field="deleted"] с текстом
//       ru["comments.deleted"], автор и время остаются, [data-field="body"] и кнопки отсутствуют.
//     button[data-action="edit-comment"]   - только при permissions.edit (иначе нет в DOM)
//     button[data-action="delete-comment"] - только при permissions.delete (иначе нет в DOM)
//   Пусто: [data-role="empty"] с ru["comments.empty"].
//   Пагинация: shared Pagination (button[data-action="next-page"|"prev-page"]) внутри секции,
//     запрос с ?page=N; смена страницы показывает комментарии новой страницы.
//   Форма добавления: form[data-form="create-comment"]: textarea[name="body"] (label
//     ru["comments.body_label"]), button[type="submit"]. Тело POST: {body} с обрезанными по краям
//     пробелами (внутренние переводы строк сохраняются). Пустой/пробельный ввод -> запроса нет,
//     role="alert" errorMessage("validation_error"). Повторная отправка при pending игнорируется
//     (ровно один POST). Успех -> textarea очищена и в фокусе, список перечитан.
//     Ошибка -> ровно один role="alert" на странице с errorMessage(code), ввод сохранён.
//   Правка: click edit-comment -> в этом элементе form[data-form="edit-comment"]: textarea[name="body"]
//     (label ru["comments.edit_label"], предзаполнена текущим текстом, в фокусе), submit,
//     button[data-action="cancel-edit"]. Submit -> PATCH {body} (trim), форма закрыта, список
//     перечитан. Escape в textarea или cancel-edit -> форма закрыта без запроса, фокус на
//     button[data-action="edit-comment"] этого комментария. Ошибка -> один alert, форма открыта, ввод сохранён.
//   Удаление: click delete-comment -> shared ConfirmDialog (alertdialog) с message
//     ru["comments.delete_confirm_message"]; confirm -> DELETE, список перечитан; cancel -> запроса нет.
//     Ошибка DELETE -> один alert errorMessage(code).
//   Ключи словаря: comments.title, comments.empty, comments.body_label, comments.edit_label,
//     comments.edited, comments.deleted, comments.delete_confirm_message (+ любые другие кнопки).
import { fireEvent, screen } from "@testing-library/react";

import {
  ADMIN_ID,
  TID1,
  ALL_PERMS,
  card,
  d,
  err,
  deferred,
  j,
  openCard,
  page,
  R_KUZNETSOV,
  R_ME,
  setValue,
  waitCount,
  type Handler,
} from "../tasks/taskpage-helpers";

export { ADMIN_ID, ALL_PERMS, card, d, deferred, err, j, openCard, page, R_KUZNETSOV, R_ME, setValue, waitCount, fireEvent, screen, TID1 };

export const COMMENTS_GET = `GET /api/v1/tasks/${TID1}/comments`;
export const COMMENT_POST = `POST /api/v1/tasks/${TID1}/comments`;
export const C_PATCH = (id: string) => `PATCH /api/v1/comments/${id}`;
export const C_DELETE = (id: string) => `DELETE /api/v1/comments/${id}`;

export const CID1 = "d1d1d1d1-0000-4000-8000-000000000001";
export const CID2 = "d2d2d2d2-0000-4000-8000-000000000002";
export const CID3 = "d3d3d3d3-0000-4000-8000-000000000003";

export const CP_NONE = { edit: false, delete: false };
export const CP_ALL = { edit: true, delete: true };

export function comment(id: string, body: string | null, over: Record<string, unknown> = {}) {
  return {
    id,
    task_id: TID1,
    author: R_KUZNETSOV,
    body,
    created_at: "2026-10-12T21:30:00Z",
    edited_at: null,
    is_deleted: false,
    permissions: CP_NONE,
    ...over,
  };
}

export const slot = (c: ParentNode) => c.querySelector<HTMLElement>('[data-slot="comments"]')!;
export const item = (c: ParentNode, id: string) => c.querySelector<HTMLElement>(`[data-comment-id="${id}"]`);
export const field = (el: ParentNode, name: string) => el.querySelector<HTMLElement>(`[data-field="${name}"]`);
export const createForm = (c: ParentNode) => c.querySelector<HTMLFormElement>('form[data-form="create-comment"]');
export const createArea = (c: ParentNode) => createForm(c)!.querySelector<HTMLTextAreaElement>('textarea[name="body"]')!;
export const editForm = (el: ParentNode) => el.querySelector<HTMLFormElement>('form[data-form="edit-comment"]');
export const editArea = (el: ParentNode) => editForm(el)!.querySelector<HTMLTextAreaElement>('textarea[name="body"]')!;
export const act = (el: ParentNode, name: string) => el.querySelector<HTMLButtonElement>(`button[data-action="${name}"]`);

/** Открывает карточку с комментариями; list - изменяемый массив, GET отдаёт его текущее состояние. */
export async function openWithComments(
  list: Record<string, unknown>[],
  over: Record<string, Handler> = {},
  opts: { hasNext?: boolean } = {},
) {
  const state = { items: list };
  const view = await openCard(() => card(), {
    [COMMENTS_GET]: () => j(200, page(state.items, 1, opts.hasNext ?? false)),
    ...over,
  });
  await screen.findByRole("heading", { level: 2, name: d("comments.title") });
  return { ...view, state };
}
