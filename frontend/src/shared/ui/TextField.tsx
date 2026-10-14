import { useId, type Ref } from "react";

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
}

export function TextField(props: TextFieldProps) {
  const { label, value, onChange, type = "text", autoComplete, inputRef, invalid, disabled, hint } = props;
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        ref={inputRef}
        type={type}
        value={value}
        autoComplete={autoComplete}
        autoCapitalize="off"
        spellCheck={false}
        aria-invalid={invalid === true ? "true" : undefined}
        aria-describedby={hint === undefined ? undefined : hintId}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint === undefined ? null : (
        <span id={hintId} className="ui-hint">
          {hint}
        </span>
      )}
    </div>
  );
}
