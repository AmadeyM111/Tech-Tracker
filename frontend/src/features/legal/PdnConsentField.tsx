// Spec 021 FR: the required checkbox with the two links. Used on /register, /login and the confirm screen.
import { useId } from "react";

import { t } from "../../shared/i18n";
import "./legal.css";

export interface PdnConsentFieldProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Text under the box when the user tried to go on without it. */
  error?: string | null;
  disabled?: boolean;
}

export function PdnConsentField({ checked, onChange, error = null, disabled = false }: PdnConsentFieldProps) {
  const errorId = useId();
  return (
    <div className="pdn-consent">
      <label className="pdn-consent-row">
        <input
          type="checkbox"
          name="pdn_consent"
          checked={checked}
          disabled={disabled}
          aria-invalid={error !== null}
          aria-describedby={error !== null ? errorId : undefined}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>
          {t("legal.consent_prefix")}
          <a href="/consent" target="_blank" rel="noopener noreferrer">
            {t("legal.consent_link")}
          </a>
          {t("legal.consent_middle")}
          <a href="/privacy" target="_blank" rel="noopener noreferrer">
            {t("legal.privacy_link")}
          </a>
        </span>
      </label>
      {error !== null ? (
        <p id={errorId} className="pdn-consent-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
