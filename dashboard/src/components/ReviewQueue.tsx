import { useEffect, useState } from "react";
import { api } from "../api";
import type { AnswerLevel, PendingReview } from "../types";

const LEVELS: { key: AnswerLevel; label: string; tint: string }[] = [
  { key: "nudge",  label: "Nudge",       tint: "#e0f2fe" },
  { key: "normal", label: "Normal",      tint: "#dcfce7" },
  { key: "more",   label: "Normal + more", tint: "#fef3c7" },
];

export function ReviewQueue() {
  const [enabled, setEnabled] = useState(false);
  const [pending, setPending] = useState<PendingReview[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    api.getReviewMode().then((r) => setEnabled(r.enabled)).catch(console.error);
  }, []);

  useEffect(() => {
    if (!enabled) {
      setPending([]);
      return;
    }
    const tick = () => api.pendingReviews().then(setPending).catch(console.error);
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, [enabled]);

  const toggle = async () => {
    const next = !enabled;
    setEnabled(next);
    try { await api.setReviewMode(next); }
    catch (e) { console.error(e); setEnabled(!next); }
  };

  const pick = async (id: number, level: AnswerLevel) => {
    setBusyId(id);
    try {
      await api.selectReview(id, level);
      setPending((p) => p.filter((r) => r.id !== id));
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section style={{
      border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 24,
      background: enabled ? "#fff7ed" : "#fafafa",
    }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <strong>🧑‍🏫 Teacher review mode</strong>
          <span style={{ marginLeft: 12, color: "#6b7280", fontSize: 13 }}>
            {enabled
              ? "Students' questions are held until you pick a variant."
              : "Off — students get answers directly from the LLM."}
          </span>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={enabled} onChange={toggle} />
          <span>{enabled ? "On" : "Off"}</span>
        </label>
      </header>

      {enabled && (
        <div style={{ marginTop: 12 }}>
          {pending.length === 0 ? (
            <div style={{ color: "#6b7280", fontStyle: "italic" }}>
              No questions waiting.
            </div>
          ) : (
            pending.map((r) => (
              <div key={r.id} style={{
                border: "1px solid #e5e7eb", borderRadius: 6, padding: 12,
                marginBottom: 10, background: "white",
              }}>
                <div style={{ marginBottom: 8 }}>
                  <strong>{r.username}</strong>{" "}
                  <span style={{ color: "#6b7280", fontSize: 12 }}>· {r.created_at}</span>
                  <div style={{ marginTop: 4, color: "#374151" }}>{r.question}</div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                  {LEVELS.map(({ key, label, tint }) => (
                    <div key={key} style={{
                      background: tint, padding: 10, borderRadius: 6,
                      display: "flex", flexDirection: "column",
                    }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>{label}</div>
                      <div style={{ flex: 1, fontSize: 13, whiteSpace: "pre-wrap" }}>
                        {r[`variant_${key}` as const]}
                      </div>
                      <button
                        disabled={busyId === r.id}
                        onClick={() => pick(r.id, key)}
                        style={{
                          marginTop: 8, padding: "6px 10px", border: "none",
                          borderRadius: 4, background: "#111827", color: "white",
                          cursor: busyId === r.id ? "wait" : "pointer",
                        }}
                      >
                        {busyId === r.id ? "Sending…" : `Send ${label}`}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
}
