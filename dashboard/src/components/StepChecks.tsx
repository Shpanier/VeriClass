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
              <div style={{ marginBottom: 8 }}>
                <strong>{c.username}</strong>
                <span style={{ marginInlineStart: 10, fontWeight: 600, color: "#1d4ed8" }}>
                  {t("stepOf", { n: c.step, total: c.total })}: {c.title}
                </span>
                <span style={{ marginInlineStart: 10, color: "#6b7280", fontSize: 12 }}>· {c.created_at}</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 12, color: "#374151", marginBottom: 4 }}>{t("studentAnswer")}</div>
                  <div dir="auto" style={{ ...box, background: "#f3f4f6", color: "#111827" }}>{c.answer}</div>
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 12, color: "#92400e", marginBottom: 4 }}>{t("expectedAnswer")}</div>
                  <div dir="ltr" style={{ ...box, background: "#fef3c7", color: "#451a03" }}>{c.expected}</div>
                </div>
              </div>
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
