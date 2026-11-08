// «@» suggestions in the comment field (012/FR-2; mockups mention-suggest / mention-no-match):
// project members by login prefix, up to 10; arrows move, Enter inserts. Members are requested only
// when the user types «@» (no request on mount).
import { useQuery } from "@tanstack/react-query";
import { useId } from "react";

import { t } from "../../shared/i18n";
import { listAllMembers } from "../projects/api";

// Перед «@» не буква (включая кириллицу), не цифра, не «_.@» — как на сервере (ревью 012, п. 5).
const TOKEN = /(?:^|[^\p{L}\p{N}_.@])@([A-Za-z0-9][A-Za-z0-9_.-]*|)$/u;
const MENTION = /(?<![\p{L}\p{N}_.@])@[A-Za-z0-9][A-Za-z0-9_.-]{2,63}/gu;
const MAX = 10;

/** The partial login right before the caret, or null when the caret is not in an «@» token. */
export function mentionAt(text: string, caret: number): string | null {
  const match = TOKEN.exec(text.slice(0, caret));
  return match === null ? null : (match[1] ?? "");
}

/** Text with the partial token replaced by the full login and a trailing space. */
export function insertMention(text: string, caret: number, login: string): { text: string; caret: number } {
  const partial = mentionAt(text, caret) ?? "";
  const start = caret - partial.length;
  const next = `${text.slice(0, start)}${login} ${text.slice(caret)}`;
  return { text: next, caret: start + login.length + 1 };
}

/** Members' logins for the prefix (active, with a role), up to 10; undefined while loading. */
export function useMentionOptions(projectId: string | null, partial: string | null): string[] | undefined {
  const members = useQuery({
    queryKey: ["projects", projectId, "members", "all"],
    queryFn: () => listAllMembers(projectId ?? ""),
    enabled: projectId !== null && partial !== null,
    staleTime: 60_000,
  });
  if (partial === null || members.data === undefined) return undefined;
  const prefix = partial.toLowerCase();
  return members.data
    .filter((m) => !m.is_blocked && m.role !== null)
    .map((m) => m.user.login)
    .filter((login) => login.toLowerCase().startsWith(prefix))
    .slice(0, MAX);
}

export function MentionSuggest(props: {
  partial: string | null;
  options: string[] | undefined;
  active: number;
  onPick: (login: string) => void;
}) {
  const { partial, options, active, onPick } = props;
  const id = useId();
  if (partial === null || options === undefined) return null;
  if (options.length === 0) {
    return (
      <p className="mention-hint" role="status">
        {t("comments.mention_none", { prefix: partial })}
      </p>
    );
  }
  return (
    <>
      <p className="mention-hint" id={`${id}-hint`}>
        {t("comments.mention_hint")}
      </p>
      <ul role="listbox" aria-label={t("comments.mention_suggest")} aria-describedby={`${id}-hint`}>
        {options.map((login, i) => (
          <li
            key={login}
            role="option"
            aria-selected={i === active}
            data-mention={login}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onPick(login)}
          >
            @{login}
          </li>
        ))}
      </ul>
    </>
  );
}

/** Comment text with «@логин» highlighted (accent, bold); not a link (owner decision 2026-11-08). */
export function MentionText({ text }: { text: string }) {
  const parts: (string | { mention: string })[] = [];
  let last = 0;
  for (const match of text.matchAll(MENTION)) {
    const at = match.index;
    if (at > last) parts.push(text.slice(last, at));
    parts.push({ mention: match[0] });
    last = at + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return (
    <>
      {parts.map((part, i) =>
        typeof part === "string" ? (
          part
        ) : (
          <span key={i} className="mention">
            {part.mention}
          </span>
        ),
      )}
    </>
  );
}
