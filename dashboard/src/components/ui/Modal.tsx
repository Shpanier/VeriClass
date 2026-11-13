import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./Button";
import { useLang } from "../../i18n";

// Open dialogs, oldest first: Escape and the focus trap belong to the last one.
const stack: symbol[] = [];

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Every dialog of the dashboard.
 *
 *  It closes with the X, Escape, or a click on the dimmed background (a click
 *  that both starts and ends there: selecting text and letting go outside the
 *  dialog doesn't close it). With `dirty`, closing first asks whether to
 *  discard the changes. Keyboard focus stays inside while it is open and goes
 *  back to where it was afterwards. */
export function Modal({
  onClose, title, subtitle, footer, size, width, dirty, flush, children,
}: {
  onClose: () => void;
  /** Shown in the header and read as the dialog's name. Without it the content brings its own heading. */
  title?: ReactNode;
  subtitle?: ReactNode;
  /** Buttons at the bottom; they stay visible while the content scrolls. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** A width in pixels, when none of the sizes fits. */
  width?: number;
  /** There are unsaved changes: ask before closing. */
  dirty?: boolean;
  /** No padding around the content. */
  flush?: boolean;
  children: ReactNode;
}) {
  const { t } = useLang();
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const downOnBackdrop = useRef(false);
  const [asking, setAsking] = useState(false);
  const me = useRef(Symbol("modal"));
  const latest = useRef({ dirty, onClose });
  latest.current = { dirty, onClose };

  const requestClose = () => {
    if (latest.current.dirty) setAsking(true);
    else latest.current.onClose();
  };

  useEffect(() => {
    const id = me.current;
    stack.push(id);
    const before = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Focus the first text field of the content (not a tick box, not the
    // footer's controls), else the dialog itself.
    const body = panel.current?.querySelector<HTMLElement>(".vc-modal__body") ?? panel.current;
    const first = panel.current?.querySelector<HTMLElement>("[autofocus]")
      ?? body?.querySelector<HTMLElement>(
        'input:not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="hidden"]), textarea, select');
    (first ?? panel.current)?.focus({ preventScroll: true });

    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        requestClose();
      } else if (e.key === "Tab" && panel.current) {
        const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
        if (items.length === 0) { e.preventDefault(); return; }
        const firstEl = items[0], lastEl = items[items.length - 1];
        const active = document.activeElement;
        if (!panel.current.contains(active)) { e.preventDefault(); firstEl.focus(); }
        else if (e.shiftKey && active === firstEl) { e.preventDefault(); lastEl.focus(); }
        else if (!e.shiftKey && active === lastEl) { e.preventDefault(); firstEl.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      stack.splice(stack.indexOf(id), 1);
      if (stack.length === 0) document.body.style.overflow = prevOverflow;
      before?.focus?.({ preventScroll: true });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cls = ["vc-modal", size ? `vc-modal--${size}` : ""].filter(Boolean).join(" ");
  return (
    <div
      className="vc-modal-backdrop"
      onMouseDown={(e) => { downOnBackdrop.current = e.target === e.currentTarget; }}
      onMouseUp={(e) => {
        if (downOnBackdrop.current && e.target === e.currentTarget) requestClose();
        downOnBackdrop.current = false;
      }}
    >
      <div
        ref={panel} className={cls} role="dialog" aria-modal="true" tabIndex={-1}
        aria-labelledby={title ? titleId : undefined}
        style={width ? { maxWidth: width } : undefined}
      >
        {title && (
          <div className="vc-modal__header">
            <div className="vc-modal__titles">
              <h2 className="vc-modal__title" id={titleId}>{title}</h2>
              {subtitle && <div className="vc-modal__subtitle">{subtitle}</div>}
            </div>
            <Button variant="quiet" size="sm" iconOnly aria-label={t("close")} onClick={requestClose} icon={<X />} />
          </div>
        )}
        {asking && (
          <div className="vc-notice vc-notice--warning" style={{ borderRadius: 0, borderInline: 0 }} role="alertdialog">
            <div className="vc-notice__body u-row u-wrap u-between">
              <span>{t("discardAsk")}</span>
              <span className="u-row">
                <Button size="sm" onClick={() => setAsking(false)} autoFocus>{t("keepEditing")}</Button>
                <Button size="sm" variant="danger" onClick={() => latest.current.onClose()}>{t("discard")}</Button>
              </span>
            </div>
          </div>
        )}
        <div className={flush ? "vc-modal__body vc-modal__body--flush" : "vc-modal__body"}>{children}</div>
        {footer && <div className="vc-modal__footer">{footer}</div>}
      </div>
    </div>
  );
}
