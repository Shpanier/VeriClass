import "../styles/pacing.css";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle, Check, CheckCircle2, ChevronDown, FastForward, Gauge, HelpCircle, Hourglass, Info, Lock, LockOpen,
  PenLine, Undo2, User, Users,
} from "lucide-react";
import { api } from "../api";
import type { PacingAnswer, PacingCourse, PacingOverview, PacingQuizItem, PacingStep, PacingStudent } from "../types";
import { useLang, type Translate } from "../i18n";
import { describeError } from "../lib/errors";
import {
  Button, Check as Checkbox, EmptyState, Input, Loading, Notice, Select, Textarea, Time, useConfirm, useToast,
  type ConfirmOptions,
} from "./ui";
import { textDir } from "../lib/textDir";

/** A step's name as the lecturer reads it: its label (A1, B2…), else its number. */
function stepLabel(steps: PacingStep[], n: number): string {
  return steps[n - 1]?.label ?? String(n);
}

/** "A1–A3": kept left to right inside a Hebrew sentence (an isolated run). */
function stepRange(steps: PacingStep[], from: number, to: number): string {
  const a = stepLabel(steps, from);
  return from >= to ? a : `⁦${a}–${stepLabel(steps, to)}⁩`;
}

function courseName(c: PacingCourse, t: Translate): string {
  return c.course_id ? (c.name || c.course_id) : t("pacingNoCourse");
}

/** The course with the most students in the lab. */
function busiest(courses: PacingCourse[]): PacingCourse {
  return [...courses].sort((a, b) => b.students.length - a.students.length)[0];
}

/** Class-paced labs (pacing: class): how far the class got, the button that
 *  opens the next step for everyone, and what waits for the lecturer: outputs
 *  that didn't match, quiz answers graded too low, questions to approve. */
export function PacingPanel({ exerciseId, quizSlot }: {
  exerciseId: string;
  /** Where the questions after steps are drawn: the bottom of the page (App.tsx). Without it, here. */
  quizSlot?: HTMLElement | null;
}) {
  const { t, dir } = useLang();
  const toast = useToast();
  const confirm = useConfirm();
  const [view, setView] = useState<PacingOverview | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  // The course the controls act on: chosen once (the busiest when the data
  // first arrives), then kept until the lecturer picks another or it disappears,
  // so a poll never switches it under the lecturer's hand.
  const [courseId, setCourseId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // "Questions wait for approval" opens the questions at the bottom of the page and scrolls to them.
  const [quizOpenReq, setQuizOpenReq] = useState(0);
  const idRef = useRef(exerciseId);
  idRef.current = exerciseId;

  // A background poll: failures stay quiet (the app's banner reports a lost server).
  const load = () => api.pacing(exerciseId)
    .then((v) => { if (idRef.current === exerciseId) { setView(v); setLoadError(null); } })
    .catch((e) => { if (idRef.current === exerciseId) setLoadError(e); });
  // Answers that wait for the lecturer's decision, in every course of this lab.
  const heldNow = view ? view.courses.reduce(
    (n, c) => n + c.students.reduce((k, s) => k + s.quiz.filter((a) => a.review === "waiting").length, 0), 0) : 0;

  // "(2 ✍️) VeriClass": answers waiting for the lecturer show in the tab, on any tab of the browser.
  useEffect(() => {
    const base = document.title.replace(/^\(\d+ ✍️\) /, "");
    document.title = heldNow > 0 ? `(${heldNow} ✍️) ${base}` : base;
    return () => { document.title = document.title.replace(/^\(\d+ ✍️\) /, ""); };
  }, [heldNow]);

  useEffect(() => {
    setView(null);
    setLoadError(null);
    setCourseId(null);
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exerciseId]);

  // Pin the course once there is data; choose again only when it disappears.
  useEffect(() => {
    if (!view || view.courses.length === 0) return;
    if (courseId !== null && view.courses.some((c) => c.course_id === courseId)) return;
    setCourseId(busiest(view.courses).course_id);
  }, [view, courseId]);

  if (!view) {
    return (
      <section className="vc-card vc-pacing" aria-label={t("pacing")}>
        <h2 className="vc-pacing__title"><Gauge aria-hidden="true" />{t("pacing")}</h2>
        {loadError
          ? <Notice tone="danger" title={t("pcLoadFailed")} className="u-mt-12">{describeError(loadError, t)}</Notice>
          : <Loading />}
      </section>
    );
  }

  const empty: PacingCourse = {
    course_id: "", name: "", released: view.open_steps, members: null, students: [], done: {}, here: {}, quiz_missed: {},
  };
  const courses = view.courses.length ? view.courses : [empty];
  const many = courses.length > 1;
  const course = courses.find((c) => c.course_id === courseId) ?? busiest(courses);
  const rel = course.released;
  const total = view.total;
  const label = (n: number) => stepLabel(view.steps, n);
  const range = (a: number, b: number) => stepRange(view.steps, a, b);
  const who = many ? t("pcWhoCourse", { course: courseName(course, t) }) : t("pcWhoClass");

  const release = async (n: number) => {
    setBusy(true);
    try {
      await api.releaseSteps(exerciseId, course.course_id, n);
      await load();
    } catch (e) {
      toast.error(t("pcOpenFailed"), e);
    } finally {
      setBusy(false);
    }
  };

  // Closing reaches the whole class: confirm. Students past it keep their work and wait.
  const closeLast = async () => {
    if (!(await confirm({
      title: t("pcCloseOneTitle", { label: label(rel) }),
      body: t("pcCloseOneBody", { who }),
      confirmLabel: t("pacingCloseLast", { label: label(rel) }),
    }))) return;
    await release(rel - 1);
  };

  // "Change the last open step…": any step, the ones open from the start included
  // ("up to A5" stops everyone after A5). The next step alone is the usual one click.
  const jump = async (n: number) => {
    if (n === rel + 1) {
      await release(n);
      return;
    }
    let ask: ConfirmOptions;
    if (n > rel) {
      ask = {
        title: t("pcOpenTitle", { label: label(n) }),
        body: t("pcOpenBody", { range: range(rel + 1, n), who }),
        confirmLabel: t("pcOpenBtn", { label: label(n) }),
      };
    } else if (n === 0) {
      ask = { title: t("pcCloseAllTitle"), body: t("pcCloseAllBody", { who }), confirmLabel: t("pacingCloseAll") };
    } else {
      const one = n + 1 === rel;
      ask = {
        title: one ? t("pcCloseOneTitle", { label: label(rel) }) : t("pcCloseManyTitle", { range: range(n + 1, rel) }),
        body: one ? t("pcCloseOneBody", { who }) : t("pcCloseBody", { who }),
        confirmLabel: one ? t("pacingCloseLast", { label: label(rel) }) : t("pcCloseManyBtn", { range: range(n + 1, rel) }),
      };
    }
    if (await confirm(ask)) await release(n);
  };

  // Everyone back to step n: students past it go back; the others stay.
  // Students on step n start it over too; back to the first step: a fresh chat for each.
  const resetAll = async (n: number) => {
    const k = course.students.filter((s) => s.current >= n).length;
    if (!(await confirm({
      title: t("pcResetAllTitle", { who, label: label(n) }),
      body: n === 1 ? t("pcResetAllFirstBody", { k }) : t("pcResetAllBody", { k, label: label(n) }),
      confirmLabel: t("pcResetAllBtn", { label: label(n) }),
      danger: true,
    }))) return;
    setBusy(true);
    try {
      const r = await api.resetCourse(exerciseId, course.course_id, n);
      toast.success(t("pcResetDone", { n: r.moved, label: label(n) }));
      await load();
    } catch (e) {
      toast.error(t("pcResetFailed"), e);
    } finally {
      setBusy(false);
    }
  };

  const started = course.students.length;
  const finishedOpen = course.students.filter((s) => s.current > rel && s.current <= total).length;
  const pendingQuiz = view.quiz.filter((q) => !q.approved).length;
  const outputsWaiting = course.students.reduce((n, s) => n + s.waiting.length, 0);
  const resetUpTo = Math.min(total, Math.max(0, ...course.students.map((s) => s.current)));

  const quiz = (
    <Quiz exerciseId={exerciseId} items={view.quiz} course={course} pending={pendingQuiz} onChange={load}
          openReq={quizOpenReq} />
  );

  const statusMain = rel >= total ? t("pacingAllOpen", { n: total })
    : rel === 0 ? t("pacingNoneOpen")
    : rel === 1 ? t("pcStatusOne", { label: label(1) })
    : t("pcStatusRange", { range: range(1, rel) });
  const fromStart = view.open_steps <= 0 ? t("pcFromStartNone")
    : view.open_steps === 1 ? t("pcFromStartOne", { label: label(1) })
    : t("pcFromStart", { range: range(1, view.open_steps) });

  return (
    <section className="vc-card vc-pacing" aria-labelledby="vc-pacing-title">
      <div className="vc-pacing__head">
        <h2 id="vc-pacing-title" className="vc-pacing__title"><Gauge aria-hidden="true" />{t("pacing")}</h2>
        {many && (
          <label className="vc-pacing-course">
            <span>{t("pcCourse")}</span>
            <Select small value={course.course_id} onChange={(e) => setCourseId(e.target.value)}>
              {courses.map((c) => (
                <option key={c.course_id} value={c.course_id}>
                  {t("pcCourseOption", { name: courseName(c, t), n: c.students.length })}
                </option>
              ))}
            </Select>
          </label>
        )}
      </div>
      <p className="vc-pacing__hint">{fromStart} {t("pcAppliesTo", { who })}</p>
      <details className="vc-pacing-how">
        <summary><Info aria-hidden="true" />{t("pcHow")}</summary>
        <ul>
          <li>{t("pcHow1")}</li>
          <li>{t("pcHow2")}</li>
          <li>{t("pcHow3")}</li>
          <li>{t("pcHow4")}</li>
        </ul>
      </details>

      {/* Where the class is, and the controls that act on the whole class (or course). */}
      <div className="vc-pacing-status">
        <div className="vc-pacing-status__text">
          <div className="vc-pacing-status__main">{statusMain}</div>
          <div className="vc-pacing-status__sub">
            {many && <><span className="u-bold">{courseName(course, t)}</span> · </>}
            {course.members != null
              ? t("pcStartedOf", { k: started, n: course.members })
              : t("pcStarted", { k: started })}
            {finishedOpen > 0 && <> · <strong>{t("pacingFinishedOpen", { k: finishedOpen })}</strong></>}
          </div>
          {(heldNow > 0 || outputsWaiting > 0 || pendingQuiz > 0) && (
            <div className="vc-pacing-needs-line">
              <span>{t("pcNeedsYou")}</span>
              {heldNow > 0 && (
                <span className="vc-badge vc-badge--danger"><PenLine aria-hidden="true" />{t("pcNeedAnswers", { n: heldNow })}</span>
              )}
              {outputsWaiting > 0 && (
                <span className="vc-badge vc-badge--warning"><Hourglass aria-hidden="true" />{t("pcNeedOutputs", { n: outputsWaiting })}</span>
              )}
              {pendingQuiz > 0 && (
                <button type="button" className="vc-badge vc-badge--warning vc-badge--button"
                        title={t("pcGoToQuiz")} onClick={() => setQuizOpenReq((n) => n + 1)}>
                  <HelpCircle aria-hidden="true" />{t("pcNeedQuiz", { n: pendingQuiz })}
                </button>
              )}
            </div>
          )}
        </div>
        <div className="vc-pacing-status__actions">
          {rel < total && (
            <Button variant="primary" icon={<LockOpen />} busy={busy} onClick={() => release(rel + 1)}>
              {t("pacingOpenNext", { label: label(rel + 1) })}
            </Button>
          )}
          {rel > 0 && (
            <Button icon={<Lock />} disabled={busy} onClick={closeLast}>
              {t("pacingCloseLast", { label: label(rel) })}
            </Button>
          )}
          <Select
            inline value="" disabled={busy} aria-label={t("pcJumpAria")}
            onChange={(e) => { if (e.target.value !== "") jump(Number(e.target.value)); }}
          >
            <option value="">{t("pcJump")}</option>
            {rel < total && (
              <optgroup label={t("pcJumpOpen")}>
                {view.steps.filter((s) => s.n > rel).map((s) => (
                  <option key={s.n} value={s.n}>{s.label} · {s.title}</option>
                ))}
              </optgroup>
            )}
            {rel > 1 && (
              <optgroup label={t("pcJumpClose")}>
                {view.steps.filter((s) => s.n < rel).map((s) => (
                  <option key={s.n} value={s.n}>{s.label} · {s.title}</option>
                ))}
              </optgroup>
            )}
            {rel > 0 && <option value="0">{t("pacingCloseAll")}</option>}
          </Select>
          {course.students.length > 0 && resetUpTo > 0 && (
            <Select
              inline value="" disabled={busy} aria-label={t("pcResetAllAria")} title={t("pacingResetHint")}
              onChange={(e) => { if (e.target.value !== "") resetAll(Number(e.target.value)); }}
            >
              <option value="">{t("pacingResetAll")}</option>
              {view.steps.filter((s) => s.n <= resetUpTo).map((s) => (
                <option key={s.n} value={s.n}>{s.label} · {s.title}</option>
              ))}
            </Select>
          )}
        </div>
      </div>

      {/* One chip per step: open or closed, how many finished it, how many are on it. */}
      <div className="vc-pacing-legend">
        <span>{t("pcLegend")}</span>
        <span className="vc-pacing-legend__item"><CheckCircle2 aria-hidden="true" />{t("pcLegendDone")}</span>
        <span className="vc-pacing-legend__item vc-pacing-count--here"><User aria-hidden="true" />{t("pcLegendHere")}</span>
        <span className="vc-pacing-legend__item vc-pacing-count--quiz"><HelpCircle aria-hidden="true" />{t("pcLegendQuiz")}</span>
        <span className="vc-pacing-legend__item"><Lock aria-hidden="true" />{t("pcLegendClosed")}</span>
        {rel < total && (
          <span className="vc-pacing-legend__item"><span className="vc-pacing-legend__swatch" aria-hidden="true" />{t("pcLegendNext")}</span>
        )}
      </div>
      <ol className="vc-pacing-chips" aria-label={t("pcStepsAria")} dir="ltr">
        {view.steps.map((s) => {
          const open = s.n <= rel;
          const next = s.n === rel + 1;
          const done = course.done[s.n] ?? 0;
          const here = course.here[s.n] ?? 0;
          const unapproved = s.quiz - s.quiz_approved;
          const state = open ? t("pcStateOpen") : next ? t("pcStateNext") : t("pcStateClosed");
          const tip = t("pcChipTip", { label: s.label, title: s.title, state, done, here })
            + (unapproved > 0 ? ` ${t("pcChipQuiz", { n: unapproved })}` : "");
          return (
            <li key={s.n} className="vc-pacing-chip" data-state={open ? "open" : next ? "next" : "closed"} title={tip} dir={dir}>
              <span className="u-sr">{tip}</span>
              <span className="vc-pacing-chip__label" aria-hidden="true" dir="ltr">{!open && <Lock />}{s.label}</span>
              <span className="vc-pacing-chip__counts" aria-hidden="true" dir="ltr">
                <span className="vc-pacing-count"><CheckCircle2 />{done}</span>
                {here > 0 && <span className="vc-pacing-count vc-pacing-count--here"><User />{here}</span>}
                {unapproved > 0 && <span className="vc-pacing-count vc-pacing-count--quiz"><HelpCircle />{unapproved}</span>}
              </span>
            </li>
          );
        })}
      </ol>

      {heldNow > 0 && (
        <AnswerReview exerciseId={exerciseId} courses={view.courses} items={view.quiz} steps={view.steps} onChange={load} />
      )}
      <Review exerciseId={exerciseId} course={course} steps={view.steps} onChange={load} />
      <Students course={course} total={total} steps={view.steps} onChange={load} />
      {quizSlot === undefined && quiz}
      {quizSlot && createPortal(
        <section className="vc-card vc-pacing vc-pacing--quiz" aria-label={t("pacingQuiz")}>{quiz}</section>, quizSlot,
      )}
    </section>
  );
}

/** Outputs that didn't match their step's checks: the student's paste next to
 *  the expected output; let the student continue, or send it back with a note. */
function Review({ exerciseId, course, steps, onChange }: {
  exerciseId: string; course: PacingCourse; steps: PacingStep[]; onChange: () => void;
}) {
  const { t } = useLang();
  const toast = useToast();
  const headId = useId();
  const [busy, setBusy] = useState<string | null>(null);
  // The lecturer's note to the student when sending an output back, per session.
  const [notes, setNotes] = useState<Record<string, string>>({});
  const items = course.students.flatMap((s) => s.waiting.map((w) => ({ s, w })));
  if (items.length === 0) return null;

  const decide = async (sessionId: string, step: number, approve: boolean) => {
    setBusy(sessionId);
    try {
      if (approve) await api.letThrough(exerciseId, sessionId, step);
      else await api.declineOutput(exerciseId, sessionId, step, notes[sessionId]);
      setNotes((m) => { const next = { ...m }; delete next[sessionId]; return next; });
      onChange();
    } catch (e) {
      toast.error(t("pcDecideFailed"), e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="vc-pacing-wait" aria-labelledby={headId}>
      <div className="vc-pacing-wait__head">
        <h3 id={headId} className="vc-pacing-wait__title"><Hourglass aria-hidden="true" />{t("pacingReview")}</h3>
        <span className="vc-badge vc-badge--solid-warning vc-badge--count">{items.length}</span>
      </div>
      <p className="vc-pacing-wait__hint">{t("pacingReviewHint")}</p>
      {items.map(({ s, w }) => {
        const step = steps[w.step - 1];
        const working = busy === s.session_id;
        return (
          <article key={s.session_id} className="vc-pacing-item">
            <div className="vc-pacing-item__head">
              <span className="vc-pacing-item__who">{s.username}</span>
              <span className="vc-pacing-item__step">{w.label}{step ? ` · ${step.title}` : ""}</span>
              {w.created_at && <span className="vc-pacing-item__meta">{t("pcPasted")} <Time value={w.created_at} /></span>}
            </div>
            <div className="vc-pacing-compare">
              <div>
                <span className="vc-pacing-compare__label">{t("pacingTheirOutput")}</span>
                <pre dir="ltr" className="vc-pre vc-pre--light vc-pacing-pre vc-pacing-out">{w.output || "—"}</pre>
              </div>
              <div>
                <span className="vc-pacing-compare__label">{t("pacingExpected")}</span>
                <pre dir="ltr" className="vc-pre vc-pre--light vc-pacing-pre vc-pacing-out vc-pacing-private">
                  {step?.expected_output || step?.expected || t("pacingNoExpected")}
                </pre>
              </div>
            </div>
            {w.missing.length > 0 && (
              <div className="vc-pacing-missing">
                <AlertTriangle aria-hidden="true" />
                <span>{t("pacingMissing")}: {w.missing.map((m, i) => (
                  <span key={i}>{i > 0 && " · "}<bdi dir="ltr" className="vc-mono">{m}</bdi></span>
                ))}</span>
              </div>
            )}
            <div className="vc-pacing-decide vc-pacing-decide--center">
              <Button variant="success" icon={<Check />} busy={working} onClick={() => decide(s.session_id, w.step, true)}>
                {t("pacingLetThrough")}
              </Button>
              {/* The note belongs to "send back": it travels only with that decision. */}
              <div className="vc-pacing-sendback">
                <label className="vc-pacing-sendback__field">
                  <span className="vc-label">{t("pcSendBackLabel")}</span>
                  <Input
                    value={notes[s.session_id] ?? ""} placeholder={t("pacingDeclineNote")} disabled={working}
                    onChange={(e) => setNotes((m) => ({ ...m, [s.session_id]: e.target.value }))}
                  />
                </label>
                <Button variant="danger-soft" icon={<Undo2 />} disabled={working} onClick={() => decide(s.session_id, w.step, false)}>
                  {t("pacingDecline")}
                </Button>
              </div>
            </div>
          </article>
        );
      })}
    </section>
  );
}

/** Where the text for the student comes from: nothing, the grader's reason,
 *  the model answer, or the lecturer's own words. */
type TextSource = "" | "grader" | "model" | "own";

/** Quiz answers the grader gave too low a grade to move on by itself
 *  (exercise.yaml quiz_review): the student's answer next to the model answer,
 *  and the lecturer's decision: continue, or answer again. */
function AnswerReview({ exerciseId, courses, items, steps, onChange }: {
  exerciseId: string; courses: PacingCourse[]; items: PacingQuizItem[]; steps: PacingStep[]; onChange: () => void;
}) {
  const { t } = useLang();
  const toast = useToast();
  const headId = useId();
  const [busy, setBusy] = useState<number | null>(null);
  // Per answer: the text for the student (picked, then edited), where it came
  // from, and the grade to set on "continue" ("" = keep).
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [sources, setSources] = useState<Record<number, TextSource>>({});
  const [grades, setGrades] = useState<Record<number, string>>({});
  const many = courses.filter((c) => c.students.some((s) => s.quiz.some((a) => a.review === "waiting"))).length > 1;
  const held: { s: PacingStudent; a: PacingAnswer; c: PacingCourse }[] = courses
    .flatMap((c) => c.students.flatMap((s) => s.quiz.filter((a) => a.review === "waiting").map((a) => ({ s, a, c }))))
    .sort((x, y) => (x.a.answered_at ?? "").localeCompare(y.a.answered_at ?? "") || x.a.id - y.a.id);
  if (held.length === 0) return null;

  const pick = (a: PacingAnswer, source: TextSource) => {
    const model = items.find((q) => q.key === a.key)?.answer ?? "";
    const text = source === "grader" ? (a.why ?? "") : source === "model" ? model : source === "" ? "" : (notes[a.id] ?? "");
    setSources((m) => ({ ...m, [a.id]: source }));
    setNotes((m) => ({ ...m, [a.id]: text }));
  };

  const decide = async (id: number, approve: boolean) => {
    setBusy(id);
    try {
      const note = (notes[id] ?? "").trim() || undefined;
      if (approve) await api.reviewAnswer(exerciseId, id, "approve", { note, grade: grades[id] ? Number(grades[id]) : undefined });
      else await api.reviewAnswer(exerciseId, id, "return", { note });
      setNotes((m) => { const next = { ...m }; delete next[id]; return next; });
      setSources((m) => { const next = { ...m }; delete next[id]; return next; });
      setGrades((m) => { const next = { ...m }; delete next[id]; return next; });
      onChange();
    } catch (e) {
      toast.error(t("pcDecideFailed"), e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="vc-pacing-wait vc-pacing-wait--urgent" aria-labelledby={headId}>
      <div className="vc-pacing-wait__head">
        <h3 id={headId} className="vc-pacing-wait__title"><PenLine aria-hidden="true" />{t("pacingAnswerReview")}</h3>
        <span className="vc-badge vc-badge--solid-danger vc-badge--count">{held.length}</span>
      </div>
      <p className="vc-pacing-wait__hint">{t("pacingAnswerReviewHint")}</p>
      <details className="vc-pacing-how">
        <summary><Info aria-hidden="true" />{t("pcHow")}</summary>
        <p>{t("pcHowAnswers")}</p>
      </details>
      {held.map(({ s, a, c }) => {
        const item = items.find((q) => q.key === a.key);
        const step = steps[a.step - 1];
        const working = busy === a.id;
        const source = sources[a.id] ?? "";
        return (
          <article key={a.id} className="vc-pacing-item">
            <div className="vc-pacing-item__head">
              <span className="vc-pacing-item__who">{s.username}</span>
              {many && <span className="vc-badge">{courseName(c, t)}</span>}
              <span className="vc-pacing-item__step">{step?.label ?? a.step}{step ? ` · ${step.title}` : ""}</span>
              <span className={`vc-badge ${a.grade === 0 ? "vc-badge--danger" : "vc-badge--warning"}`} title={t("pcGradeTitle")}>
                <span className="u-sr">{t("pcGradeTitle")}: </span>{a.grade ?? "?"}/2
              </span>
              {a.answered_at && <span className="vc-pacing-item__meta">{t("pcAnswered")} <Time value={a.answered_at} /></span>}
            </div>
            <div className="u-mt-8">
              <span className="vc-pacing-compare__label">{t("pcQuestion")}</span>
              <div className="vc-pacing-text" dir={textDir(a.body)}>{a.body}</div>
            </div>
            <div className="vc-pacing-compare">
              <div>
                <span className="vc-pacing-compare__label">{t("pacingTheirAnswer")}</span>
                <div className="vc-pacing-text" dir={textDir(a.answer)}>{a.answer || "—"}</div>
              </div>
              <div>
                <span className="vc-pacing-compare__label">{t("pacingModelAnswer")}</span>
                <div className="vc-pacing-text vc-pacing-text--private" dir={textDir(item?.answer)}>{item?.answer || "—"}</div>
              </div>
            </div>
            <p className="u-xs u-warning u-mt-8" dir={textDir(a.why)}>
              {t("pacingGraderSays", { g: a.grade ?? 0 })}{a.why ? ` — ${a.why}` : ""}
            </p>
            <div className="vc-pacing-tell">
              <div className="u-row u-wrap">
                <label className="u-sm u-bold" htmlFor={`vc-pacing-tell-${a.id}`}>{t("pacingTellThem")}</label>
                <Select
                  id={`vc-pacing-tell-${a.id}`} small inline value={source} disabled={working}
                  onChange={(e) => pick(a, e.target.value as TextSource)}
                >
                  <option value="">{t("pacingTellNothing")}</option>
                  {a.why && <option value="grader">{t("pacingTellGrader")}</option>}
                  {item?.answer && <option value="model">{t("pacingTellModel")}</option>}
                  <option value="own">{t("pacingTellOwn")}</option>
                </Select>
                <span className="u-muted u-xs">{t("pacingTellHint")}</span>
              </div>
              {source !== "" && (
                <Textarea
                  className="u-mt-8" value={notes[a.id] ?? ""} dir={textDir(notes[a.id] || item?.answer)} rows={3} disabled={working}
                  aria-label={t("pacingAnswerNote")} placeholder={t("pacingAnswerNote")}
                  onChange={(e) => setNotes((m) => ({ ...m, [a.id]: e.target.value }))}
                />
              )}
            </div>
            <div className="vc-pacing-decide">
              <div className="vc-pacing-group">
                <label className="vc-pacing-field">
                  <span className="vc-label">{t("pcGradeIfContinue")}</span>
                  <Select
                    inline value={grades[a.id] ?? ""} disabled={working}
                    onChange={(e) => setGrades((m) => ({ ...m, [a.id]: e.target.value }))}
                  >
                    <option value="">{t("pacingGradeKeep", { g: a.grade ?? 0 })}</option>
                    {[0, 1, 2].filter((g) => g !== a.grade).map((g) => (
                      <option key={g} value={g}>{t("pacingGradeSet", { g })}</option>
                    ))}
                  </Select>
                </label>
                <Button variant="success" icon={<Check />} busy={working} onClick={() => decide(a.id, true)}>
                  {t("pacingLetThrough")}
                </Button>
              </div>
              <Button variant="danger-soft" icon={<Undo2 />} disabled={working} onClick={() => decide(a.id, false)}>
                {t("pacingAnswerReturn")}
              </Button>
            </div>
          </article>
        );
      })}
    </section>
  );
}

/** Each student's step, the furthest behind first, with the steps the lecturer
 *  let them past although their output didn't match; "Move to step…" per student. */
function Students({ course, total, steps, onChange }: {
  course: PacingCourse; total: number; steps: PacingStep[]; onChange: () => void;
}) {
  const { t } = useLang();
  const toast = useToast();
  const confirm = useConfirm();
  const rows = [...course.students].sort((a, b) => a.current - b.current || a.username.localeCompare(b.username));
  const quizzing = rows.filter((s) => s.quiz_pending > 0).length;
  const held = rows.filter((s) => s.quiz_review > 0).length;
  // Open or closed is the lecturer's choice; at first, open unless the class is large.
  const [open, setOpen] = useState(rows.length <= 40);
  const [moving, setMoving] = useState<string | null>(null);
  const label = (n: number) => stepLabel(steps, n);

  // Back (their work from there on no longer counts), ahead (the steps between
  // are skipped and opened for them), or the step they are on (start it over).
  const move = async (s: PacingStudent, n: number) => {
    const name = s.username;
    const lbl = label(n);
    // Back to the first step: the lab starts over in a fresh chat (the earlier one is kept).
    const ask: ConfirmOptions = n === 1
      ? { title: t("pcRestartTitle", { who: name }), body: t("pcRestartBody"),
          confirmLabel: t("pcMoveAgainBtn"), danger: true }
      : n < s.current
      ? { title: t("pcMoveBackTitle", { who: name, label: lbl }), body: t("pcMoveBackBody", { label: lbl }),
          confirmLabel: t("pcMoveBackBtn"), danger: true }
      : n > s.current
        ? { title: t("pcMoveAheadTitle", { who: name, label: lbl }), body: t("pcMoveAheadBody", { label: lbl }),
            confirmLabel: t("pcMoveAheadBtn") }
        : { title: t("pcMoveAgainTitle", { who: name, label: lbl }), body: t("pcMoveAgainBody"),
            confirmLabel: t("pcMoveAgainBtn") };
    if (!(await confirm(ask))) return;
    setMoving(s.session_id);
    try {
      await api.moveSession(s.session_id, n);
      toast.success(t("pcMoved", { who: name, label: lbl }));
      onChange();
    } catch (e) {
      toast.error(t("pcMoveFailed", { who: name }), e);
    } finally {
      setMoving(null);
    }
  };

  const option = (s: PacingStep) => <option key={s.n} value={s.n}>{s.label} · {s.title}</option>;

  return (
    <details className="vc-pacing-block" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <ChevronDown className="vc-pacing-chev" aria-hidden="true" />
        <span>{t("pacingStudents")}</span>
        <span className="vc-badge vc-badge--count">{rows.length}</span>
        {quizzing > 0 && <span className="vc-badge vc-badge--info">{t("pacingQuizWaiting", { n: quizzing })}</span>}
        {held > 0 && <span className="vc-badge vc-badge--danger">{t("pacingAnswerWaiting", { n: held })}</span>}
      </summary>
      {rows.length === 0 ? (
        <EmptyState icon={<Users />} title={t("pacingNoStudents")}>{t("pcNoStudentsText")}</EmptyState>
      ) : (
        <ul className="vc-pacing-students">
          {rows.map((s) => {
            const finished = s.current > total;
            const back = steps.filter((st) => st.n < s.current);
            const ahead = steps.filter((st) => st.n > s.current);
            const here = steps.find((st) => st.n === s.current);
            return (
              <li key={s.session_id} className="vc-pacing-student">
                <div className="vc-pacing-student__row">
                  <span className="vc-pacing-student__name">{s.username}</span>
                  <span className={`vc-badge ${finished ? "vc-badge--success" : "vc-badge--info"}`}>
                    {finished ? t("pacingDone") : t("pacingOnStep", { label: s.current_label ?? "" })}
                  </span>
                  {(s.waiting.length > 0 || s.quiz_pending > 0 || s.quiz_review > 0) && (
                    <span className="vc-pacing-student__marks">
                      {s.waiting.length > 0 && (
                        <span className="u-warning" title={t("pcRowOutput")}>
                          <Hourglass aria-hidden="true" /><span className="u-sr">{t("pcRowOutput")}</span>
                        </span>
                      )}
                      {s.quiz_pending > 0 && (
                        <span className="u-brand" title={t("pcRowAnswering")}>
                          <HelpCircle aria-hidden="true" /><span className="u-sr">{t("pcRowAnswering")}</span>
                        </span>
                      )}
                      {s.quiz_review > 0 && (
                        <span className="u-danger" title={t("pcRowAnswer")}>
                          <PenLine aria-hidden="true" /><span className="u-sr">{t("pcRowAnswer")}</span>
                        </span>
                      )}
                    </span>
                  )}
                  <Select
                    small value="" disabled={moving === s.session_id} aria-label={t("pcMoveAria", { who: s.username })}
                    onChange={(e) => { if (e.target.value !== "") move(s, Number(e.target.value)); }}
                  >
                    <option value="">{t("pacingMove")}</option>
                    {back.length > 0 && <optgroup label={t("pcMoveBack")}>{back.map(option)}</optgroup>}
                    {here && <optgroup label={t("pcMoveAgain")}>{option(here)}</optgroup>}
                    {ahead.length > 0 && <optgroup label={t("pcMoveAhead")}>{ahead.map(option)}</optgroup>}
                  </Select>
                </div>
                {(s.skipped.length > 0 || s.released_to) && (
                  <div className="vc-pacing-student__more">
                    {s.skipped.length > 0 && (
                      <span><FastForward aria-hidden="true" />{t("pacingSkipped", { labels: s.skipped.join(", ") })}</span>
                    )}
                    {s.released_to ? (
                      <span><LockOpen aria-hidden="true" />{t("pacingOpenForThem", { label: label(s.released_to) })}</span>
                    ) : null}
                  </div>
                )}
                {s.flags.map((f) => (
                  <details key={f.step} className="vc-pacing-flag">
                    <summary>{t("pacingFlag", { label: f.label })} {f.missing.map((m, i) => (
                      <span key={i}>{i > 0 && ", "}<bdi dir="ltr" className="vc-mono">{m}</bdi></span>
                    ))}</summary>
                    <pre dir="ltr" className="vc-pre vc-pre--light vc-pacing-pre">{f.output}</pre>
                  </details>
                ))}
              </li>
            );
          })}
        </ul>
      )}
    </details>
  );
}

/** The quiz questions: edit the wording, approve, and see the class's answers. */
function Quiz({ exerciseId, items, course, pending, onChange, openReq = 0 }: {
  exerciseId: string; items: PacingQuizItem[]; course: PacingCourse; pending: number; onChange: () => void;
  /** Goes up each time the lecturer asks to see the questions: open them and scroll to them. */
  openReq?: number;
}) {
  const { t } = useLang();
  const toast = useToast();
  const confirm = useConfirm();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  // Approving: also ask the students who already finished the step (default yes).
  const [askPast, setAskPast] = useState<Record<string, boolean>>({});
  const [askedNow, setAskedNow] = useState<Record<string, number>>({});
  // Withdrawing: also take it back from the students asked it (default yes).
  const [takeBack, setTakeBack] = useState<Record<string, boolean>>({});
  const [toldNow, setToldNow] = useState<Record<string, number>>({});

  // Open or closed is the lecturer's choice: open at first when a question waits
  // for approval, and opened again only when a question starts waiting.
  const [open, setOpen] = useState(pending > 0);
  const box = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (openReq === 0) return;
    // Open first, so the page is long enough to bring the questions to the top.
    if (box.current) box.current.open = true;
    setOpen(true);
    const id = window.requestAnimationFrame(() => box.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    return () => window.cancelAnimationFrame(id);
  }, [openReq]);
  const pendingKeys = items.filter((q) => !q.approved).map((q) => q.key).join("\n");
  const seenPending = useRef(pendingKeys);
  useEffect(() => {
    const before = new Set(seenPending.current.split("\n"));
    seenPending.current = pendingKeys;
    if (pendingKeys && pendingKeys.split("\n").some((k) => !before.has(k))) setOpen(true);
  }, [pendingKeys]);

  const save = async (q: PacingQuizItem, approved: boolean, askFinished = false, withdrawAsked = false) => {
    setBusyKey(q.key);
    try {
      const r = await api.setQuiz(exerciseId, q.key, approved, drafts[q.key],
                                  askFinished || withdrawAsked ? { courseId: course.course_id } : undefined,
                                  withdrawAsked);
      if (r.asked_now) setAskedNow((m) => ({ ...m, [q.key]: r.asked_now }));
      setToldNow((m) => ({ ...m, [q.key]: r.withdrawn_now ?? 0 }));
      setDrafts((d) => { const next = { ...d }; delete next[q.key]; return next; });
      onChange();
    } catch (e) {
      toast.error(t("pcQuizFailed"), e);
    } finally {
      setBusyKey(null);
    }
  };

  // Withdrawing reaches the students already asked (when ticked): confirm first.
  const withdraw = async (q: PacingQuizItem, asked: number, takeThem: boolean) => {
    const tell = asked > 0 && takeThem;
    const body = asked === 0 ? t("pcWithdrawBodyNone", { label: q.label })
      : tell ? t("pcWithdrawBodyTell", { label: q.label, n: asked })
      : t("pcWithdrawBodyKeep", { label: q.label, n: asked });
    if (!(await confirm({
      title: t("pcWithdrawTitle", { label: q.label }), body, confirmLabel: t("pacingUnapprove"), danger: tell,
    }))) return;
    await save(q, false, false, tell);
  };

  return (
    <details ref={box} className="vc-pacing-block" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <ChevronDown className="vc-pacing-chev" aria-hidden="true" />
        <span>{t("pacingQuiz")}</span>
        <span className="vc-badge vc-badge--count">{items.length}</span>
        {pending > 0 && (
          <span className="vc-badge vc-badge--warning"><Hourglass aria-hidden="true" />{t("pacingQuizPending", { n: pending })}</span>
        )}
      </summary>
      <p className="vc-pacing__hint">{t("pacingQuizHint")}</p>
      {items.length === 0 && (
        <EmptyState icon={<HelpCircle />} title={t("pacingNoQuiz")}>{t("pcNoQuizText")}</EmptyState>
      )}
      {items.map((q) => {
        const draft = drafts[q.key];
        const edited = draft !== undefined && draft.trim() !== q.body;
        const answers = course.students.flatMap((s) =>
          s.quiz.filter((a) => a.key === q.key && a.status === "answered").map((a) => ({ user: s.username, ...a })));
        const graded = answers.filter((a) => a.grade != null);
        const avg = graded.length ? (graded.reduce((x, a) => x + (a.grade ?? 0), 0) / graded.length).toFixed(1) : "–";
        const busy = busyKey === q.key;
        const missed = course.quiz_missed?.[q.key] ?? 0;
        const askThem = askPast[q.key] ?? true;
        // Students of this course who were asked it and haven't had it taken back.
        const asked = course.students.filter((s) =>
          s.quiz.some((a) => a.key === q.key && (a.status === "pending" || a.status === "answered"))).length;
        const takeThem = takeBack[q.key] ?? true;
        return (
          <article key={q.key} className="vc-pacing-quiz" data-approved={q.approved}>
            <div className="vc-pacing-item__head">
              <span className="vc-pacing-item__step">{q.label}</span>
              {q.approved
                ? <span className="vc-badge vc-badge--success"><Check aria-hidden="true" />{t("pacingApproved")}</span>
                : <span className="vc-badge vc-badge--warning"><Hourglass aria-hidden="true" />{t("pcNotApproved")}</span>}
              {answers.length === 0 && <span className="vc-pacing-item__meta u-push">{t("pacingNoAnswers")}</span>}
            </div>
            <Textarea
              value={draft ?? q.body} rows={2} disabled={busy} aria-label={t("pcQuizWordingAria", { label: q.label })}
              onChange={(e) => setDrafts((d) => ({ ...d, [q.key]: e.target.value }))}
            />
            {q.answer && (
              <div className="u-mt-8">
                <span className="vc-pacing-compare__label">{t("pacingModelAnswer")}</span>
                <div className="vc-pacing-text vc-pacing-text--private" dir={textDir(q.answer)}>{q.answer}</div>
              </div>
            )}
            <div className="vc-pacing-actions">
              {!q.approved && missed > 0 && (
                <Checkbox checked={askThem} disabled={busy} onChange={(v) => setAskPast((m) => ({ ...m, [q.key]: v }))}>
                  {t("pacingAskFinished", { n: missed, label: q.label })}
                </Checkbox>
              )}
              {(!q.approved || edited) && (
                <Button variant="success" icon={<Check />} busy={busy} onClick={() => save(q, true, missed > 0 && askThem)}>
                  {edited ? t("pacingApproveEdited") : t("pacingApprove")}
                </Button>
              )}
              {q.approved && !edited && missed > 0 && (
                <Button variant="brand-soft" icon={<HelpCircle />} disabled={busy} onClick={() => save(q, true, true)}>
                  {t("pacingAskFinishedNow", { n: missed, label: q.label })}
                </Button>
              )}
              {q.approved && asked > 0 && (
                <Checkbox checked={takeThem} disabled={busy} onChange={(v) => setTakeBack((m) => ({ ...m, [q.key]: v }))}>
                  {t("pacingWithdrawAsked", { n: asked })}
                </Checkbox>
              )}
              {q.approved && (
                <Button disabled={busy} onClick={() => withdraw(q, asked, takeThem)}>{t("pacingUnapprove")}</Button>
              )}
              {!q.approved && toldNow[q.key] ? (
                <span className="vc-badge vc-badge--danger"><Check aria-hidden="true" />{t("pacingWithdrawnNow", { n: toldNow[q.key] })}</span>
              ) : null}
              {askedNow[q.key] ? (
                <span className="vc-badge vc-badge--success"><Check aria-hidden="true" />{t("pacingAskedNow", { n: askedNow[q.key] })}</span>
              ) : null}
            </div>
            {answers.length > 0 && (
              <details className="vc-pacing-quiz__answers">
                <summary>{t("pacingAnswers", { n: answers.length, avg })}</summary>
                <ul>
                  {answers.map((a) => (
                    <li key={a.id} dir={textDir(a.user, a.answer)}>
                      <span className="u-bold">{a.user}</span>
                      {a.grade != null && <span className="u-muted"> ({a.grade}/2)</span>}
                      {a.review === "waiting" && <span className="u-danger u-bold"> · {t("pacingAnswerWaitingTag")}</span>}
                      {a.review === "returned" && <span className="u-warning"> · {t("pacingAnswerReturnedTag")}</span>}
                      : {a.answer}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </article>
        );
      })}
    </details>
  );
}
