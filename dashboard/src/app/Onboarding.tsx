import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { api, type Overview } from "../api";
import { useLang, type StringKey } from "../i18n";
import { Button } from "../components/ui";

const HIDDEN_KEY = "vericlass.firstSteps.hidden";
const SHARED_KEY = "vericlass.firstSteps.shared";

function flag(key: string): boolean {
  try { return localStorage.getItem(key) === "1"; } catch { return false; }
}
export function markShared() {
  try { localStorage.setItem(SHARED_KEY, "1"); } catch { /* not remembered, that's all */ }
}

/** The first-steps checklist on the class page: what a new lecturer does
 *  before the first class, each step with the button that does it. It goes
 *  away once students have signed in, or when the lecturer hides it. */
export function Onboarding({ llmReady, onSettings, onCourses, onShare }: {
  llmReady: boolean;
  onSettings: () => void;
  onCourses: () => void;
  onShare: () => void;
}) {
  const { t } = useLang();
  const [hidden, setHidden] = useState(() => flag(HIDDEN_KEY));
  const [o, setO] = useState<Overview | null>(null);

  useEffect(() => {
    if (hidden) return;
    let alive = true;
    const load = () => api.overview().then((v) => { if (alive) setO(v); }).catch(() => { /* the banner reports a lost server */ });
    load();
    const id = window.setInterval(load, 10_000);
    return () => { alive = false; window.clearInterval(id); };
  }, [hidden]);

  if (hidden || !o) return null;
  const steps: { done: boolean; title: StringKey; hint: StringKey; action: StringKey; run: () => void }[] = [
    { done: llmReady, title: "ob1", hint: "ob1Hint", action: "ob1Action", run: onSettings },
    { done: o.students > 0, title: "ob2", hint: "ob2Hint", action: "ob2Action", run: onCourses },
    { done: o.courses_with_exercise && o.courses_with_students, title: "ob3", hint: "ob3Hint", action: "ob3Action", run: onCourses },
    { done: o.sessions > 0 || flag(SHARED_KEY), title: "ob4", hint: "ob4Hint", action: "ob4Action", run: onShare },
  ];
  const allDone = steps.every((s) => s.done);
  // An installation that already ran classes doesn't need the checklist.
  if (allDone && o.sessions > 0) return null;

  const hide = () => {
    try { localStorage.setItem(HIDDEN_KEY, "1"); } catch { /* shown again next time */ }
    setHidden(true);
  };

  return (
    <section className="vc-card vc-card--brand vc-card--pad-lg u-mb-16" aria-label={t("obTitle")}>
      <div className="u-row u-row--top">
        <div className="u-grow">
          <h2>{t("obTitle")}</h2>
          <p className="u-soft">{allDone ? t("obAllDone") : t("obLead")}</p>
        </div>
        <Button variant="quiet" size="sm" icon={<X />} onClick={hide}>{t("hide")}</Button>
      </div>
      <div className="vc-checklist">
        {steps.map((s, i) => (
          <div key={s.title} className="vc-checklist__item" data-done={s.done}>
            <span className="vc-checklist__mark">{s.done ? <Check /> : i + 1}</span>
            <div className="vc-checklist__text">
              <div className="vc-checklist__title">{t(s.title)}</div>
              {!s.done && <div className="vc-checklist__hint">{t(s.hint)}</div>}
            </div>
            {!s.done && <Button variant={steps.findIndex((x) => !x.done) === i ? "primary" : "secondary"} size="sm" onClick={s.run}>{t(s.action)}</Button>}
          </div>
        ))}
      </div>
    </section>
  );
}
