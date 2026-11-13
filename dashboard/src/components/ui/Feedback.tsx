import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check, CheckCircle2, Copy, Info, XCircle } from "lucide-react";
import { Button, type ButtonProps } from "./Button";
import { useLang } from "../../i18n";

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const ICON: Record<Tone, ReactNode> = {
  neutral: <Info />, info: <Info />, success: <CheckCircle2 />, warning: <AlertTriangle />, danger: <XCircle />,
};

/** A message inside the page: what happened, or what to know before acting. */
export function Notice({ tone = "neutral", title, children, action, className }: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  /** A button at the end of the message. */
  action?: ReactNode;
  className?: string;
}) {
  const cls = ["vc-notice", tone !== "neutral" ? `vc-notice--${tone}` : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <div className={cls} role={tone === "danger" ? "alert" : "status"}>
      {ICON[tone]}
      <div className="vc-notice__body">
        {title && <div className="vc-notice__title">{title}</div>}
        {children}
      </div>
      {action}
    </div>
  );
}

/** What a list shows when it has nothing: what belongs here and how to add it. */
export function EmptyState({ icon, title, children, actions }: {
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="vc-empty">
      {icon && <div className="vc-empty__icon">{icon}</div>}
      <div className="vc-empty__title">{title}</div>
      {children && <div className="vc-empty__text">{children}</div>}
      {actions && <div className="vc-empty__actions">{actions}</div>}
    </div>
  );
}

export function Spinner({ large }: { large?: boolean }) {
  return <span className={large ? "vc-spinner vc-spinner--lg" : "vc-spinner"} role="status" aria-label="…" />;
}

export function Loading({ children }: { children?: ReactNode }) {
  const { t } = useLang();
  return <div className="vc-loading"><Spinner /> {children ?? t("loading")}</div>;
}

/** Copies `text` and says so for two seconds. */
export function CopyButton({ text, children, ...rest }: { text: string } & Omit<ButtonProps, "onClick">) {
  const { t } = useLang();
  const [done, setDone] = useState(false);
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // No clipboard permission (an http page on another computer): the old way.
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      try { document.execCommand("copy"); } catch { /* nothing more to try */ }
      el.remove();
    }
    setDone(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDone(false), 2000);
  };
  return (
    <Button icon={done ? <Check /> : <Copy />} onClick={copy} {...rest}>
      {done ? t("copied") : (children ?? t("copy"))}
    </Button>
  );
}
