"use client";
/** Labelled input with inline (field-level) error, wired for screen readers (aria-invalid / describedby). */
import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "onChange"> & {
  label: string;
  error?: string | null;
  hint?: ReactNode;
  testId: string;
  onValue: (v: string) => void;
  /** render a textarea instead */
  multiline?: boolean;
  rows?: number;
};

export function FormField({ label, error, hint, testId, onValue, multiline, rows, type, ...rest }: Props) {
  const id = useId();
  const [show, setShow] = useState(false);
  const isPw = type === "password";
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  const common = {
    id,
    "data-testid": testId,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy,
  } as const;
  return (
    <div className={`form-field${error ? " has-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea
          className="textarea"
          rows={rows}
          {...common}
          {...(rest as InputHTMLAttributes<HTMLTextAreaElement>)}
          onChange={(e) => onValue(e.target.value)}
        />
      ) : (
        <div className="input-wrap">
          <input
            className="input"
            type={isPw && show ? "text" : type}
            {...common}
            {...rest}
            onChange={(e) => onValue(e.target.value)}
          />
          {isPw ? (
            <button
              type="button"
              className="pw-toggle"
              aria-label={show ? "隐藏密码" : "显示密码"}
              data-testid={`${testId}-toggle`}
              onClick={() => setShow((s) => !s)}
            >
              {show ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
            </button>
          ) : null}
        </div>
      )}
      {error ? (
        <p className="field-error" id={`${id}-err`} data-testid={`${testId}-error`} role="alert">
          {error}
        </p>
      ) : hint ? (
        // div, not p: hints may contain block content (the password meter)
        <div className="field-hint" id={`${id}-hint`}>
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export function PasswordMeter({ score }: { score: number }) {
  const labels = ["", "弱", "一般", "较强", "强"];
  return (
    <div className="pw-meter" data-score={score} aria-live="polite" data-testid="password-strength">
      <div className="pw-bars" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <i key={i} className={i <= score ? "on" : undefined} />
        ))}
      </div>
      {score ? <span>密码强度：{labels[score]}</span> : null}
    </div>
  );
}
