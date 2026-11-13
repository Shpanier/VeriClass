import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useLang } from "../../i18n";
import { describeError } from "../../lib/errors";

type Kind = "success" | "error" | "info";
interface ToastItem { id: number; kind: Kind; text: ReactNode; details?: string }

export interface Toaster {
  success: (text: ReactNode) => void;
  info: (text: ReactNode) => void;
  /** `what` says what was being done ("Couldn't save the course"); the reason
   *  comes from the error. Pass only an error to show its own message. */
  error: (what: ReactNode | unknown, err?: unknown) => void;
}

const Ctx = createContext<Toaster | null>(null);

/** Short messages in the corner: an action worked, or it didn't and why. Every
 *  action a lecturer takes ends in one of these or in a visible change. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useLang();
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((list) => list.filter((i) => i.id !== id));
  }, []);

  const push = useCallback((kind: Kind, text: ReactNode, details?: string) => {
    const id = next.current++;
    setItems((list) => [...list.slice(-3), { id, kind, text, details }]);
    timers.current.set(id, window.setTimeout(() => dismiss(id), kind === "error" ? 9000 : 4000));
  }, [dismiss]);

  useEffect(() => {
    const all = timers.current;
    return () => { all.forEach((tm) => window.clearTimeout(tm)); };
  }, []);

  const tRef = useRef(t);
  tRef.current = t;
  const api = useRef<Toaster>({
    success: (text) => push("success", text),
    info: (text) => push("info", text),
    error: (what, err) => {
      if (err === undefined && (what instanceof Error || typeof what !== "string")) {
        push("error", describeError(what, tRef.current));
      } else {
        push("error", what as ReactNode, err === undefined ? undefined : describeError(err, tRef.current));
      }
    },
  });

  return (
    <Ctx.Provider value={api.current}>
      {children}
      <div className="vc-toasts" aria-live="polite">
        {items.map((i) => (
          <div key={i.id} className={`vc-toast vc-toast--${i.kind}`} role={i.kind === "error" ? "alert" : "status"}>
            {i.kind === "success" ? <CheckCircle2 /> : i.kind === "error" ? <XCircle /> : <Info />}
            <div className="vc-toast__body">
              <div dir="auto">{i.text}</div>
              {i.details && <div className="vc-toast__details" dir="auto">{i.details}</div>}
            </div>
            <button className="vc-toast__close" aria-label={t("close")} onClick={() => dismiss(i.id)}><X size={16} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): Toaster {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast must be used within <ToastProvider>");
  return v;
}
