import { useEffect, useState } from "react";
import { api } from "../api";
import type { PacingAnswer, PacingCourse, PacingOverview, PacingQuizItem, PacingStep, PacingStudent } from "../types";
import { useLang } from "../i18n";

/** Class-paced labs (pacing: class): how far the class got, the button that
 *  opens the next step for everyone, and the questions that wait for the
 *  teacher's approval before any student sees them. */
export function PacingPanel({ exerciseId }: { exerciseId: string }) {
  const { t } = useLang();
  const [view, setView] = useState<PacingOverview | null>(null);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.pacing(exerciseId).then(setView).catch(console.error);
  // Answers that wait for the teacher's decision, in every course of this lab.
  const heldNow = view ? view.courses.reduce(
    (n, c) => n + c.students.reduce((k, s) => k + s.quiz.filter((a) => a.review === "waiting").length, 0), 0) : 0;

  // "(2 ✍️) VeriClass": answers waiting for the teacher show in the tab, on any tab of the browser.
  useEffect(() => {
    const base = document.title.replace(/^\(\d+ ✍️\) /, "");
    document.title = heldNow > 0 ? `(${heldNow} ✍️) ${base}` : base;
    return () => { document.title = document.title.replace(/^\(\d+ ✍️\) /, ""); };
  }, [heldNow]);

  useEffect(() => {
    setView(null);
    setCourseId(null);
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [exerciseId]);

  if (!view) return null;

  const empty: PacingCourse = {
    course_id: "", name: "", released: view.open_steps, members: null, students: [], done: {}, here: {}, quiz_missed: {},
  };
  const courses = view.courses.length ? view.courses : [empty];
  // Until the teacher picks one: the course with the most students in the lab.
  const course = courses.find((c) => c.course_id === courseId)
    ?? [...courses].sort((a, b) => b.students.length - a.students.length)[0];
  const rel = course.released;
  const label = (n: number) => view.steps[n - 1]?.label ?? String(n);

  const release = async (n: number) => {
    setBusy(true);
    try {
      await api.releaseSteps(exerciseId, course.course_id, n);
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  };

  const started = course.students.length;
  const waiting = course.students.filter((s) => s.current > rel && s.current <= view.total).length;
  const pendingQuiz = view.quiz.filter((q) => !q.approved).length;

  const btn = (primary: boolean): React.CSSProperties => ({
    padding: "6px 12px", borderRadius: 4, fontWeight: 600, cursor: busy ? "wait" : "pointer",
    border: primary ? "none" : "1px solid #d1d5db",
    background: primary ? "#15803d" : "white", color: primary ? "white" : "#111827",
  });

  return (
    <section style={{
      border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 24, background: "#f0fdf4",
    }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <strong>🚦 {t("pacing")}</strong>
        <span style={{ color: "#6b7280", fontSize: 13 }}>{t("pacingHint", { n: view.open_steps })}</span>
        {courses.length > 1 && (
          <select
            value={course.course_id}
            onChange={(e) => setCourseId(e.target.value)}
            style={{ marginInlineStart: "auto", padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db" }}
          >
            {courses.map((c) => (
              <option key={c.course_id} value={c.course_id}>
                {c.course_id ? (c.name || c.course_id) : t("pacingNoCourse")} ({c.students.length})
              </option>
            ))}
          </select>
        )}
      </header>

      {heldNow > 0 && (
        <AnswerReview exerciseId={exerciseId} courses={view.courses} items={view.quiz} steps={view.steps} onChange={load} />
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "12px 0" }}>
        <span style={{ fontWeight: 700, fontSize: 15 }}>
          {rel >= view.total ? t("pacingAllOpen", { n: view.total })
            : rel === 0 ? t("pacingNoneOpen")
            : t("pacingOpen", { n: rel, label: label(rel) })}
        </span>
        <span style={{ color: "#374151", fontSize: 13 }}>
          · {course.members != null
            ? t("pacingStartedOf", { k: started, n: course.members })
            : t("pacingStarted", { k: started })}
          {waiting > 0 && <> · <strong>{t("pacingFinishedOpen", { k: waiting })}</strong></>}
        </span>
        <span style={{ flex: 1 }} />
        {rel < view.total && (
          <button disabled={busy} onClick={() => release(rel + 1)} style={btn(true)}>
            {t("pacingOpenNext", { label: label(rel + 1) })}
          </button>
        )}
        {/* Any step, the ones open from the start included: "up to A5" stops everyone after A5. */}
        <select
          disabled={busy}
          value=""
          onChange={(e) => e.target.value !== "" && release(Number(e.target.value))}
          style={{ padding: "6px 8px", borderRadius: 4, border: "1px solid #d1d5db" }}
        >
          <option value="">{t("pacingOpenUpTo")}</option>
          {rel > 0 && <option value="0">{t("pacingCloseAll")}</option>}
          {view.steps.filter((s) => s.n !== rel).map((s) => (
            <option key={s.n} value={s.n}>{s.n < rel ? "◀ " : "▶ "}{s.label} · {s.title}</option>
          ))}
        </select>
        {rel > 0 && (
          <button disabled={busy} onClick={() => release(rel - 1)} style={btn(false)}>
            {t("pacingCloseLast", { label: label(rel) })}
          </button>
        )}
        {course.students.length > 0 && (
          <ResetPicker
            steps={view.steps}
            upTo={Math.min(view.total, Math.max(...course.students.map((s) => s.current)))}
            prompt={t("pacingResetAll")}
            who={t("pacingResetEveryone")}
            onReset={async (n) => { await api.resetCourse(exerciseId, course.course_id, n); await load(); }}
          />
        )}
      </div>

      {/* One chip per step: open or closed, how many finished it, how many are on it. */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }} dir="ltr">
        {view.steps.map((s) => {
          const open = s.n <= rel;
          const done = course.done[s.n] ?? 0;
          const here = course.here[s.n] ?? 0;
          return (
            <div
              key={s.n}
              title={t("pacingStepTip", { label: s.label, title: s.title, done, here })}
              style={{
                minWidth: 54, padding: "4px 8px", borderRadius: 6, fontSize: 12, textAlign: "center",
                background: open ? "white" : "#f3f4f6",
                border: open ? "1px solid #10b981" : s.n === rel + 1 ? "1px dashed #15803d" : "1px solid #e5e7eb",
                color: open ? "#065f46" : "#6b7280",
              }}
            >
              <div style={{ fontWeight: 700 }}>{open ? "" : "🔒 "}{s.label}</div>
              <div>
                <span title="finished">{done}✓</span>
                {here > 0 && <span style={{ color: "#1d4ed8", fontWeight: 700 }}> {here}●</span>}
                {s.quiz > s.quiz_approved && (
                  <span title={t("pacingQuizUnapprovedTip", { n: s.quiz - s.quiz_approved })}
                        style={{ color: "#b45309", fontWeight: 700 }}> ❓{s.quiz - s.quiz_approved}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <Review exerciseId={exerciseId} course={course} steps={view.steps} onChange={load} />
      <Students course={course} total={view.total} steps={view.steps} onChange={load} />
      <Quiz exerciseId={exerciseId} items={view.quiz} course={course} pending={pendingQuiz} onChange={load} />
    </section>
  );
}

/** "Back to step…" (the class: steps up to `upTo`) or, for one student
 *  (`current` given), "Move to step…": back, forward, or the step they are on
 *  (start it over). Pick a step, then confirm. */
function ResetPicker({ steps, upTo, current, prompt, who, small, onReset }: {
  steps: PacingStep[]; upTo: number; current?: number; prompt: string; who: string; small?: boolean;
  onReset: (n: number) => Promise<void>;
}) {
  const { t } = useLang();
  const [n, setN] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const options = steps.filter((s) => s.n <= upTo);
  const mark = (k: number) => current == null ? "" : k < current ? "◀ " : k > current ? "▶ " : "↻ ";
  const go = async () => {
    if (n == null) return;
    setBusy(true);
    try {
      await onReset(n);
      setN(null);
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  };
  const fs = small ? 11 : 13;
  if (n == null) {
    return (
      <select value="" onChange={(e) => e.target.value && setN(Number(e.target.value))} title={t("pacingResetHint")}
              style={{ padding: small ? "1px 4px" : "6px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: fs }}>
        <option value="">{prompt}</option>
        {options.map((s) => <option key={s.n} value={s.n}>{mark(s.n)}{s.label} · {s.title}</option>)}
      </select>
    );
  }
  const label = steps[n - 1]?.label ?? String(n);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: fs,
                   background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 4, padding: "2px 6px" }}>
      {current == null || n < current ? t("pacingResetConfirm", { who, label })
        : n > current ? t("pacingMoveForwardConfirm", { who, label })
        : t("pacingMoveAgainConfirm", { who, label })}
      <button disabled={busy} onClick={go} style={{ border: "none", borderRadius: 4, background: "#b91c1c", color: "white",
                                                    fontWeight: 600, padding: "2px 8px", cursor: busy ? "wait" : "pointer", fontSize: fs }}>
        {t("pacingResetYes")}
      </button>
      <button disabled={busy} onClick={() => setN(null)} style={{ border: "1px solid #d1d5db", borderRadius: 4, background: "white",
                                                                 padding: "2px 8px", cursor: "pointer", fontSize: fs }}>
        {t("pacingCancel")}
      </button>
    </span>
  );
}

const mono: React.CSSProperties = {
  fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 11, whiteSpace: "pre-wrap",
  background: "#f8fafc", padding: 6, borderRadius: 4, maxHeight: 260, overflow: "auto", margin: "4px 0 0",
};

/** Outputs that didn't match their step's checks: the student's paste next to
 *  the expected output, and the button that lets the student continue. */
function Review({ exerciseId, course, steps, onChange }: {
  exerciseId: string; course: PacingCourse; steps: PacingStep[]; onChange: () => void;
}) {
  const { t } = useLang();
  const [busy, setBusy] = useState<string | null>(null);
  // The teacher's note to the student when sending an output back, per session.
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
      console.error(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ marginTop: 14, border: "1px solid #f59e0b", borderRadius: 8, background: "#fffbeb", padding: 10 }}>
      <div style={{ fontWeight: 700, fontSize: 14 }}>⏳ {t("pacingReview")} ({items.length})</div>
      <div style={{ color: "#6b7280", fontSize: 12, margin: "2px 0 8px" }}>{t("pacingReviewHint")}</div>
      {items.map(({ s, w }) => {
        const step = steps[w.step - 1];
        return (
          <div key={s.session_id} style={{ background: "white", border: "1px solid #e5e7eb", borderRadius: 6, padding: 8, marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <strong>{s.username}</strong>
              <span style={{ color: "#1d4ed8", fontWeight: 600 }}>{w.label}{step ? ` · ${step.title}` : ""}</span>
              <span style={{ flex: 1 }} />
              <button disabled={busy === s.session_id} onClick={() => decide(s.session_id, w.step, true)} style={{
                padding: "4px 12px", border: "none", borderRadius: 4, background: "#15803d", color: "white",
                fontWeight: 600, cursor: busy === s.session_id ? "wait" : "pointer",
              }}>
                {t("pacingLetThrough")}
              </button>
              <button disabled={busy === s.session_id} onClick={() => decide(s.session_id, w.step, false)} style={{
                padding: "4px 12px", border: "1px solid #fca5a5", borderRadius: 4, background: "#fef2f2", color: "#b91c1c",
                fontWeight: 600, cursor: busy === s.session_id ? "wait" : "pointer",
              }}>
                {t("pacingDecline")}
              </button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8, marginTop: 6 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{t("pacingTheirOutput")}</div>
                <pre dir="ltr" style={mono}>{w.output || "—"}</pre>
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{t("pacingExpected")}</div>
                <pre dir="ltr" style={{ ...mono, background: "#ecfdf5" }}>{step?.expected_output || step?.expected || t("pacingNoExpected")}</pre>
              </div>
            </div>
            {w.missing.length > 0 && (
              <div style={{ fontSize: 12, color: "#b45309", marginTop: 4 }} dir="auto">
                {t("pacingMissing")}: {w.missing.join(" · ")}
              </div>
            )}
            <input value={notes[s.session_id] ?? ""} dir="auto" placeholder={t("pacingDeclineNote")}
                   onChange={(e) => setNotes((m) => ({ ...m, [s.session_id]: e.target.value }))}
                   style={{ width: "100%", boxSizing: "border-box", marginTop: 6, padding: "4px 8px", fontSize: 12,
                            border: "1px solid #d1d5db", borderRadius: 4 }} />
          </div>
        );
      })}
    </div>
  );
}

/** Hebrew text that opens with a Latin word or `code` would be laid out left to right by dir="auto". */
const dirOf = (text: string | null | undefined): "rtl" | "ltr" => (/[\u0590-\u05FF]/.test(text ?? "") ? "rtl" : "ltr");

/** Quiz answers the grader gave too low a grade to move on by itself
 *  (exercise.yaml quiz_review): the student's answer next to the model answer,
 *  and the teacher's decision: continue, or answer again. */
type TextSource = "" | "grader" | "model" | "own";

function AnswerReview({ exerciseId, courses, items, steps, onChange }: {
  exerciseId: string; courses: PacingCourse[]; items: PacingQuizItem[]; steps: PacingStep[]; onChange: () => void;
}) {
  const { t } = useLang();
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
      console.error(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ marginTop: 12, border: "2px solid #dc2626", borderRadius: 8, background: "#fff7ed", padding: 10,
                  boxShadow: "0 2px 10px rgba(220, 38, 38, 0.15)" }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: "#991b1b" }}>✍️ {t("pacingAnswerReview")} ({held.length})</div>
      <div style={{ color: "#6b7280", fontSize: 12, margin: "2px 0 8px" }}>{t("pacingAnswerReviewHint")}</div>
      {held.map(({ s, a, c }) => {
        const item = items.find((q) => q.key === a.key);
        const step = steps[a.step - 1];
        const waiting = busy === a.id;
        return (
          <div key={a.id} style={{ background: "white", border: "1px solid #e5e7eb", borderRadius: 6, padding: 8, marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <strong>{s.username}</strong>
              {many && <span style={{ color: "#6b7280", fontSize: 12 }}>{c.name || c.course_id || t("pacingNoCourse")}</span>}
              <span style={{ color: "#1d4ed8", fontWeight: 600 }}>{step?.label ?? a.step}{step ? ` · ${step.title}` : ""}</span>
              <span style={{ fontWeight: 700, color: a.grade === 0 ? "#b91c1c" : "#b45309" }}>{a.grade ?? "?"}/2</span>
              <span style={{ flex: 1 }} />
              <select value={grades[a.id] ?? ""} disabled={waiting}
                      onChange={(e) => setGrades((m) => ({ ...m, [a.id]: e.target.value }))}
                      style={{ padding: "3px 6px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 12 }}>
                <option value="">{t("pacingGradeKeep", { g: a.grade ?? 0 })}</option>
                {[0, 1, 2].filter((g) => g !== a.grade).map((g) => (
                  <option key={g} value={g}>{t("pacingGradeSet", { g })}</option>
                ))}
              </select>
              <button disabled={waiting} onClick={() => decide(a.id, true)} style={{
                padding: "4px 12px", border: "none", borderRadius: 4, background: "#15803d", color: "white",
                fontWeight: 600, cursor: waiting ? "wait" : "pointer",
              }}>
                {t("pacingLetThrough")}
              </button>
              <button disabled={waiting} onClick={() => decide(a.id, false)} style={{
                padding: "4px 12px", border: "1px solid #fca5a5", borderRadius: 4, background: "#fef2f2", color: "#b91c1c",
                fontWeight: 600, cursor: waiting ? "wait" : "pointer",
              }}>
                {t("pacingAnswerReturn")}
              </button>
            </div>
            <div dir={dirOf(a.body)} style={{ fontSize: 13, margin: "6px 0", whiteSpace: "pre-wrap" }}>❓ {a.body}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{t("pacingTheirAnswer")}</div>
                <div dir={dirOf(a.answer)} style={{ background: "#f8fafc", borderRadius: 4, padding: 6, fontSize: 13, whiteSpace: "pre-wrap", marginTop: 4 }}>
                  {a.answer || "—"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{t("pacingModelAnswer")}</div>
                <div dir={dirOf(item?.answer)} style={{ background: "#fef3c7", color: "#451a03", borderRadius: 4, padding: 6, fontSize: 13, whiteSpace: "pre-wrap", marginTop: 4 }}>
                  {item?.answer || "—"}
                </div>
              </div>
            </div>
            <div dir={dirOf(a.why)} style={{ fontSize: 12, color: "#b45309", marginTop: 4 }}>
              {t("pacingGraderSays", { g: a.grade ?? 0 })}{a.why ? ` — ${a.why}` : ""}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginTop: 8, fontSize: 12 }}>
              <strong>{t("pacingTellThem")}</strong>
              <select value={sources[a.id] ?? ""} disabled={waiting} onChange={(e) => pick(a, e.target.value as TextSource)}
                      style={{ padding: "3px 6px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 12 }}>
                <option value="">{t("pacingTellNothing")}</option>
                {a.why && <option value="grader">{t("pacingTellGrader")}</option>}
                {item?.answer && <option value="model">{t("pacingTellModel")}</option>}
                <option value="own">{t("pacingTellOwn")}</option>
              </select>
              <span style={{ color: "#6b7280" }}>{t("pacingTellHint")}</span>
            </div>
            {(sources[a.id] ?? "") !== "" && (
              <textarea value={notes[a.id] ?? ""} dir={dirOf(notes[a.id] || item?.answer)} rows={3} disabled={waiting}
                        placeholder={t("pacingAnswerNote")}
                        onChange={(e) => setNotes((m) => ({ ...m, [a.id]: e.target.value }))}
                        style={{ width: "100%", boxSizing: "border-box", marginTop: 4, padding: "4px 8px", fontSize: 13,
                                 fontFamily: "inherit", border: "1px solid #d1d5db", borderRadius: 4 }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Each student's step, the furthest behind first, with the steps the teacher
 *  let them past although their output didn't match. */
function Students({ course, total, steps, onChange }: {
  course: PacingCourse; total: number; steps: PacingStep[]; onChange: () => void;
}) {
  const { t } = useLang();
  const rows = [...course.students].sort((a, b) => a.current - b.current || a.username.localeCompare(b.username));
  const quizzing = rows.filter((s) => s.quiz_pending > 0).length;
  const held = rows.filter((s) => s.quiz_review > 0).length;
  return (
    <details style={{ marginTop: 14 }} open={rows.length > 0 && rows.length <= 40}>
      <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 14 }}>
        {t("pacingStudents")} ({rows.length})
        {quizzing > 0 && <span style={{ color: "#b45309", fontWeight: 600 }}> · {t("pacingQuizWaiting", { n: quizzing })}</span>}
        {held > 0 && <span style={{ color: "#b91c1c", fontWeight: 600 }}> · {t("pacingAnswerWaiting", { n: held })}</span>}
      </summary>
      {rows.length === 0 ? (
        <div style={{ color: "#6b7280", fontStyle: "italic", marginTop: 6 }}>{t("pacingNoStudents")}</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 6, marginTop: 8 }}>
          {rows.map((s) => (
            <div key={s.session_id} style={{ background: "white", border: "1px solid #e5e7eb", borderRadius: 6, padding: "6px 10px", fontSize: 13 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <strong>{s.username}</strong>
                <span style={{ color: s.current > total ? "#15803d" : "#1d4ed8", fontWeight: 600 }}>
                  {s.current > total ? t("pacingDone") : t("pacingOnStep", { label: s.current_label ?? "" })}
                </span>
                {s.waiting.length > 0 && <span title={t("pacingReview")}>⏳</span>}
                {s.quiz_pending > 0 && <span title={t("pacingQuiz")}>❓</span>}
                {s.quiz_review > 0 && <span title={t("pacingAnswerReview")}>✍️</span>}
                <span style={{ flex: 1 }} />
                <ResetPicker
                  steps={steps}
                  upTo={total}
                  current={s.current}
                  prompt={t("pacingMove")}
                  who={s.username}
                  small
                  onReset={async (n) => { await api.moveSession(s.session_id, n); onChange(); }}
                />
              </div>
              {(s.skipped.length > 0 || s.released_to) && (
                <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
                  {s.skipped.length > 0 && <>⏩ {t("pacingSkipped", { labels: s.skipped.join(", ") })} </>}
                  {s.released_to ? <>🔓 {t("pacingOpenForThem", { label: steps[s.released_to - 1]?.label ?? String(s.released_to) })}</> : null}
                </div>
              )}
              {s.flags.map((f) => (
                <details key={f.step} style={{ marginTop: 4 }}>
                  <summary style={{ cursor: "pointer", color: "#b45309", fontSize: 12 }}>
                    {t("pacingFlag", { label: f.label })} {f.missing.join(", ")}
                  </summary>
                  <pre dir="ltr" style={mono}>{f.output}</pre>
                </details>
              ))}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

/** The quiz questions: edit the wording, approve, and see the class's answers. */
function Quiz({ exerciseId, items, course, pending, onChange }: {
  exerciseId: string; items: PacingQuizItem[]; course: PacingCourse; pending: number; onChange: () => void;
}) {
  const { t } = useLang();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  // Approving: also ask the students who already finished the step (default yes).
  const [askPast, setAskPast] = useState<Record<string, boolean>>({});
  const [askedNow, setAskedNow] = useState<Record<string, number>>({});
  // Withdrawing: also take it back from the students asked it (default yes).
  const [takeBack, setTakeBack] = useState<Record<string, boolean>>({});
  const [toldNow, setToldNow] = useState<Record<string, number>>({});

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
      console.error(e);
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <details style={{ marginTop: 14 }} open={pending > 0}>
      <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 14 }}>
        {t("pacingQuiz")} ({items.length})
        {pending > 0 && <span style={{ color: "#b45309" }}> · {t("pacingQuizPending", { n: pending })}</span>}
      </summary>
      <div style={{ color: "#6b7280", fontSize: 13, margin: "6px 0 8px" }}>{t("pacingQuizHint")}</div>
      {items.length === 0 && <div style={{ color: "#6b7280", fontStyle: "italic" }}>{t("pacingNoQuiz")}</div>}
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
          <div key={q.key} style={{
            background: "white", borderRadius: 6, padding: 10, marginBottom: 8,
            border: q.approved ? "1px solid #10b981" : "1px solid #f59e0b",
          }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 6 }}>
              <span style={{ fontWeight: 700, color: "#1d4ed8" }}>{q.label}</span>
              {q.approved && <span style={{ color: "#15803d", fontSize: 12, fontWeight: 700 }}>✓ {t("pacingApproved")}</span>}
              <span style={{ flex: 1 }} />
              <span style={{ color: "#6b7280", fontSize: 12 }}>
                {answers.length ? t("pacingAnswers", { n: answers.length, avg }) : t("pacingNoAnswers")}
              </span>
            </div>
            <textarea
              dir="auto"
              value={draft ?? q.body}
              onChange={(e) => setDrafts((d) => ({ ...d, [q.key]: e.target.value }))}
              rows={2}
              style={{ width: "100%", boxSizing: "border-box", padding: 6, border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13, fontFamily: "inherit" }}
            />
            {q.answer && (
              <div dir="auto" style={{ background: "#fef3c7", color: "#451a03", borderRadius: 4, padding: 6, fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}>
                <strong>{t("pacingModelAnswer")}:</strong> {q.answer}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              {(!q.approved || edited) && (
                <button disabled={busy} onClick={() => save(q, true, missed > 0 && askThem)} style={{
                  padding: "4px 10px", border: "none", borderRadius: 4, background: "#15803d", color: "white",
                  fontWeight: 600, cursor: busy ? "wait" : "pointer",
                }}>
                  {edited ? t("pacingApproveEdited") : t("pacingApprove")}
                </button>
              )}
              {q.approved && (
                <button disabled={busy} onClick={() => save(q, false, false, asked > 0 && takeThem)} style={{
                  padding: "4px 10px", border: "1px solid #d1d5db", borderRadius: 4, background: "white", cursor: busy ? "wait" : "pointer",
                }}>
                  {t("pacingUnapprove")}
                </button>
              )}
              {!q.approved && missed > 0 && (
                <label style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: 12, color: "#374151" }}>
                  <input type="checkbox" checked={askThem}
                         onChange={(e) => setAskPast((m) => ({ ...m, [q.key]: e.target.checked }))} />
                  {t("pacingAskFinished", { n: missed, label: q.label })}
                </label>
              )}
              {q.approved && !edited && missed > 0 && (
                <button disabled={busy} onClick={() => save(q, true, true)} style={{
                  padding: "4px 10px", border: "1px solid #f59e0b", borderRadius: 4, background: "#fffbeb",
                  color: "#92400e", fontWeight: 600, cursor: busy ? "wait" : "pointer",
                }}>
                  {t("pacingAskFinishedNow", { n: missed, label: q.label })}
                </button>
              )}
              {q.approved && asked > 0 && (
                <label style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: 12, color: "#374151" }}>
                  <input type="checkbox" checked={takeThem}
                         onChange={(e) => setTakeBack((m) => ({ ...m, [q.key]: e.target.checked }))} />
                  {t("pacingWithdrawAsked", { n: asked })}
                </label>
              )}
              {!q.approved && toldNow[q.key] ? (
                <span style={{ fontSize: 12, color: "#b91c1c", fontWeight: 600 }}>✓ {t("pacingWithdrawnNow", { n: toldNow[q.key] })}</span>
              ) : null}
              {askedNow[q.key] ? (
                <span style={{ fontSize: 12, color: "#15803d", fontWeight: 600 }}>✓ {t("pacingAskedNow", { n: askedNow[q.key] })}</span>
              ) : null}
            </div>
            {answers.length > 0 && (
              <details style={{ marginTop: 6 }}>
                <summary style={{ cursor: "pointer", fontSize: 12, color: "#374151" }}>{t("pacingAnswers", { n: answers.length, avg })}</summary>
                {answers.map((a, i) => (
                  <div key={i} dir="auto" style={{ fontSize: 12, padding: "3px 0", borderBottom: "1px solid #f3f4f6" }}>
                    <strong>{a.user}</strong> {a.grade != null && <span style={{ color: "#6b7280" }}>({a.grade}/2)</span>}
                    {a.review === "waiting" && <span style={{ color: "#b91c1c", fontWeight: 600 }}> · {t("pacingAnswerWaitingTag")}</span>}
                    {a.review === "returned" && <span style={{ color: "#b45309" }}> · {t("pacingAnswerReturnedTag")}</span>}
                    : {a.answer}
                  </div>
                ))}
              </details>
            )}
          </div>
        );
      })}
    </details>
  );
}
