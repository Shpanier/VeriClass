import type { ButtonHTMLAttributes } from "react";

// The recurring button palette used across the dashboard, collected in one place.
type Variant = "primary" | "neutral" | "danger" | "ghost";

const PALETTE: Record<Variant, { bg: string; fg: string; border: string }> = {
  primary: { bg: "#111827", fg: "white", border: "#111827" },
  neutral: { bg: "#3b82f6", fg: "white", border: "#3b82f6" },
  danger: { bg: "#b91c1c", fg: "white", border: "#b91c1c" },
  ghost: { bg: "white", fg: "#374151", border: "#d1d5db" },
};

export function Button({
  variant = "ghost",
  style,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const c = PALETTE[variant];
  return (
    <button
      disabled={disabled}
      style={{
        padding: "8px 16px",
        borderRadius: 6,
        border: `1px solid ${c.border}`,
        background: c.bg,
        color: c.fg,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
        fontSize: 13,
        fontWeight: 600,
        ...style,
      }}
      {...rest}
    />
  );
}
