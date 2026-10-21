import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

import { listDirectory, type DirectoryUser } from "../../features/users/api";
import { ApiError } from "../api/client";
import { errorMessage, t } from "../i18n";

export interface UserPickerProps {
  label: string;
  onSelect: (user: DirectoryUser) => void;
  /** When set, only these ids may be chosen (e.g. project members); `[]` allows nobody. */
  allowedIds?: readonly string[];
  disabled?: boolean;
  /** An action on the chosen user is in flight: the field stays enabled (focus), marked aria-busy. */
  busy?: boolean;
  /** The search error is a status line, not a second alert (the page has its own alert). */
  quietError?: boolean;
  /** Id of an element that already shows the caption (e.g. a <dt>): no own <label>, the input points to it. */
  labelledBy?: string;
  /** aria-required у combobox (006/FR-19). */
  required?: boolean;
  /** aria-invalid у combobox. */
  invalid?: boolean;
  /** aria-describedby у combobox (сообщение об ошибке поля). */
  describedBy?: string;
  /** Признак обязательности внутри собственной подписи (006/PD-12), напр. `<span class="ui-required">`. */
  labelMark?: ReactNode;
}

const DEBOUNCE_MS = 300;
// A fast answer is not announced as "loading": the status would only flicker.
const LOADING_DELAY_MS = 200;
// Look of the listbox is in ui.css ([role="listbox"]). The active option keeps an inline outline:
// it stays visible when forced colors drop the background (NFR-7).
const ACTIVE_STYLE: CSSProperties = {
  outline: "2px solid var(--focus)",
  outlineOffset: "-4px",
};
// Mirrors the backend login length limit; the server stays authoritative.
const MAX_QUERY_LENGTH = 64;

/** Combobox over the users directory: search by login, keyboard and click selection. */
export function UserPicker({ label, onSelect, allowedIds, disabled, busy, quietError, labelledBy, required, invalid, describedBy, labelMark }: UserPickerProps) {
  const baseId = useId();
  const inputId = `${baseId}-input`;
  const listId = `${baseId}-list`;
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // `typed` is what the field shows; `query` is the debounced value being searched.
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  const wanted = typed.trim();
  const search = useQuery({
    queryKey: ["users", "directory", query],
    queryFn: () => listDirectory({ q: query ?? undefined }),
    enabled: query !== null,
    retry: false,
  });

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const cancelTimer = () => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  };

  // The answer is shown only when it belongs to the text currently in the field.
  const current = open && query === wanted;
  const options =
    current && search.data !== undefined
      ? search.data.items.filter((u) => allowedIds === undefined || allowedIds.includes(u.id))
      : [];
  const activeIndex = active < options.length ? active : -1;
  const expanded = options.length > 0;
  const hasMore = search.data?.has_next === true;
  const showError = current && search.isError;
  const optionId = (i: number) => `${listId}-${i}`;

  // One permanent live region: loading, number of results, nothing found (NFR-7).
  const fetching = current && search.isFetching;
  // Query for which the answer is already late (set only by the timer).
  const [lateFor, setLateFor] = useState<string | null>(null);
  useEffect(() => {
    if (!fetching) return undefined;
    const id = setTimeout(() => setLateFor(query), LOADING_DELAY_MS);
    return () => clearTimeout(id);
  }, [fetching, query]);
  let statusText = "";
  if (fetching) {
    statusText = lateFor === query ? t("user_picker.loading") : "";
  } else if (current && search.isSuccess) {
    if (options.length > 0) statusText = t("user_picker.count", { count: options.length });
    else statusText = t(hasMore ? "user_picker.refine" : "user_picker.empty");
  }

  const choose = (user: DirectoryUser) => {
    cancelTimer();
    setTyped(user.login);
    setOpen(false);
    setActive(-1);
    onSelect(user);
    inputRef.current?.focus();
  };

  const onChange = (value: string) => {
    setTyped(value);
    setOpen(true);
    setActive(-1);
    cancelTimer();
    const next = value.trim();
    timer.current = setTimeout(() => setQuery(next), DEBOUNCE_MS);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open || query !== wanted) {
        cancelTimer();
        setQuery(wanted);
        setOpen(true);
        setActive(0);
      } else if (options.length > 0) {
        setActive(Math.min(activeIndex + 1, options.length - 1));
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (options.length > 0) setActive(Math.max(activeIndex - 1, 0));
    } else if (e.key === "Enter") {
      const user = options[activeIndex];
      if (user !== undefined) {
        e.preventDefault();
        choose(user);
      }
    } else if (e.key === "Escape") {
      // An open list takes the key; a closed one lets it reach the owner window.
      if (open) e.stopPropagation();
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="ui-field">
      {labelledBy === undefined ? (
        <label htmlFor={inputId}>
          {label}
          {labelMark}
        </label>
      ) : null}
      <input
        id={inputId}
        ref={inputRef}
        type="text"
        role="combobox"
        aria-labelledby={labelledBy}
        aria-required={required === true ? true : undefined}
        aria-invalid={invalid === true ? "true" : undefined}
        aria-describedby={describedBy}
        maxLength={MAX_QUERY_LENGTH}
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        aria-autocomplete="list"
        aria-expanded={expanded ? "true" : "false"}
        aria-controls={listId}
        aria-activedescendant={expanded && activeIndex >= 0 ? optionId(activeIndex) : undefined}
        disabled={disabled}
        aria-busy={busy === true ? "true" : undefined}
        value={typed}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
      />
      {expanded ? (
        <ul id={listId} role="listbox" aria-label={label}>
          {options.map((user, i) => (
            <li
              key={user.id}
              id={optionId(i)}
              role="option"
              aria-selected={i === activeIndex ? "true" : "false"}
              style={i === activeIndex ? ACTIVE_STYLE : undefined}
              // Keeps the focus in the input, so the click is not lost to blur.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(user)}
            >
              {user.login}
            </li>
          ))}
        </ul>
      ) : null}
      <div role="status" className="ui-hint">
        {statusText}
      </div>
      {showError ? (
        <p role={quietError === true ? "status" : "alert"} className="ui-error">
          {errorMessage(search.error instanceof ApiError ? search.error.code : "unknown")}
        </p>
      ) : null}
    </div>
  );
}
