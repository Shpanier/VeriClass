import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { useLang } from "../../i18n";

export interface ConfirmOptions {
  title: ReactNode;
  /** What will happen, in a sentence or two. */
  body?: ReactNode;
  /** The confirming button's text: the action itself ("Delete the meeting"), not "OK". */
  confirmLabel: ReactNode;
  cancelLabel?: ReactNode;
  /** A destructive action: the confirming button is red. */
  danger?: boolean;
}

type Ask = (o: ConfirmOptions) => Promise<boolean>;
const Ctx = createContext<Ask | null>(null);

/** "Are you sure?" for actions that reach the whole class or can't be undone:
 *    const confirm = useConfirm();
 *    if (!(await confirm({ title, body, confirmLabel, danger: true }))) return; */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const { t } = useLang();
  const [open, setOpen] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);

  const ask = useCallback<Ask>((o) => new Promise<boolean>((resolve) => {
    resolver.current?.(false);
    resolver.current = resolve;
    setOpen(o);
  }), []);

  const answer = (v: boolean) => {
    resolver.current?.(v);
    resolver.current = null;
    setOpen(null);
  };

  return (
    <Ctx.Provider value={ask}>
      {children}
      {open && (
        <Modal
          size="sm" title={open.title} onClose={() => answer(false)}
          footer={<>
            <span className="u-push" />
            <Button onClick={() => answer(false)}>{open.cancelLabel ?? t("cancel")}</Button>
            <Button variant={open.danger ? "danger" : "primary"} onClick={() => answer(true)} autoFocus>
              {open.confirmLabel}
            </Button>
          </>}
        >
          {open.body && <div className="u-soft">{open.body}</div>}
        </Modal>
      )}
    </Ctx.Provider>
  );
}

export function useConfirm(): Ask {
  const v = useContext(Ctx);
  if (!v) throw new Error("useConfirm must be used within <ConfirmProvider>");
  return v;
}
