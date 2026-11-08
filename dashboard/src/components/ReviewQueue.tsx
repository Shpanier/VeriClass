import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  AnswerLevel, AnswerSlot, BankMatch, Lang, PendingReview, RegenModel, ReviewAnswer, ReviewChatEntry,
  ReviewConfig, ReviewStepStatus, SelectResult, TranslateTo,
} from "../types";
import { useLang } from "../i18n";

const LEVELS: AnswerLevel[] = ["nudge", "normal", "more", "direct"];
const TINT: Record<AnswerLevel, string> = {
  nudge: "#e0f2fe", normal: "#dcfce7", more: "#fef3c7", direct: "#ede9fe",
};
const BEST_TINT = "#fce7f3";
const OWN_TINT = "#f3f4f6";

type Chosen = AnswerSlot | "bank" | "own";

/** A language code's name in the dashboard's language ("ar" -> "Arabic" / "ערבית"). */
function langName(code: string | null, ui: Lang): string {
  if (!code) return "?";
  try {
    return new Intl.DisplayNames([ui], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Text of an answer in a given language (Hebrew falls back to English if empty, and back). */
function answerText(a: ReviewAnswer, lang: Lang): string {
  return (lang === "he" ? a.text_he || a.text_en : a.text_en || a.text_he) ?? "";
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
  return LEVELS.filter((k) => m.answers[k]);
}

/** Markdown as plain text for a one-line summary: no fences, bold marks, code ticks, headings or quote marks. */
function plain(md: string): string {
  return md
    .split("\n")
    .filter((line) => !line.trim().startsWith("```"))
    .map((line) => line.replace(/^\s*#{1,6}\s+/, "").replace(/^\s*>\s?/, ""))
    .join("\n")
    .replace(/\*\*/g, "")
    .replace(/`/g, "");
}

/** Enough rows to show the whole text without an inner scrollbar (up to a limit). */
function rowsFor(text: string): number {
  const lines = text.split("\n").reduce((n, l) => n + 1 + Math.floor(l.length / 140), 0);
  return Math.min(24, Math.max(3, lines + 1));
}

/** The step's status on the card, and its colour. */
const STEP_STATUS: Record<ReviewStepStatus, { key: "reviewStepOpen" | "reviewStepWaitingTeacher" | "reviewStepWaitingReview"
  | "reviewStepQuiz" | "reviewStepWaitingCheck" | "reviewStepNotStarted" | "reviewStepFinished"; color: string }> = {
  open: { key: "reviewStepOpen", color: "#15803d" },
  waiting_teacher: { key: "reviewStepWaitingTeacher", color: "#b45309" },
  waiting_review: { key: "reviewStepWaitingReview", color: "#b91c1c" },
  quiz: { key: "reviewStepQuiz", color: "#6d28d9" },
  waiting_check: { key: "reviewStepWaitingCheck", color: "#b45309" },
  not_started: { key: "reviewStepNotStarted", color: "#6b7280" },
  finished: { key: "reviewStepFinished", color: "#15803d" },
};

/** An icon and a label key for a chat entry before the question, by who wrote it and what it is. */
function entryTag(e: ReviewChatEntry): { icon: string; key: "reviewKindStudent" | "reviewKindOutput" | "reviewKindAnswer"
  | "reviewKindStep" | "reviewKindResult" | "reviewKindQuiz" | "reviewKindBrief" | "reviewKindNote" | "reviewKindReturned"
  | "reviewKindReset" | "reviewKindTutor" } {
  if (e.author === "student") {
    if (e.kind === "output") return { icon: "📋", key: "reviewKindOutput" };
    if (e.kind === "answer") return { icon: "✍️", key: "reviewKindAnswer" };
    return { icon: "🧑‍🎓", key: "reviewKindStudent" };
  }
  switch (e.kind) {
    case "step": return { icon: "📘", key: "reviewKindStep" };
    case "result": return { icon: "✅", key: "reviewKindResult" };
    case "quiz": return { icon: "❓", key: "reviewKindQuiz" };
    case "brief": return { icon: "📖", key: "reviewKindBrief" };
    case "note": return { icon: "🧑‍🏫", key: "reviewKindNote" };
    case "returned": return { icon: "↩️", key: "reviewKindReturned" };
    case "reset": return { icon: "⏮", key: "reviewKindReset" };
    default: return { icon: "🤖", key: "reviewKindTutor" };
  }
}

export function ReviewQueue({ exerciseId, onViewChat }: {
  exerciseId: string | null;
  /** Open the student's whole chat (the dashboard's chat view) for a card. */
  onViewChat?: (r: PendingReview) => void;
}) {
  const { t, lang } = useLang();
  const [enabled, setEnabled] = useState(false);
  const [allPending, setPending] = useState<PendingReview[]>([]);
  // Only the exercise the live view follows.
  const pending = allPending.filter((r) => r.exercise_id === exerciseId);
  const elsewhere = allPending.length - pending.length;
  const [busyId, setBusyId] = useState<number | null>(null);
  const [cfg, setCfg] = useState<ReviewConfig | null>(null);
  // A card being drafted again and failing.
  const [regenError, setRegenError] = useState<Record<number, string>>({});
  // Teacher edits, keyed by `${reviewId}:${slot}:${lang}` so each language's
  // box edits independently. Separate state so the 2s poll never clobbers them.
  const [edits, setEdits] = useState<Record<string, string>>({});
  // Per-card language to view/send; defaults to the language the student wrote in.
  const [cardLang, setCardLang] = useState<Record<number, Lang>>({});
  // Per-card level shown in the question-bank box.
  const [bankLevel, setBankLevel] = useState<Record<number, AnswerLevel>>({});
  // Per-card "save to the question bank" (default from the settings).
  const [saveBank, setSaveBank] = useState<Record<number, boolean>>({});
  // "Send to all students": the row waiting for a yes, with how many it reaches.
  const [confirmAll, setConfirmAll] = useState<{ id: number; key: string; count: number } | null>(null);
  // Deleting: tell the student (per card, default yes), and the "delete stale" confirmation.
  const [notify, setNotify] = useState<Record<number, boolean>>({});
  const [confirmStale, setConfirmStale] = useState(false);
  // Chat entries before the question shown whole (default: cut to two lines), keyed by `${reviewId}:${index}`.
  const [openEntry, setOpenEntry] = useState<Record<string, boolean>>({});
  // What the last send did ("sent to 12 students"), shown for a few seconds.
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const stale = allPending.filter((r) => !r.waiting).length;

  const say = (text: string, error = false) => {
    setNotice({ text, error });
    setTimeout(() => setNotice((n) => (n && n.text === text ? null : n)), error ? 15000 : 8000);
  };

  const remove = async (r: PendingReview) => {
    setBusyId(r.id);
    try {
      await api.deleteReview(r.id, notify[r.id] ?? !r.looks_like_noise);
      setPending((p) => p.filter((x) => x.id !== r.id));
      clearEdits(r.id);
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  const removeStale = async () => {
    try {
      await api.deleteStaleReviews(false);
      setPending((p) => p.filter((x) => x.waiting));
    } catch (e) {
      console.error(e);
    } finally {
      setConfirmStale(false);
    }
  };

  const editKey = (id: number, chosen: Chosen, l: Lang) => `${id}:${chosen}:${l}`;
  const langOf = (r: PendingReview): Lang => cardLang[r.id] ?? r.suggested_lang ?? lang;

  useEffect(() => {
    api.getReviewMode().then((r) => setEnabled(r.enabled)).catch(console.error);
    api.reviewConfig().then(setCfg).catch(console.error);
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

  const changeConfig = (change: Parameters<typeof api.setReviewConfig>[0]) =>
    api.setReviewConfig(change).then(setCfg).catch(console.error);

  const clearEdits = (id: number) =>
    setEdits((e) => {
      const next = { ...e };
      for (const k of Object.keys(next)) if (k.startsWith(`${id}:`)) delete next[k];
      return next;
    });

  const outcome = (res: SelectResult): { text: string; error: boolean } => {
    const parts = [res.delivered === "later" ? t("reviewNotWaiting").split(":")[0] : t("send")];
    if (res.saved_to_bank) parts.push(t("reviewSaved"));
    if (res.sent_to_class) parts.push(t("reviewSentAll", { n: res.sent_to_class }));
    if (res.bank_error) return { text: t("reviewBankFailed", { e: res.bank_error }), error: true };
    if (res.class_error) return { text: t("reviewClassFailed", { e: res.class_error }), error: true };
    return { text: "✓ " + parts.join(" · "), error: false };
  };

  const pick = async (r: PendingReview, chosen: Chosen, l: Lang, text: string, toClass = false,
                      level?: AnswerLevel) => {
    setBusyId(r.id);
    setConfirmAll(null);
    try {
      const res = await api.selectReview(r.id, chosen, l, text, {
        save_to_bank: saveBank[r.id] ?? cfg?.save_to_bank ?? true,
        send_to_class: toClass,
        ...(level ? { level } : {}),
      });
      setPending((p) => p.filter((x) => x.id !== r.id));
      clearEdits(r.id);
      const o = outcome(res);
      say(o.text, o.error);
    } catch (e) {
      say(t("reviewSendFailed", { e: e instanceof Error ? e.message : String(e) }), true);
    } finally {
      setBusyId(null);
    }
  };

  const askAll = async (r: PendingReview, key: string) => {
    try {
      const who = await api.broadcastRecipients(r.exercise_id ?? "", r.course_id);
      setConfirmAll({ id: r.id, key, count: who.count });
    } catch (e) {
      console.error(e);
      setConfirmAll({ id: r.id, key, count: 0 });
    }
  };

  const redo = async (r: PendingReview, m?: RegenModel, slots?: AnswerSlot[]) => {
    setRegenError((x) => { const next = { ...x }; delete next[r.id]; return next; });
    try {
      const fresh = await api.regenerateReview(r.id, m?.key, slots);
      setPending((p) => p.map((x) => (x.id === r.id ? fresh : x)));
    } catch (e) {
      setRegenError((x) => ({ ...x, [r.id]: e instanceof Error ? e.message : String(e) }));
    }
  };

  const box: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", fontSize: 14, lineHeight: 1.5,
    fontFamily: "inherit", resize: "vertical",
    border: "1px solid rgba(0,0,0,0.12)", borderRadius: 4,
    padding: 8, background: "white", color: "#111827",
  };
  const sendBtn = (busy: boolean, color = "#111827"): React.CSSProperties => ({
    padding: "6px 12px", border: "none", borderRadius: 4, background: color, color: "white",
    fontWeight: 600, cursor: busy ? "wait" : "pointer",
  });
  const lightBtn = (busy: boolean): React.CSSProperties => ({
    padding: "6px 12px", borderRadius: 4, border: "1px solid #f97316", background: "#fff7ed",
    color: "#c2410c", fontWeight: 600, cursor: busy ? "wait" : "pointer",
  });

  /** One answer, a full-width row: who wrote it, the text to edit, and the ways to send it. */
  const answerRow = (r: PendingReview, chosen: Chosen, l: Lang, head: React.ReactNode, original: string,
                     tint: string, busy: boolean, placeholder?: string, level?: AnswerLevel) => {
    const k = editKey(r.id, chosen, l);
    const value = edits[k] ?? original;
    const editedFlag = edits[k] !== undefined && edits[k] !== original;
    const confirming = confirmAll && confirmAll.id === r.id && confirmAll.key === k;
    const save = saveBank[r.id] ?? cfg?.save_to_bank ?? true;
    return (
      <div key={k} style={{ background: tint, padding: "8px 10px", borderRadius: 6, marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          {head}
          {editedFlag && <span style={{ color: "#92400e", fontSize: 12 }}>· {t("edited")}</span>}
        </div>
        <textarea
          value={value}
          dir="auto"
          placeholder={placeholder}
          rows={rowsFor(value)}
          onChange={(e) => setEdits((prev) => ({ ...prev, [k]: e.target.value }))}
          spellCheck={false}
          style={box}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
          <button disabled={busy || !value.trim()} onClick={() => pick(r, chosen, l, value, false, level)} style={sendBtn(busy)}>
            {busyId === r.id ? t("sending") : t("send")}
          </button>
          <button disabled={busy || !value.trim()} onClick={() => askAll(r, k)} style={lightBtn(busy)}>
            {t("reviewSendAll")}
          </button>
          <label style={{ fontSize: 12, color: "#374151", display: "inline-flex", gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={save}
                   onChange={(e) => setSaveBank((m) => ({ ...m, [r.id]: e.target.checked }))} />
            📚 {t("reviewSaveToBank")}
          </label>
        </div>
        {confirming && (
          <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
                        background: "#fff7ed", border: "1px solid #fdba74", borderRadius: 4, padding: "4px 8px",
                        fontSize: 13 }}>
            <span>{confirmAll.count > 0 ? t("reviewSendAllConfirm", { n: confirmAll.count }) : t("reviewSendAllNone")}</span>
            <button onClick={() => pick(r, chosen, l, value, true, level)} style={sendBtn(busy, "#c2410c")}>
              {t("reviewSendAll")}
            </button>
            <button onClick={() => setConfirmAll(null)} style={{ border: "1px solid #d1d5db", borderRadius: 4,
                                                                 background: "white", padding: "4px 8px", cursor: "pointer" }}>
              {t("reviewCancel")}
            </button>
          </div>
        )}
      </div>
    );
  };

  const best = cfg?.best_answer;

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
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", fontSize: 13,
                        color: "#374151", marginBottom: 8 }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              🌐 {t("reviewTranslateTo")}
              <select value={cfg?.translate_to ?? "he"}
                      onChange={(e) => changeConfig({ translate_to: e.target.value as TranslateTo })}>
                <option value="he">{t("reviewTranslateHe")}</option>
                <option value="en">{t("reviewTranslateEn")}</option>
                <option value="off">{t("reviewTranslateOff")}</option>
              </select>
            </label>
            {best && (best.available ? (
              <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={best.enabled}
                       onChange={(e) => changeConfig({ best_answer: e.target.checked })} />
                ✨ {t("reviewBest", { m: best.label ?? modelLabel(best.model) })}
                {" "}{t("reviewBestLevel")}{" "}
                <select value={best.level} disabled={!best.enabled}
                        onChange={(e) => changeConfig({ best_level: e.target.value as AnswerLevel })}>
                  {LEVELS.map((k) => <option key={k} value={k}>{t(k)}</option>)}
                </select>
              </label>
            ) : (
              <span style={{ color: "#9ca3af" }}>✨ {t("reviewBestOff", { m: best.label ?? "Opus" })}</span>
            ))}
            {cfg && (
              <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={cfg.save_to_bank}
                       onChange={(e) => changeConfig({ save_to_bank: e.target.checked })} />
                📚 {t("reviewSaveDefault")}
              </label>
            )}
          </div>
          {notice && (
            <div style={{ marginBottom: 8, fontSize: 13, fontWeight: 600, padding: "4px 8px", borderRadius: 4,
                          background: notice.error ? "#fef2f2" : "#ecfdf5",
                          color: notice.error ? "#b91c1c" : "#047857" }}>
              {notice.text}
            </div>
          )}
          {elsewhere > 0 && (
            <div style={{ color: "#b45309", fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              {t("otherExercisesWaiting", { n: elsewhere })}
            </div>
          )}
          {stale > 0 && (
            <div style={{ marginBottom: 8, fontSize: 13 }}>
              {confirmStale ? (
                <span style={{ display: "inline-flex", gap: 8, alignItems: "center", background: "#fef2f2",
                               border: "1px solid #fca5a5", borderRadius: 4, padding: "3px 8px" }}>
                  {t("reviewDeleteStaleConfirm", { n: stale })}
                  <button onClick={removeStale} style={{ border: "none", borderRadius: 4, background: "#b91c1c",
                                                         color: "white", fontWeight: 600, padding: "2px 8px", cursor: "pointer" }}>
                    {t("reviewYes")}
                  </button>
                  <button onClick={() => setConfirmStale(false)} style={{ border: "1px solid #d1d5db", borderRadius: 4,
                                                                         background: "white", padding: "2px 8px", cursor: "pointer" }}>
                    {t("reviewCancel")}
                  </button>
                </span>
              ) : (
                <button onClick={() => setConfirmStale(true)} style={{ border: "1px solid #d1d5db", borderRadius: 4,
                                                                      background: "white", padding: "3px 10px", cursor: "pointer" }}>
                  {t("reviewDeleteStale", { n: stale })}
                </button>
              )}
            </div>
          )}
          {pending.length === 0 ? (
            <div style={{ color: "#6b7280", fontStyle: "italic" }}>
              {t("noQuestions")}
            </div>
          ) : (
            pending.map((r) => {
              const l = langOf(r);
              const busy = busyId === r.id;
              const ready = r.answers.filter((a) => a.status === "ready");
              const failed = r.answers.filter((a) => a.status === "failed");
              const bank = r.bank_match;
              const bLevels = bank ? bankLevels(bank) : [];
              const bLevel = bankLevel[r.id] ?? (bLevels.includes("normal") ? "normal" : bLevels[0]);
              const bOriginal = bank && bLevel ? bank.answers[bLevel]?.[l] ?? "" : "";
              const draftingList = r.drafting.map((d) =>
                d.slot === "best" ? `✨ ${d.label ?? modelLabel(d.model)}` : `${t(d.level)} (${d.label ?? modelLabel(d.model)})`
              ).join(", ");
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
                    <span style={{ color: "#6b7280", fontSize: 12 }}>· {r.created_at}</span>{" "}
                    <span title={r.waiting ? undefined : t("reviewNotWaiting")} style={{
                      fontSize: 12, fontWeight: 600, color: r.waiting ? "#15803d" : "#6b7280",
                    }}>
                      · {r.waiting ? t("reviewWaitingNow") : t("reviewNotWaiting").split(":")[0]}
                    </span>
                    {r.looks_like_noise && (
                      <span style={{ marginInlineStart: 6, fontSize: 11, fontWeight: 700, color: "#b91c1c",
                                     background: "#fee2e2", borderRadius: 4, padding: "1px 6px" }}>
                        {t("reviewNoise")}
                      </span>
                    )}
                    <div style={{ marginTop: 4, color: "#111827", fontSize: 15, whiteSpace: "pre-wrap" }} dir="auto">
                      {r.question}
                    </div>
                    {r.question_translation && (
                      <div style={{ marginTop: 6, padding: "6px 8px", borderRadius: 4, background: "#eef2ff",
                                    border: "1px solid #c7d2fe" }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#4338ca", marginBottom: 2 }}>
                          🌐 {t("reviewTranslated", { from: langName(r.question_lang, lang),
                                                       to: langName(r.translated_to, lang) })}
                        </div>
                        <div style={{ color: "#111827", whiteSpace: "pre-wrap" }} dir="auto">{r.question_translation}</div>
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    {/* Draft the four answers again with a stronger model. */}
                    {(cfg?.regen_models ?? []).map((m) => (
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
                    {/* Delete: sent by mistake, or no longer relevant. */}
                    <span style={{ display: "inline-flex", gap: 4, alignItems: "center", marginInlineStart: 6 }}>
                      <button disabled={busy} onClick={() => remove(r)} style={{
                        padding: "3px 8px", borderRadius: 4, fontSize: 12, cursor: busy ? "wait" : "pointer",
                        border: "1px solid #fca5a5", background: "#fef2f2", color: "#b91c1c", fontWeight: 600,
                      }}>
                        {t("reviewDelete")}
                      </button>
                      <label style={{ fontSize: 11, color: "#6b7280", display: "inline-flex", gap: 3, alignItems: "center" }}>
                        <input type="checkbox" checked={notify[r.id] ?? !r.looks_like_noise}
                               onChange={(e) => setNotify((m) => ({ ...m, [r.id]: e.target.checked }))} />
                        {t("reviewDeleteNotify")}
                      </label>
                    </span>
                  </div>
                </div>

                  {/* Where the student is, and what the chat showed just before the question. */}
                  <div style={{ marginBottom: 8, padding: "6px 10px", borderRadius: 4, background: "#f9fafb",
                                border: "1px solid #e5e7eb", fontSize: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      {r.step ? (
                        <span style={{ fontWeight: 600, color: "#1f2937" }} dir="auto">
                          📍 {t("reviewStep", { label: r.step.label, total: r.step.total, title: r.step.title })}
                          <span style={{ fontWeight: 500, color: STEP_STATUS[r.step.status].color }}>
                            {" "}· {t(STEP_STATUS[r.step.status].key)}
                          </span>
                        </span>
                      ) : (
                        <span style={{ color: "#6b7280" }}>📍 {t("reviewNoSteps")}</span>
                      )}
                      {onViewChat && (
                        <button onClick={() => onViewChat(r)} style={{
                          padding: "1px 8px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                          border: "1px solid #d1d5db", background: "white", color: "#374151",
                        }}>
                          {t("reviewFullChat")}
                        </button>
                      )}
                    </div>
                    {r.before.entries.length > 0 ? (
                      <div style={{ marginTop: 4 }}>
                        <div style={{ color: "#6b7280", marginBottom: 2 }}>{t("reviewBefore")}</div>
                        {r.before.entries.map((e, i) => {
                          const key = `${r.id}:${i}`;
                          const open = !!openEntry[key];
                          const tag = entryTag(e);
                          return (
                            <div key={key} title={open ? undefined : t("reviewEntryExpand")}
                                 onClick={() => setOpenEntry((m) => ({ ...m, [key]: !open }))}
                                 style={{ display: "flex", gap: 6, padding: "2px 0", cursor: "pointer",
                                          borderTop: i ? "1px dashed #e5e7eb" : undefined }}>
                              <span style={{ flex: "0 0 auto", color: "#6b7280", whiteSpace: "nowrap" }}>
                                {tag.icon} {t(tag.key)}{e.step != null && e.kind === "step" ? ` ${e.step}` : ""}
                              </span>
                              <span dir="auto" style={{
                                flex: "1 1 auto", minWidth: 0, color: "#374151", whiteSpace: "pre-wrap",
                                ...(open ? {} : { display: "-webkit-box", WebkitLineClamp: 2,
                                                  WebkitBoxOrient: "vertical", overflow: "hidden" }),
                              }}>
                                {plain(e.content)}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div style={{ marginTop: 4, color: "#6b7280" }}>{t("reviewNoBefore")}</div>
                    )}
                  </div>

                {regenError[r.id] && (
                  <div style={{ fontSize: 13, marginBottom: 8, color: "#b91c1c" }}>
                    {t("regenFailed", { e: regenError[r.id] })}
                  </div>
                )}

                {bank && bLevel && answerRow(r, "bank", l, (
                  <>
                    <strong style={{ color: "#115e59" }}>{t("fromBank", { p: Math.round(bank.score * 100) })}</strong>
                    <span style={{ fontSize: 12, color: "#134e4a" }} dir="auto">{t("bankQuestion")}: {bank.question}</span>
                    {bLevels.length > 1 && bLevels.map((k) => (
                      <button
                        key={k}
                        onClick={() => setBankLevel((m) => ({ ...m, [r.id]: k }))}
                        style={{
                          padding: "1px 8px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                          border: "1px solid " + (bLevel === k ? "#115e59" : "#99f6e4"),
                          background: bLevel === k ? "#115e59" : "white",
                          color: bLevel === k ? "white" : "#115e59",
                        }}
                      >
                        {t(k)}
                      </button>
                    ))}
                  </>
                ), bOriginal, "#f0fdfa", busy, undefined, bLevel)}

                {/* The finished answers, each a row, the first that finished on top. */}
                {ready.map((a) => answerRow(r, a.slot, l, (
                  <>
                    <strong>{a.slot === "best" ? `✨ ${a.label ?? modelLabel(a.model)} · ${t(a.level)}` : t(a.level)}</strong>
                    <span style={{ color: "#6b7280", fontSize: 12 }}>
                      {a.slot !== "best" && `· ${a.label ?? modelLabel(a.model)} `}
                      {a.seconds != null && `· ${t("reviewSeconds", { s: a.seconds })}`}
                    </span>
                  </>
                ), answerText(a, l), a.slot === "best" ? BEST_TINT : TINT[a.level], busy))}

                {failed.map((a) => (
                  <div key={`${a.slot}-failed`} style={{ fontSize: 13, color: "#b91c1c", marginBottom: 6,
                                                         display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    ⚠️ {t("reviewAnswerFailed", { m: a.label ?? modelLabel(a.model), level: t(a.level), e: a.error ?? "" })}
                    <button onClick={() => redo(r, undefined, [a.slot])} style={{ border: "1px solid #fca5a5", borderRadius: 4,
                                                                                background: "white", padding: "1px 8px", cursor: "pointer", fontSize: 12 }}>
                      {t("reviewRetry")}
                    </button>
                  </div>
                ))}

                {r.drafting.length > 0 && (
                  <div style={{ fontSize: 13, color: "#5b21b6", marginBottom: 8 }}>
                    {t("reviewDrafting", { list: draftingList })}
                  </div>
                )}
                {ready.length === 0 && r.drafting.length > 0 && !bank && (
                  <div style={{ fontSize: 13, color: "#6b7280", fontStyle: "italic", marginBottom: 8 }}>
                    {t("reviewNoAnswersYet")}
                  </div>
                )}

                {/* The teacher's own text, always possible. */}
                {answerRow(r, "own", l, <strong>✍️ {t("reviewOwn")}</strong>, "", OWN_TINT, busy, t("reviewOwnPlaceholder"))}
              </div>
              );
            })
          )}
        </div>
      )}
    </section>
  );
}
