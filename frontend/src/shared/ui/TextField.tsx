import { useId, type Ref } from "react";
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
  name?: string;
  reveal?: TextFieldReveal;
}

export function TextField(props: TextFieldProps) {
  const { label, value, onChange, type = "text", autoComplete, inputRef, invalid, disabled, hint, name, reveal } = props;
  const id = useId();
  const hintId = `${id}-hint`;
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
      aria-invalid={invalid === true ? "true" : undefined}
      aria-describedby={hint === undefined ? undefined : hintId}
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
            className="ui-reveal"
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
    </div>
  );
}
