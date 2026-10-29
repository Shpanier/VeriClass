import { useEffect, useState } from "react";
import { api } from "../api";
import type { PacingCourse, PacingOverview, PacingQuizItem, PacingStep } from "../types";
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

  useEffect(() => {
    setView(null);
    setCourseId(null);
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [exerciseId]);

  if (!view) return null;

  const empty: PacingCourse = {
    course_id: "", name: "", released: view.open_steps, members: null, students: [], done: {}, here: {},
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

/** "Back to step…": pick a step (1 = the beginning), then confirm. */
function ResetPicker({ steps, upTo, prompt, who, small, onReset }: {
  steps: PacingStep[]; upTo: number; prompt: string; who: string; small?: boolean;
  onReset: (n: number) => Promise<void>;
}) {
  const { t } = useLang();
  const [n, setN] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const options = steps.filter((s) => s.n <= upTo);
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
        {options.map((s) => <option key={s.n} value={s.n}>{s.label} · {s.title}</option>)}
      </select>
    );
  }
  const label = steps[n - 1]?.label ?? String(n);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: fs,
                   background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 4, padding: "2px 6px" }}>
      {t("pacingResetConfirm", { who, label })}
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
  const items = course.students.flatMap((s) => s.waiting.map((w) => ({ s, w })));
  if (items.length === 0) return null;

  const letThrough = async (sessionId: string, step: number) => {
    setBusy(sessionId);
    try {
      await api.letThrough(exerciseId, sessionId, step);
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
              <button disabled={busy === s.session_id} onClick={() => letThrough(s.session_id, w.step)} style={{
                padding: "4px 12px", border: "none", borderRadius: 4, background: "#15803d", color: "white",
                fontWeight: 600, cursor: busy === s.session_id ? "wait" : "pointer",
              }}>
                {t("pacingLetThrough")}
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
  return (
    <details style={{ marginTop: 14 }} open={rows.length > 0 && rows.length <= 40}>
      <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 14 }}>
        {t("pacingStudents")} ({rows.length})
        {quizzing > 0 && <span style={{ color: "#b45309", fontWeight: 600 }}> · {t("pacingQuizWaiting", { n: quizzing })}</span>}
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
                <span style={{ flex: 1 }} />
                {s.current > 1 && (
                  <ResetPicker
                    steps={steps}
                    upTo={Math.min(total, s.current)}
                    prompt={t("pacingReset")}
                    who={s.username}
                    small
                    onReset={async (n) => { await api.resetSession(s.session_id, n); onChange(); }}
                  />
                )}
              </div>
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

  const save = async (q: PacingQuizItem, approved: boolean) => {
    setBusyKey(q.key);
    try {
      await api.setQuiz(exerciseId, q.key, approved, drafts[q.key]);
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
                <button disabled={busy} onClick={() => save(q, true)} style={{
                  padding: "4px 10px", border: "none", borderRadius: 4, background: "#15803d", color: "white",
                  fontWeight: 600, cursor: busy ? "wait" : "pointer",
                }}>
                  {edited ? t("pacingApproveEdited") : t("pacingApprove")}
                </button>
              )}
              {q.approved && (
                <button disabled={busy} onClick={() => save(q, false)} style={{
                  padding: "4px 10px", border: "1px solid #d1d5db", borderRadius: 4, background: "white", cursor: busy ? "wait" : "pointer",
                }}>
                  {t("pacingUnapprove")}
                </button>
              )}
            </div>
            {answers.length > 0 && (
              <details style={{ marginTop: 6 }}>
                <summary style={{ cursor: "pointer", fontSize: 12, color: "#374151" }}>{t("pacingAnswers", { n: answers.length, avg })}</summary>
                {answers.map((a, i) => (
                  <div key={i} dir="auto" style={{ fontSize: 12, padding: "3px 0", borderBottom: "1px solid #f3f4f6" }}>
                    <strong>{a.user}</strong> {a.grade != null && <span style={{ color: "#6b7280" }}>({a.grade}/2)</span>}: {a.answer}
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
