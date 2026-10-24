import { useEffect, useState } from "react";
import { api } from "../api";
import type { AnswerLevel, BankMatch, Lang, PendingReview, RegenModel } from "../types";
import { useLang } from "../i18n";

const LEVELS: { key: AnswerLevel; tint: string }[] = [
  { key: "nudge",  tint: "#e0f2fe" },
  { key: "normal", tint: "#dcfce7" },
  { key: "more",   tint: "#fef3c7" },
  { key: "direct", tint: "#ede9fe" },
];

/** Text of a level in a given language (Hebrew falls back to English if empty). */
function variantText(r: PendingReview, level: AnswerLevel, lang: Lang): string | null {
  if (lang === "he") {
    return r[`variant_${level}_he` as const] ?? r[`variant_${level}` as const];
  }
  return r[`variant_${level}` as const];
}

/** "claude-opus-5-5" -> "Opus 5.5" (other model names are shown as they are). */
export function modelLabel(model: string | null): string {
  if (!model) return "";
  if (!model.startsWith("claude-")) return model;
  const parts = model.slice("claude-".length).split("-");
  const words = parts.filter((p) => !/^\d+$/.test(p));
  const nums = parts.filter((p) => /^\d+$/.test(p) && p.length < 8);
  const name = words.map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
  return nums.length ? `${name} ${nums.join(".")}` : name;
}

/** The bank's answer in the card's language: the normal level if it has one. */
function bankLevels(m: BankMatch): AnswerLevel[] {
  return LEVELS.map((l) => l.key).filter((k) => m.answers[k]);
}

export function ReviewQueue({ exerciseId }: { exerciseId: string | null }) {
  const { t, lang } = useLang();
  const [enabled, setEnabled] = useState(false);
  const [allPending, setPending] = useState<PendingReview[]>([]);
  // Only the exercise the live view follows.
  const pending = allPending.filter((r) => r.exercise_id === exerciseId);
  const elsewhere = allPending.length - pending.length;
  const [busyId, setBusyId] = useState<number | null>(null);
  const [regenModels, setRegenModels] = useState<RegenModel[]>([]);
  // A card being drafted again: which model, and any error.
  const [regen, setRegen] = useState<Record<number, { label: string; error?: string }>>({});
  // Teacher edits, keyed by `${reviewId}:${level}:${lang}` so each language's
  // box edits independently. Separate state so the 2s poll never clobbers them.
  const [edits, setEdits] = useState<Record<string, string>>({});
  // Per-card language to view/send; defaults to the language the student wrote in.
  const [cardLang, setCardLang] = useState<Record<number, Lang>>({});
  // Per-card level shown in the question-bank box.
  const [bankLevel, setBankLevel] = useState<Record<number, AnswerLevel>>({});

  const editKey = (id: number, level: AnswerLevel | "bank", l: Lang) => `${id}:${level}:${l}`;
  const langOf = (r: PendingReview): Lang => cardLang[r.id] ?? r.suggested_lang ?? lang;

  useEffect(() => {
    api.getReviewMode().then((r) => setEnabled(r.enabled)).catch(console.error);
    api.reviewConfig().then((c) => setRegenModels(c.regen_models)).catch(console.error);
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

  const clearEdits = (id: number) =>
    setEdits((e) => {
      const next = { ...e };
      for (const k of Object.keys(next)) if (k.startsWith(`${id}:`)) delete next[k];
      return next;
    });

  const pick = async (id: number, level: AnswerLevel | "bank", l: Lang, text: string) => {
    setBusyId(id);
    try {
      await api.selectReview(id, level, l, text);
      setPending((p) => p.filter((r) => r.id !== id));
      clearEdits(id);
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  const redo = async (r: PendingReview, m: RegenModel) => {
    setRegen((x) => ({ ...x, [r.id]: { label: m.label } }));
    try {
      const fresh = await api.regenerateReview(r.id, m.key);
      setPending((p) => p.map((x) => (x.id === r.id ? fresh : x)));
      clearEdits(r.id);
      setRegen((x) => { const next = { ...x }; delete next[r.id]; return next; });
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e);
      setRegen((x) => ({ ...x, [r.id]: { label: m.label, error } }));
    }
  };

  const box: React.CSSProperties = {
    flex: 1, minHeight: 120, fontSize: 13, lineHeight: 1.4,
    fontFamily: "inherit", resize: "vertical",
    border: "1px solid rgba(0,0,0,0.12)", borderRadius: 4,
    padding: 6, background: "white", color: "#111827",
  };
  const sendBtn = (busy: boolean): React.CSSProperties => ({
    marginTop: 8, padding: "6px 10px", border: "none",
    borderRadius: 4, background: "#111827", color: "white",
    cursor: busy ? "wait" : "pointer",
  });

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
              const l = langOf(r);
              const working = regen[r.id] && !regen[r.id].error;
              const busy = busyId === r.id || !!working;
              const levels = LEVELS.filter(({ key }) => variantText(r, key, l));
              const bank = r.bank_match;
              const bLevels = bank ? bankLevels(bank) : [];
              const bLevel = bankLevel[r.id] ?? (bLevels.includes("normal") ? "normal" : bLevels[0]);
              const bOriginal = bank && bLevel ? bank.answers[bLevel]?.[l] ?? "" : "";
              const bKey = editKey(r.id, "bank", l);
              const bValue = edits[bKey] ?? bOriginal;
              return (
              <div key={r.id} style={{
                border: "1px solid #e5e7eb", borderRadius: 6, padding: 12,
                marginBottom: 10, background: "white",
              }}>
                <div style={{
                  marginBottom: 8, display: "flex", alignItems: "flex-start",
                  justifyContent: "space-between", gap: 12, flexWrap: "wrap",
                }}>
                  <div style={{ minWidth: 0, flex: "1 1 320px" }}>
                    <strong>{r.username}</strong>{" "}
                    <span style={{ color: "#6b7280", fontSize: 12 }}>· {r.created_at}</span>
                    {r.model && (
                      <span style={{ color: "#6b7280", fontSize: 12 }}>
                        {" "}· {t("draftedBy", { m: modelLabel(r.model) })}
                      </span>
                    )}
                    <div style={{ marginTop: 4, color: "#374151", whiteSpace: "pre-wrap" }} dir="auto">{r.question}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    {/* Draft the four answers again with a stronger model. */}
                    {regenModels.map((m) => (
                      <button
                        key={m.key}
                        disabled={busy}
                        onClick={() => redo(r, m)}
                        title={m.model}
                        style={{
                          padding: "3px 8px", borderRadius: 4, fontSize: 12,
                          cursor: busy ? "wait" : "pointer",
                          border: "1px solid #c4b5fd", background: "#f5f3ff", color: "#5b21b6", fontWeight: 600,
                        }}
                      >
                        {t("regenerate", { m: m.label })}
                      </button>
                    ))}
                    {/* Per-card language switch: which language to view & send. */}
                    <span style={{ color: "#6b7280", fontSize: 12, marginInlineStart: 6 }}>{t("answersIn")}:</span>
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

                {regen[r.id] && (
                  <div style={{ fontSize: 13, marginBottom: 8, color: regen[r.id].error ? "#b91c1c" : "#5b21b6" }}>
                    {regen[r.id].error
                      ? t("regenFailed", { e: regen[r.id].error ?? "" })
                      : t("regenerating", { m: regen[r.id].label })}
                  </div>
                )}

                {bank && bLevel && (
                  <div style={{
                    background: "#f0fdfa", border: "1px solid #99f6e4", borderRadius: 6,
                    padding: 10, marginBottom: 8, display: "flex", flexDirection: "column",
                  }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap", marginBottom: 6 }}>
                      <strong style={{ color: "#115e59" }}>{t("fromBank", { p: Math.round(bank.score * 100) })}</strong>
                      <span style={{ fontSize: 12, color: "#134e4a" }} dir="auto">
                        {t("bankQuestion")}: {bank.question}
                      </span>
                      <span style={{ flex: 1 }} />
                      {bLevels.length > 1 && bLevels.map((k) => (
                        <button
                          key={k}
                          onClick={() => setBankLevel((m) => ({ ...m, [r.id]: k }))}
                          style={{
                            padding: "2px 8px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                            border: "1px solid " + (bLevel === k ? "#115e59" : "#99f6e4"),
                            background: bLevel === k ? "#115e59" : "white",
                            color: bLevel === k ? "white" : "#115e59",
                          }}
                        >
                          {t(k)}
                        </button>
                      ))}
                    </div>
                    <textarea
                      value={bValue}
                      dir="auto"
                      onChange={(e) => setEdits((prev) => ({ ...prev, [bKey]: e.target.value }))}
                      spellCheck={false}
                      style={{ ...box, minHeight: 80 }}
                    />
                    <button
                      disabled={busy || !bValue.trim()}
                      onClick={() => pick(r.id, "bank", l, bValue)}
                      style={{ ...sendBtn(busy), alignSelf: "flex-start", background: "#115e59" }}
                    >
                      {busyId === r.id ? t("sending") : t("sendBank")}
                    </button>
                  </div>
                )}

                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
                  {levels.map(({ key, tint }) => {
                    const original = variantText(r, key, l) ?? "";
                    const k = editKey(r.id, key, l);
                    const value = edits[k] ?? original;
                    const editedFlag = edits[k] !== undefined && edits[k] !== original;
                    return (
                    <div key={key} style={{
                      background: tint, padding: 10, borderRadius: 6,
                      display: "flex", flexDirection: "column", opacity: working ? 0.5 : 1,
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
                        style={box}
                      />
                      <button
                        disabled={busy || !value.trim()}
                        onClick={() => pick(r.id, key, l, value)}
                        style={sendBtn(busy)}
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
