import { useCallback, useEffect, useRef, useState } from "react";

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

/** Error message announced to assistants; takes focus when it appears (NFR-7). */
export function ErrorAlert({ message, seq = 0 }: { message: string | null; seq?: number }) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (message !== null) ref.current?.focus();
  }, [message, seq]);
  if (message === null) return null;
  return (
    <p ref={ref} role="alert" tabIndex={-1} className="ui-error">
      {message}
    </p>
  );
}
