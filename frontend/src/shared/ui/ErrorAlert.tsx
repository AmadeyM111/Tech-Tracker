import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";

export interface AlertState {
  message: string | null;
  /** Changes on every show(): the same message again still takes focus. */
  seq: number;
  show: (message: string) => void;
  clear: () => void;
}

export function useAlertState(): AlertState {
  const [state, setState] = useState<{ message: string; seq: number } | null>(null);
  const counter = useRef(0);
  const show = useCallback((message: string) => {
    counter.current += 1;
    setState({ message, seq: counter.current });
  }, []);
  const clear = useCallback(() => setState(null), []);
  return { message: state?.message ?? null, seq: state?.seq ?? 0, show, clear };
}

/**
 * Error message announced to assistants; takes focus when it appears (NFR-7).
 * `focus={false}`: the caller moves focus itself (e.g. to the first empty field).
 */
export function ErrorAlert({ message, seq = 0, focus = true }: { message: string | null; seq?: number; focus?: boolean }) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (focus && message !== null) ref.current?.focus();
  }, [message, seq, focus]);
  if (message === null) return null;
  return (
    <p ref={ref} role="alert" tabIndex={-1} className="ui-error-alert">
      <Icon name="alert" />
      {message}
    </p>
  );
}

/** Message under a field: role="alert", never takes focus (006/FR-19, FR-28). Icon and text as in the field-error mockup. */
export function FieldError({ id, message }: { id: string; message: string | null }) {
  if (message === null) return null;
  return (
    <p id={id} role="alert" className="ui-error ui-field-error">
      <Icon name="alert" />
      <span>{message}</span>
    </p>
  );
}
