// «@» suggestions in the comment field (012/FR-2): project members by login prefix, up to 10.
// Members are requested only when the user types «@» (no request on mount).
import { useQuery } from "@tanstack/react-query";

import { t } from "../../shared/i18n";
import { listAllMembers } from "../projects/api";

const TOKEN = /(?:^|[^\w.@])@([A-Za-z0-9][A-Za-z0-9_.-]*|)$/;

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

export function MentionSuggest(props: {
  projectId: string | null;
  partial: string | null;
  onPick: (login: string) => void;
}) {
  const { projectId, partial, onPick } = props;
  const members = useQuery({
    queryKey: ["projects", projectId, "members", "all"],
    queryFn: () => listAllMembers(projectId ?? ""),
    enabled: projectId !== null && partial !== null,
    staleTime: 60_000,
  });
  if (partial === null || members.data === undefined) return null;
  const prefix = partial.toLowerCase();
  const logins = members.data
    .filter((m) => !m.is_blocked && m.role !== null)
    .map((m) => m.user.login)
    .filter((login) => login.toLowerCase().startsWith(prefix))
    .slice(0, 10);
  if (logins.length === 0) return null;
  return (
    <ul className="ui-suggest" aria-label={t("comments.mention_suggest")}>
      {logins.map((login) => (
        <li key={login}>
          <button type="button" data-mention={login} onMouseDown={(e) => e.preventDefault()} onClick={() => onPick(login)}>
            @{login}
          </button>
        </li>
      ))}
    </ul>
  );
}
