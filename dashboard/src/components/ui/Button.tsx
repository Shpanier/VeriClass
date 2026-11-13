import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

/** How a button looks:
 *  primary     the one main action of a screen or dialog (filled, brand colour)
 *  secondary   every other action (white, bordered): the default
 *  quiet       low-key actions inside dense rows (no border until hovered)
 *  link        reads as a link inside a sentence
 *  success / warn / danger   filled: approve, careful, destructive
 *  danger-soft outlined red: destructive but not the main action
 *  brand-soft  tinted brand: a secondary action that should still stand out
 *  neutral, ghost: the old names of primary and secondary. */
export type ButtonVariant =
  | "primary" | "secondary" | "quiet" | "link" | "success" | "warn" | "danger" | "danger-soft" | "brand-soft"
  | "neutral" | "ghost";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "vc-btn--primary",
  secondary: "",
  quiet: "vc-btn--quiet",
  link: "vc-btn--link",
  success: "vc-btn--success",
  warn: "vc-btn--warn",
  danger: "vc-btn--danger",
  "danger-soft": "vc-btn--danger-soft",
  "brand-soft": "vc-btn--brand-soft",
  neutral: "vc-btn--primary",
  ghost: "",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  /** An icon before the text (a lucide-react icon element). */
  icon?: ReactNode;
  /** Shows a spinner and disables the button while an action runs. */
  busy?: boolean;
  /** Full width. */
  block?: boolean;
  /** A square button holding only an icon; give it an aria-label. */
  iconOnly?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, busy, block, iconOnly, className, children, disabled, type = "button", ...rest },
  ref,
) {
  const cls = [
    "vc-btn", VARIANT[variant],
    size === "sm" ? "vc-btn--sm" : size === "lg" ? "vc-btn--lg" : "",
    block ? "vc-btn--block" : "", iconOnly ? "vc-btn--icon" : "", className ?? "",
  ].filter(Boolean).join(" ");
  return (
    <button ref={ref} type={type} className={cls} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy ? <span className="vc-spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  );
});
