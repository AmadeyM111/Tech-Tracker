import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";

import { listDirectory, type DirectoryUser } from "../../features/users/api";
import { ApiError } from "../api/client";
import { errorMessage, t } from "../i18n";

export interface UserPickerProps {
  label: string;
  onSelect: (user: DirectoryUser) => void;
  /** When set, only these ids may be chosen (e.g. project members); `[]` allows nobody. */
  allowedIds?: readonly string[];
  disabled?: boolean;
}

const DEBOUNCE_MS = 300;
// Inline: ui.css is outside the T81 file list. The active option is visibly marked (NFR-7).
const LIST_STYLE: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  border: "1px solid #c4c4c4",
  maxHeight: "16rem",
  overflowY: "auto",
};
const OPTION_STYLE: CSSProperties = { padding: "6px 8px", cursor: "pointer" };
const ACTIVE_STYLE: CSSProperties = { ...OPTION_STYLE, background: "#0b3d91", color: "#ffffff" };

/** Combobox over the users directory: search by login, keyboard and click selection. */
export function UserPicker({ label, onSelect, allowedIds, disabled }: UserPickerProps) {
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
  const showEmpty = current && search.isSuccess && options.length === 0;
  const showError = current && search.isError;
  const optionId = (i: number) => `${listId}-${i}`;

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
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="ui-field">
      <label htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        ref={inputRef}
        type="text"
        role="combobox"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        aria-autocomplete="list"
        aria-expanded={expanded ? "true" : "false"}
        aria-controls={listId}
        aria-activedescendant={expanded && activeIndex >= 0 ? optionId(activeIndex) : undefined}
        disabled={disabled}
        value={typed}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
      />
      {expanded ? (
        <ul id={listId} role="listbox" aria-label={label} style={LIST_STYLE}>
          {options.map((user, i) => (
            <li
              key={user.id}
              id={optionId(i)}
              role="option"
              aria-selected={i === activeIndex ? "true" : "false"}
              style={i === activeIndex ? ACTIVE_STYLE : OPTION_STYLE}
              // Keeps the focus in the input, so the click is not lost to blur.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(user)}
            >
              {user.login}
            </li>
          ))}
        </ul>
      ) : null}
      {showEmpty ? <p role="status">{t("user_picker.empty")}</p> : null}
      {showError ? (
        <p role="alert" className="ui-error">
          {errorMessage(search.error instanceof ApiError ? search.error.code : "unknown")}
        </p>
      ) : null}
    </div>
  );
}
