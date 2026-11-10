import { useId, type Ref } from "react";
import { FieldError } from "./ErrorAlert";
import { Icon } from "./Icon";

export interface TextFieldReveal {
  /** Постоянное доступное имя из словаря (006/D-6). */
  label: string;
  shown: boolean;
  onToggle: () => void;
}

export interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password";
  autoComplete: string;
  inputRef?: Ref<HTMLInputElement>;
  invalid?: boolean;
  disabled?: boolean;
  hint?: string;
  /** Text under the field (FieldError); a non-null text also marks the field invalid. */
  error?: string | null;
  name?: string;
  reveal?: TextFieldReveal;
}

export function TextField(props: TextFieldProps) {
  const { label, value, onChange, type = "text", autoComplete, inputRef, invalid, disabled, hint, error, name, reveal } = props;
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hasError = error !== undefined && error !== null;
  const describedBy = [hint === undefined ? null : hintId, hasError ? errorId : null].filter(Boolean).join(" ");
  const withReveal = type === "password" && reveal !== undefined;
  const input = (
    <input
      id={id}
      name={name}
      ref={inputRef}
      type={withReveal && reveal.shown ? "text" : type}
      value={value}
      autoComplete={autoComplete}
      autoCapitalize="off"
      spellCheck={false}
      aria-invalid={invalid === true || hasError ? "true" : undefined}
      aria-describedby={describedBy === "" ? undefined : describedBy}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  );
  return (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      {withReveal ? (
        <div className="ui-input-row">
          {input}
          <button
            type="button"
            className="ui-reveal ui-btn-secondary"
            aria-pressed={reveal.shown ? "true" : "false"}
            aria-label={reveal.label}
            disabled={disabled}
            onClick={reveal.onToggle}
          >
            <Icon name={reveal.shown ? "eye-off" : "eye"} />
          </button>
        </div>
      ) : (
        input
      )}
      {hint === undefined ? null : (
        <span id={hintId} className="ui-hint">
          {hint}
        </span>
      )}
      <FieldError id={errorId} message={hasError ? error : null} />
    </div>
  );
}
