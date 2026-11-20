import "../styles/pacing.css";
import { useEffect, useId, useRef, useState } from "react";
import { Check, CheckCircle2, Circle, ClipboardCheck, ListChecks, Paperclip, Undo2, XCircle } from "lucide-react";
import { api } from "../api";
import type { StepCheck } from "../types";
import { useLang } from "../i18n";
import { Button, EmptyState, Input, Notice, Time, useToast } from "./ui";
import { textDir } from "../lib/textDir";

/** Step-by-step labs: each student's "Done with step N" answer, next to the
 *  expected values. Approve releases the next step into their chat. Shown only
 *  when an exercise students can open has steps (or an answer waits). */
export function StepChecks({ exerciseId }: { exerciseId: string | null }) {
  const { t } = useLang();
  const toast = useToast();
  const headId = useId();
  const [loaded, setLoaded] = useState(false);
  const [hasSteps, setHasSteps] = useState(false);
  const [allItems, setItems] = useState<StepCheck[]>([]);
  // Only the exercise the live view follows; the rest are counted, not shown.
  const items = allItems.filter((c) => c.exercise_id === exerciseId);
  const elsewhere = allItems.length - items.length;
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  // Counts finished decisions. A poll sent before the latest one finished may
  // still list the answer just decided, so its result is dropped.
  const decided = useRef(0);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      const sentAt = decided.current;
      api.pendingStepChecks()
        .then((r) => {
          if (!alive || sentAt !== decided.current) return;
          setHasSteps(r.has_steps);
          setItems(r.items);
          setLoaded(true);
        })
        .catch(() => { /* a background poll: the app's banner reports a lost server */ });
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const decide = async (c: StepCheck, action: "approve" | "return") => {
    setBusyId(c.id);
    try {
      await api.decideStepCheck(c.id, action, notes[c.id] ?? "");
      decided.current += 1;
      setItems((xs) => xs.filter((x) => x.id !== c.id));
      setNotes((n) => { const next = { ...n }; delete next[c.id]; return next; });
    } catch (e) {
      toast.error(t("pcDecideFailed"), e);
    } finally {
      setBusyId(null);
    }
  };

  // Hidden until the server first answers, and while no lab with steps is in use.
  if (!loaded || (!hasSteps && allItems.length === 0)) return null;

  return (
    <section className={`vc-card vc-pacing${items.length ? " vc-card--info" : ""}`} data-notify-section="step"
             aria-labelledby={headId}>
      <div className="vc-pacing__head">
        <h2 id={headId} className="vc-pacing__title"><ListChecks aria-hidden="true" />{t("stepChecks")}</h2>
        {items.length > 0 && <span className="vc-badge vc-badge--solid-brand vc-badge--count">{items.length}</span>}
      </div>
      <p className="vc-pacing__hint">{t("stepChecksHint")}</p>
      {elsewhere > 0 && <Notice tone="warning" className="u-mt-12">{t("pcOtherExercises", { n: elsewhere })}</Notice>}

      {items.length === 0 ? (
        <EmptyState icon={<ClipboardCheck />} title={t("noStepChecks")}>{t("pcNoChecksText")}</EmptyState>
      ) : items.map((c) => {
        const last = c.step >= c.total;
        const busy = busyId === c.id;
        const complete = c.questions != null && c.answered != null && c.answered >= c.questions;
        return (
          <article key={c.id} className="vc-pacing-item" data-notify-key={`step:${c.id}`}>
            <div className="vc-pacing-item__head">
              <span className="vc-pacing-item__who">{c.username}</span>
              <span className="vc-pacing-item__step">{t("stepOf", { n: c.step, total: c.total })}: {c.title}</span>
              <span className="vc-pacing-item__meta">{t("pcSent")} <Time value={c.created_at} /></span>
              {c.questions != null && c.answered != null && (
                <span className={`vc-badge ${complete ? "vc-badge--success" : "vc-badge--danger"}`} title={t("answeredHint")}>
                  {t("answeredOf", { k: c.answered, n: c.questions })}
                </span>
              )}
            </div>
            <div className="vc-pacing-compare">
              <div>
                <span className="vc-pacing-compare__label">{t("studentAnswer")}</span>
                <div className="vc-pacing-text" dir={textDir(c.answer)}>{c.answer}</div>
              </div>
              <div>
                <span className="vc-pacing-compare__label">{t("expectedAnswer")}</span>
                <div className="vc-pacing-text vc-pacing-text--private" dir={textDir(c.expected)}>{c.expected}</div>
              </div>
            </div>
            <Evidence c={c} />
            <Attachment c={c} />
            <div className="vc-pacing-decide">
              <Input
                className="vc-pacing-note" value={notes[c.id] ?? ""} disabled={busy}
                placeholder={t("noteForStudents")} aria-label={t("noteForStudents")}
                onChange={(e) => setNotes((n) => ({ ...n, [c.id]: e.target.value }))}
              />
              <Button variant="success" icon={<Check />} busy={busy} onClick={() => decide(c, "approve")}>
                {last ? t("approveFinish") : t("approveNext", { n: c.step + 1 })}
              </Button>
              <Button icon={<Undo2 />} disabled={busy} onClick={() => decide(c, "return")}>
                {t("sendBack")}
              </Button>
            </div>
          </article>
        );
      })}
    </section>
  );
}

/** The step's evidence rules and the student's last terminal lines (IDE plugin). */
function Evidence({ c }: { c: StepCheck }) {
  const { t } = useLang();
  const { rules, recent } = c.evidence ?? { rules: [], recent: [] };
  if (rules.length === 0 && recent.length === 0) return null;
  return (
    <div className="vc-pacing-term">
      <div className="vc-pacing-term__title">{t("terminalEvidence")}</div>
      {rules.map((r, i) => {
        const word = r.ok === false ? t("pcRuleFailed") : r.ok ? t("pcRulePassed") : t("pcRuleUnknown");
        const tone = r.ok === false ? " vc-pacing-term__fail" : r.ok ? " vc-pacing-term__ok" : "";
        return (
          <div key={i} className="vc-pacing-term__rule">
            <span className={`vc-pacing-term__name${tone}`} title={word}>
              {r.ok === false ? <XCircle aria-hidden="true" /> : r.ok ? <CheckCircle2 aria-hidden="true" /> : <Circle aria-hidden="true" />}
              <span dir={textDir(r.label)}>{r.label}</span>
              <span className="u-sr"> ({word})</span>
            </span>
            {r.found ? (
              <>
                <pre dir="ltr" className="vc-pacing-term__cmd">$ {r.line}</pre>
                {r.output && <pre dir="ltr">{r.output}</pre>}
              </>
            ) : (
              <span className="vc-pacing-term__fail"> · {t("evidenceMissing")}</span>
            )}
          </div>
        );
      })}
      {recent.length > 0 && (
        <details open={rules.length === 0}>
          <summary>{t("recentLines")}</summary>
          {recent.map((r, i) => (
            <div key={i} className="u-mt-4">
              <pre dir="ltr" className={r.allowed ? "vc-pacing-term__cmd" : "vc-pacing-term__blocked"}>
                $ {r.line}{"  "}
                <span className="vc-pacing-term__exit">
                  {r.allowed ? t("pcExit", { n: r.exit_code ?? "?" }) : t("blockedShort")}
                </span>
              </pre>
              {r.output && <pre dir="ltr">{r.output}</pre>}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

/** The open file, Run console and check output the plugin attached. */
function Attachment({ c }: { c: StepCheck }) {
  const { t } = useLang();
  if (!c.code) return null;
  const { filename, source, console: out, check_output: check } = c.code;
  return (
    <details className="vc-pacing-attach">
      <summary><Paperclip aria-hidden="true" />{t("attachedCode", { f: filename || t("pcCodeDefault") })}</summary>
      {check && (
        <>
          <span className="vc-pacing-compare__label u-mt-8">{t("checkOutput")}</span>
          <pre dir="ltr" className="vc-pre vc-pre--light vc-pacing-pre">{check}</pre>
        </>
      )}
      {source && <pre dir="ltr" className="vc-pre vc-pre--light vc-pacing-pre">{source}</pre>}
      {out && (
        <>
          <span className="vc-pacing-compare__label u-mt-8">{t("consoleOutput")}</span>
          <pre dir="ltr" className="vc-pre vc-pre--light vc-pacing-pre">{out}</pre>
        </>
      )}
    </details>
  );
}
