import { useEffect, useState } from "react";
import { api } from "../api";
import type { AnswerLevel, Lang, PendingReview } from "../types";
import { useLang } from "../i18n";

const LEVELS: { key: AnswerLevel; tint: string }[] = [
  { key: "nudge",  tint: "#e0f2fe" },
  { key: "normal", tint: "#dcfce7" },
  { key: "more",   tint: "#fef3c7" },
];

/** Text of a level in a given language (Hebrew falls back to English if empty). */
function variantText(r: PendingReview, level: AnswerLevel, lang: Lang): string {
  if (lang === "he") {
    return r[`variant_${level}_he` as const] ?? r[`variant_${level}` as const];
  }
  return r[`variant_${level}` as const];
}

export function ReviewQueue({ exerciseId }: { exerciseId: string | null }) {
  const { t, lang } = useLang();
  const [enabled, setEnabled] = useState(false);
  const [allPending, setPending] = useState<PendingReview[]>([]);
  // Only the exercise the live view follows.
  const pending = allPending.filter((r) => r.exercise_id === exerciseId);
  const elsewhere = allPending.length - pending.length;
  const [busyId, setBusyId] = useState<number | null>(null);
  // Teacher edits, keyed by `${reviewId}:${level}:${lang}` so each language's
  // box edits independently. Separate state so the 2s poll never clobbers them.
  const [edits, setEdits] = useState<Record<string, string>>({});
  // Per-card language to view/send; defaults to the dashboard language.
  const [cardLang, setCardLang] = useState<Record<number, Lang>>({});

  const editKey = (id: number, level: AnswerLevel, l: Lang) => `${id}:${level}:${l}`;
  const langOf = (id: number): Lang => cardLang[id] ?? lang;

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

  const pick = async (id: number, level: AnswerLevel, l: Lang, text: string) => {
    setBusyId(id);
    try {
      await api.selectReview(id, level, l, text);
      setPending((p) => p.filter((r) => r.id !== id));
      setEdits((e) => {
        const next = { ...e };
        for (const lvl of ["nudge", "normal", "more"] as AnswerLevel[]) {
          delete next[editKey(id, lvl, "en")];
          delete next[editKey(id, lvl, "he")];
        }
        return next;
      });
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
          <strong>🧑‍🏫 {t("reviewMode")}</strong>
          <span style={{ marginInlineStart: 12, color: "#6b7280", fontSize: 13 }}>
            {enabled ? t("reviewOnHint") : t("reviewOffHint")}
          </span>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={enabled} onChange={toggle} />
          <span>{enabled ? t("on") : t("off")}</span>
        </label>
      </header>

      {enabled && (
        <div style={{ marginTop: 12 }}>
          {elsewhere > 0 && (
            <div style={{ color: "#b45309", fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              {t("otherExercisesWaiting", { n: elsewhere })}
            </div>
          )}
          {pending.length === 0 ? (
            <div style={{ color: "#6b7280", fontStyle: "italic" }}>
              {t("noQuestions")}
            </div>
          ) : (
            pending.map((r) => {
              const l = langOf(r.id);
              return (
              <div key={r.id} style={{
                border: "1px solid #e5e7eb", borderRadius: 6, padding: 12,
                marginBottom: 10, background: "white",
              }}>
                <div style={{
                  marginBottom: 8, display: "flex", alignItems: "flex-start",
                  justifyContent: "space-between", gap: 12,
                }}>
                  <div style={{ minWidth: 0 }}>
                    <strong>{r.username}</strong>{" "}
                    <span style={{ color: "#6b7280", fontSize: 12 }}>· {r.created_at}</span>
                    <div style={{ marginTop: 4, color: "#374151" }} dir="auto">{r.question}</div>
                  </div>
                  {/* Per-card language switch: which language to view & send. */}
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <span style={{ color: "#6b7280", fontSize: 12 }}>{t("answersIn")}:</span>
                    {(["en", "he"] as Lang[]).map((opt) => (
                      <button
                        key={opt}
                        onClick={() => setCardLang((m) => ({ ...m, [r.id]: opt }))}
                        style={{
                          padding: "3px 8px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                          border: "1px solid " + (l === opt ? "#111827" : "#d1d5db"),
                          background: l === opt ? "#111827" : "white",
                          color: l === opt ? "white" : "#374151",
                          fontWeight: 600,
                        }}
                      >
                        {opt === "en" ? "EN" : "עב"}
                      </button>
                    ))}
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                  {LEVELS.map(({ key, tint }) => {
                    const original = variantText(r, key, l);
                    const k = editKey(r.id, key, l);
                    const value = edits[k] ?? original;
                    const editedFlag = edits[k] !== undefined && edits[k] !== original;
                    return (
                    <div key={key} style={{
                      background: tint, padding: 10, borderRadius: 6,
                      display: "flex", flexDirection: "column",
                    }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>
                        {t(key)}
                        {editedFlag && (
                          <span style={{ color: "#92400e", fontWeight: 400 }}> · {t("edited")}</span>
                        )}
                      </div>
                      <textarea
                        value={value}
                        dir="auto"
                        onChange={(e) =>
                          setEdits((prev) => ({ ...prev, [k]: e.target.value }))
                        }
                        spellCheck={false}
                        style={{
                          flex: 1, minHeight: 120, fontSize: 13, lineHeight: 1.4,
                          fontFamily: "inherit", resize: "vertical",
                          border: "1px solid rgba(0,0,0,0.12)", borderRadius: 4,
                          padding: 6, background: "white", color: "#111827",
                        }}
                      />
                      <button
                        disabled={busyId === r.id || !value.trim()}
                        onClick={() => pick(r.id, key, l, value)}
                        style={{
                          marginTop: 8, padding: "6px 10px", border: "none",
                          borderRadius: 4, background: "#111827", color: "white",
                          cursor: busyId === r.id ? "wait" : "pointer",
                        }}
                      >
                        {busyId === r.id ? t("sending") : `${t("send")} · ${t(key)}`}
                      </button>
                    </div>
                    );
                  })}
                </div>
              </div>
              );
            })
          )}
        </div>
      )}
    </section>
  );
}
