import { useEffect, useRef, useState } from "react";
import { ChevronDown, Megaphone } from "lucide-react";
import { api } from "../api";
import type { AnsweredReview } from "../types";
import { useLang } from "../i18n";
import { Button, Textarea, Time, useToast } from "./ui";
import { textDir } from "../lib/textDir";

// Open or closed, remembered in this browser (open at first).
const OPEN_KEY = "vc.answered.open";
// Shown before "Show all".
const FIRST = 5;

function savedOpen(): boolean {
  try { return localStorage.getItem(OPEN_KEY) !== "0"; } catch { return true; }
}

/** Enough rows for the text, up to a limit. */
function rowsFor(text: string): number {
  const lines = text.split("\n").reduce((n, l) => n + 1 + Math.floor(l.length / 140), 0);
  return Math.min(16, Math.max(3, lines + 1));
}

/** The questions answered in the last hours, under the review queue: an answer
 *  already sent to one student can still go to everyone else on the exercise
 *  (edited for the class if needed). Hidden while nothing was answered. */
export function AnsweredRecently({ exerciseId, refresh, plain }: {
  exerciseId: string | null;
  /** Goes up after the queue sends an answer: load the list again now. */
  refresh: number;
  /** Markdown as plain text, for the folded answer. */
  plain: (md: string) => string;
}) {
  const { t } = useLang();
  const toast = useToast();
  const [items, setItems] = useState<AnsweredReview[]>([]);
  const [open, setOpen] = useState(savedOpen);
  const [all, setAll] = useState(false);
  const [unfolded, setUnfolded] = useState<Record<number, boolean>>({});
  // The answer whose "send to the class" box is open, its text, and how many it would reach.
  const [composing, setComposing] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [reach, setReach] = useState<{ count: number; minutes: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const idRef = useRef(exerciseId);
  idRef.current = exerciseId;

  const load = () => {
    if (!exerciseId) return;
    const asked = exerciseId;
    api.answeredReviews(asked)
      .then((list) => { if (idRef.current === asked) setItems(list); })
      .catch(() => { /* a background poll: the page's banner says when the server is unreachable */ });
  };

  useEffect(() => {
    setItems([]);
    setComposing(null);
    if (!exerciseId) return;
    load();
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exerciseId]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (refresh > 0) load(); }, [refresh]);

  if (!exerciseId || items.length === 0) return null;

  const toggle = () => setOpen((was) => {
    try { localStorage.setItem(OPEN_KEY, was ? "0" : "1"); } catch { /* ignore */ }
    return !was;
  });

  const compose = (a: AnsweredReview) => {
    setComposing(a.id);
    setText(a.text);
    setReach(null);
    api.broadcastRecipients(a.exercise_id, a.course_id, a.session_id)
      .then((r) => setReach(r))
      .catch(() => setReach(null)); // the button then says "all students", without a number
  };

  const send = async (a: AnsweredReview) => {
    setBusy(true);
    try {
      const edited = text.trim() !== a.text.trim();
      const r = await api.sendAnsweredToClass(a.id, edited ? text : undefined);
      if (r.sent_to_class > 0) toast.success(t("answeredToast", { n: r.sent_to_class }));
      else toast.info(t("answeredToastNone"));
      setComposing(null);
      load();
    } catch (e) {
      toast.error(t("answeredFailed"), e);
    } finally {
      setBusy(false);
    }
  };

  const shown = all ? items : items.slice(0, FIRST);

  return (
    <section className="vc-answered" data-open={open} aria-labelledby="vc-answered-title">
      <h3 className="vc-answered__title" id="vc-answered-title">
        <button type="button" className="vc-answered__toggle" aria-expanded={open} onClick={toggle}>
          <ChevronDown className="vc-answered__chev" aria-hidden="true" />
          {t("answeredTitle")}
          <span className="vc-badge vc-badge--count">{items.length}</span>
        </button>
      </h3>
      {open && (
        <>
          <p className="vc-answered__hint">{t("answeredHint")}</p>
          <ul className="vc-answered__list">
            {shown.map((a) => {
              const isOpen = !!unfolded[a.id];
              const flat = plain(a.text);
              const editing = composing === a.id;
              const empty = !text.trim();
              return (
                <li key={a.id} className="vc-answered__item" data-editing={editing}>
                  <div className="vc-answered__head">
                    <span className="vc-answered__name" dir={textDir(a.username)}>{a.username}</span>
                    <span className="u-muted u-xs"><Time value={a.answered_at ?? a.created_at} /></span>
                    {a.sent_to_class > 0 && (
                      <span className="vc-badge vc-badge--success">
                        <Megaphone aria-hidden="true" /> {t("answeredSentBadge", { n: a.sent_to_class })}
                      </span>
                    )}
                    {!editing && (
                      <Button size="sm" icon={<Megaphone />} className="u-push" onClick={() => compose(a)}>
                        {t("answeredSendAll")}
                      </Button>
                    )}
                  </div>
                  <div className="vc-answered__question" dir={textDir(a.question)}>{a.question}</div>
                  {editing ? (
                    <div className="vc-answered__compose">
                      <div className="u-soft u-xs" dir={textDir(a.username)}>{t("answeredEditHint", { name: a.username })}</div>
                      <Textarea value={text} rows={rowsFor(text)} spellCheck={false} disabled={busy}
                                aria-label={t("answeredTextAria")} onChange={(e) => setText(e.target.value)} />
                      <div className="vc-answered__actions">
                        <Button size="sm" variant="primary" icon={<Megaphone />} busy={busy}
                                disabled={empty || reach?.count === 0} onClick={() => send(a)}>
                          {reach ? t("answeredSendN", { n: reach.count }) : t("answeredSendAll")}
                        </Button>
                        <Button size="sm" variant="quiet" disabled={busy} onClick={() => setComposing(null)}>{t("cancel")}</Button>
                        {reach?.count === 0 && <span className="u-muted u-xs">{t("answeredNobody", { m: reach.minutes })}</span>}
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button" className="vc-review-entry vc-answered__answer" aria-expanded={isOpen}
                      title={isOpen ? undefined : t("reviewEntryExpand")}
                      onClick={() => setUnfolded((m) => ({ ...m, [a.id]: !isOpen }))}
                    >
                      <span className="vc-review-entry__kind" data-author="tutor">{t("answeredAnswerLabel")}</span>
                      <span className="vc-review-entry__text" data-open={isOpen} dir={textDir(flat)}>{flat}</span>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {items.length > FIRST && (
            <Button size="sm" variant="quiet" onClick={() => setAll((v) => !v)}>
              {all ? t("answeredShowFewer") : t("answeredShowAll", { n: items.length })}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
