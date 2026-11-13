import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
         type TextareaHTMLAttributes } from "react";

function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** Plain controls with the dashboard's look. Free text uses dir="auto", so
 *  Hebrew content orients itself whatever the dashboard's language is. */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { small?: boolean; inline?: boolean; mono?: boolean }>(
  function Input({ className, small, inline, mono, dir = "auto", ...rest }, ref) {
    return <input ref={ref} dir={dir} className={cx("vc-input", small && "vc-input--sm", inline && "vc-input--inline", mono && "vc-mono", className)} {...rest} />;
  });

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & { small?: boolean; inline?: boolean }>(
  function Select({ className, small, inline, ...rest }, ref) {
    return <select ref={ref} className={cx("vc-select", small && "vc-select--sm", inline && "vc-select--inline", className)} {...rest} />;
  });

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }>(
  function Textarea({ className, mono, dir = "auto", ...rest }, ref) {
    return <textarea ref={ref} dir={dir} className={cx("vc-textarea", mono && "vc-mono", className)} {...rest} />;
  });

/** A label, a control, and what goes under it (a hint, or the error instead). */
export function FormField({ label, hint, error, required, children, className }: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** The control. Wrapped in the <label>, so clicking the label focuses it. */
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cx("vc-field", className)}>
      <span className="vc-label">
        {label}
        {required && <span className="vc-label__req" aria-hidden="true">*</span>}
      </span>
      {children}
      {error ? <span className="vc-error" role="alert">{error}</span> : hint ? <span className="vc-hint">{hint}</span> : null}
    </label>
  );
}

/** A labelled text input or textarea in one line of code. */
export function Field({
  label, value, onChange, textarea, monospace, placeholder, minHeight, hint, error, required, type, autoFocus, disabled,
  autoComplete,
}: {
  label: ReactNode;
  value: string;
  onChange: (v: string) => void;
  textarea?: boolean;
  monospace?: boolean;
  placeholder?: string;
  minHeight?: number;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  type?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  autoComplete?: string;
}) {
  const id = useId();
  const invalid = error ? true : undefined;
  return (
    <FormField label={label} hint={hint} error={error} required={required}>
      {textarea ? (
        <Textarea id={id} value={value} mono={monospace} placeholder={placeholder} disabled={disabled}
                  aria-invalid={invalid} style={minHeight ? { minHeight } : undefined}
                  onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input id={id} value={value} mono={monospace} placeholder={placeholder} type={type} autoFocus={autoFocus}
               disabled={disabled} autoComplete={autoComplete} aria-invalid={invalid}
               dir={type === "password" ? "ltr" : "auto"} onChange={(e) => onChange(e.target.value)} />
      )}
    </FormField>
  );
}

/** A checkbox with its text. */
export function Check({ checked, onChange, children, disabled, className }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label className={cx("vc-check", className)}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  );
}

/** An on/off switch. `label` is read by screen readers when no text is shown. */
export function Switch({ checked, onChange, children, disabled, label }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children?: ReactNode;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <label className="vc-switch">
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} aria-label={label}
             onChange={(e) => onChange(e.target.checked)} />
      <span className="vc-switch__track" aria-hidden="true" />
      {children != null && <span>{children}</span>}
    </label>
  );
}

// The old inline styles, for screens not yet moved to the classes above.
export const labelStyle: React.CSSProperties = {
  display: "block", fontSize: 13, fontWeight: 600, color: "var(--c-text-2)", marginBottom: 5,
};
export const controlStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", border: "1px solid var(--c-border-strong)", borderRadius: 8,
  fontSize: 14, fontFamily: "inherit", boxSizing: "border-box", background: "var(--c-surface)",
};
