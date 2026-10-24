import { useEffect, useState } from "react";
import { api } from "../api";
import type { StepCheck } from "../types";
import { useLang } from "../i18n";

/** Step-by-step labs: each pair's "Done with step N" answer, next to the
 *  expected values. Approve releases the next step into their chat. */
export function StepChecks({ exerciseId }: { exerciseId: string | null }) {
  const { t } = useLang();
  const [hasSteps, setHasSteps] = useState(false);
  const [allItems, setItems] = useState<StepCheck[]>([]);
  // Only the exercise the live view follows; the rest are counted, not shown.
  const items = allItems.filter((c) => c.exercise_id === exerciseId);
  const elsewhere = allItems.length - items.length;
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    const tick = () =>
      api.pendingStepChecks()
        .then((r) => { setHasSteps(r.has_steps); setItems(r.items); })
        .catch(console.error);
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, []);

  const decide = async (c: StepCheck, action: "approve" | "return") => {
    setBusyId(c.id);
    try {
      await api.decideStepCheck(c.id, action, notes[c.id] ?? "");
      setItems((xs) => xs.filter((x) => x.id !== c.id));
      setNotes((n) => { const next = { ...n }; delete next[c.id]; return next; });
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  if (!hasSteps && allItems.length === 0) return null;

  const box = { padding: 10, borderRadius: 6, whiteSpace: "pre-wrap" as const, fontSize: 13, lineHeight: 1.5 };

  return (
    <section style={{
      border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 24,
      background: items.length ? "#eff6ff" : "#fafafa",
    }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <strong>📋 {t("stepChecks")}{items.length ? ` (${items.length})` : ""}</strong>
        <span style={{ color: "#6b7280", fontSize: 13 }}>{t("stepChecksHint")}</span>
        {elsewhere > 0 && (
          <span style={{ color: "#b45309", fontSize: 13, fontWeight: 600 }}>
            {t("otherExercisesWaiting", { n: elsewhere })}
          </span>
        )}
      </header>

      <div style={{ marginTop: 12 }}>
        {items.length === 0 ? (
          <div style={{ color: "#6b7280", fontStyle: "italic" }}>{t("noStepChecks")}</div>
        ) : items.map((c) => {
          const last = c.step >= c.total;
          const busy = busyId === c.id;
          return (
            <div key={c.id} style={{
              border: "1px solid #e5e7eb", borderRadius: 6, padding: 12,
              marginBottom: 10, background: "white",
            }}>
              <div style={{ marginBottom: 8, display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                <strong>{c.username}</strong>
                <span style={{ fontWeight: 600, color: "#1d4ed8" }}>
                  {t("stepOf", { n: c.step, total: c.total })}: {c.title}
                </span>
                <span style={{ color: "#6b7280", fontSize: 12 }}>· {c.created_at}</span>
                {c.questions != null && c.answered != null && (
                  <span title={t("answeredHint")} style={{
                    fontSize: 12, fontWeight: 700, padding: "1px 8px", borderRadius: 999,
                    background: c.answered >= c.questions ? "#dcfce7" : "#fee2e2",
                    color: c.answered >= c.questions ? "#166534" : "#991b1b",
                  }}>
                    {t("answeredOf", { k: c.answered, n: c.questions })}
                  </span>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 12, color: "#374151", marginBottom: 4 }}>{t("studentAnswer")}</div>
                  <div dir="auto" style={{ ...box, background: "#f3f4f6", color: "#111827" }}>{c.answer}</div>
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 12, color: "#92400e", marginBottom: 4 }}>{t("expectedAnswer")}</div>
                  <div dir="ltr" style={{ ...box, background: "#fef3c7", color: "#451a03" }}>{c.expected}</div>
                </div>
              </div>
              <Evidence c={c} />
              <Attachment c={c} />
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <input
                  value={notes[c.id] ?? ""}
                  onChange={(e) => setNotes((n) => ({ ...n, [c.id]: e.target.value }))}
                  placeholder={t("noteForStudents")}
                  dir="auto"
                  style={{ flex: "1 1 260px", padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13 }}
                />
                <button
                  disabled={busy}
                  onClick={() => decide(c, "approve")}
                  style={{ padding: "6px 12px", border: "none", borderRadius: 4, background: "#15803d", color: "white", cursor: busy ? "wait" : "pointer", fontWeight: 600 }}
                >
                  {last ? t("approveFinish") : t("approveNext", { n: c.step + 1 })}
                </button>
                <button
                  disabled={busy}
                  onClick={() => decide(c, "return")}
                  style={{ padding: "6px 12px", border: "1px solid #d1d5db", borderRadius: 4, background: "white", color: "#111827", cursor: busy ? "wait" : "pointer" }}
                >
                  {t("sendBack")}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

const mono: React.CSSProperties = {
  fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 12, whiteSpace: "pre-wrap",
  overflowWrap: "anywhere", margin: 0,
};

/** The step's evidence rules and the student's last terminal lines. */
function Evidence({ c }: { c: StepCheck }) {
  const { t } = useLang();
  const { rules, recent } = c.evidence ?? { rules: [], recent: [] };
  if (rules.length === 0 && recent.length === 0) return null;
  return (
    <div style={{ marginTop: 10, background: "#0f172a", color: "#e2e8f0", borderRadius: 6, padding: 10 }} dir="ltr">
      <div style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginBottom: 6 }}>{t("terminalEvidence")}</div>
      {rules.map((r, i) => (
        <div key={i} style={{ marginBottom: 6 }}>
          <span style={{ color: r.ok === false ? "#fca5a5" : r.ok ? "#86efac" : "#e2e8f0", fontWeight: 700 }}>
            {r.ok === false ? "✗" : r.ok ? "✓" : "•"} {r.label}
          </span>
          {r.found ? (
            <>
              <pre style={{ ...mono, color: "#93c5fd" }}>$ {r.line}</pre>
              {r.output && <pre style={{ ...mono, color: "#cbd5e1" }}>{r.output}</pre>}
            </>
          ) : (
            <span style={{ color: "#fca5a5", fontSize: 12 }}> · {t("evidenceMissing")}</span>
          )}
        </div>
      ))}
      {recent.length > 0 && (
        <details open={rules.length === 0}>
          <summary style={{ cursor: "pointer", fontSize: 12, color: "#94a3b8" }}>{t("recentLines")}</summary>
          {recent.map((r, i) => (
            <div key={i} style={{ marginTop: 4 }}>
              <pre style={{ ...mono, color: r.allowed ? "#93c5fd" : "#fca5a5" }}>
                $ {r.line}{"  "}
                <span style={{ color: "#64748b" }}>
                  {r.allowed ? `exit ${r.exit_code ?? "?"}` : t("blockedShort")}
                </span>
              </pre>
              {r.output && <pre style={{ ...mono, color: "#cbd5e1" }}>{r.output}</pre>}
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
    <details style={{ marginTop: 10 }}>
      <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600, color: "#1d4ed8" }}>
        {t("attachedCode", { f: filename || "code" })}
      </summary>
      {check && (
        <>
          <div style={{ fontSize: 12, fontWeight: 600, margin: "8px 0 4px" }}>{t("checkOutput")}</div>
          <pre dir="ltr" style={{ ...mono, background: "#f0fdf4", padding: 8, borderRadius: 4 }}>{check}</pre>
        </>
      )}
      {source && (
        <pre dir="ltr" style={{ ...mono, background: "#f8fafc", padding: 8, borderRadius: 4, marginTop: 8, maxHeight: 360, overflow: "auto" }}>
          {source}
        </pre>
      )}
      {out && (
        <>
          <div style={{ fontSize: 12, fontWeight: 600, margin: "8px 0 4px" }}>{t("consoleOutput")}</div>
          <pre dir="ltr" style={{ ...mono, background: "#f8fafc", padding: 8, borderRadius: 4, maxHeight: 240, overflow: "auto" }}>{out}</pre>
        </>
      )}
    </details>
  );
}
