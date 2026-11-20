import "../styles/review.css";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  BookOpen, Inbox, Languages, MapPin, Megaphone, MessageCircleQuestion, MessagesSquare, PenLine, RefreshCw,
  RotateCcw, Send, Sparkles, Trash2,
} from "lucide-react";
import { api } from "../api";
import type {
  AnswerLevel, AnswerSlot, BankMatch, Lang, PendingReview, RegenModel, ReviewAnswer, ReviewChatEntry,
  ReviewConfig, ReviewStepStatus, SelectResult, TranslateTo,
} from "../types";
import { useLang, type StringKey } from "../i18n";
import { describeError } from "../lib/errors";
import {
  Button, Check, EmptyState, Loading, Notice, Select, Spinner, Switch, Textarea, Time, useConfirm, useToast,
} from "./ui";
import { textDir } from "../lib/textDir";
import { AnsweredRecently } from "./AnsweredRecently";

const LEVELS: AnswerLevel[] = ["nudge", "normal", "more", "direct"];

/** What each level gives the student: the legend, and the tooltip of every level's label. */
const LEVEL_HELP: Record<AnswerLevel, StringKey> = {
  nudge: "reviewLevelHelpNudge", normal: "reviewLevelHelpNormal", more: "reviewLevelHelpMore", direct: "reviewLevelHelpDirect",
};

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

/** The step's status on the card, and its colour (the words carry the meaning; the colour helps scanning). */
const STEP_STATUS: Record<ReviewStepStatus, { key: StringKey; tone: "success" | "warning" | "danger" | "brand" | "muted" }> = {
  open: { key: "reviewStepOpen", tone: "success" },
  waiting_teacher: { key: "reviewStepWaitingTeacher", tone: "warning" },
  waiting_review: { key: "reviewStepWaitingReview", tone: "danger" },
  quiz: { key: "reviewStepQuiz", tone: "brand" },
  quiz_review: { key: "reviewStepQuizReview", tone: "danger" },
  waiting_check: { key: "reviewStepWaitingCheck", tone: "warning" },
  not_started: { key: "reviewStepNotStarted", tone: "muted" },
  finished: { key: "reviewStepFinished", tone: "success" },
};

/** The label of a chat entry, by who wrote it and what it is (also used by the chat view). */
export function entryLabel(e: Pick<ReviewChatEntry, "author" | "kind">): StringKey {
  if (e.author === "student") {
    if (e.kind === "output") return "reviewKindOutput";
    if (e.kind === "answer") return "reviewKindAnswer";
    return "reviewKindStudent";
  }
  switch (e.kind) {
    case "step": return "reviewKindStep";
    case "result": return "reviewKindResult";
    case "quiz": return "reviewKindQuiz";
    case "brief": return "reviewKindBrief";
    case "note": return "reviewKindNote";
    case "returned": return "reviewKindReturned";
    case "reset": return "reviewKindReset";
    case "restart": return "reviewKindRestart";
    case "cancelled": return "reviewKindCancelled";
    default: return "reviewKindTutor";
  }
}

/** How much of the answer a level gives away: one to four filled dots (the label beside it says it in words). */
function Pips({ level }: { level: AnswerLevel }) {
  const n = LEVELS.indexOf(level) + 1;
  return (
    <span className="vc-review-pips" aria-hidden="true">
      {LEVELS.map((k, i) => <span key={k} data-on={i < n} />)}
    </span>
  );
}

/** Why an answer couldn't be drafted, in words a lecturer can act on; the server's own text behind "Details". */
function DraftError({ what, error }: { what: ReactNode; error: string | null | undefined }) {
  const { t } = useLang();
  if (error && /is not set/i.test(error)) return <div>{t("reviewDraftNoKey")}</div>;
  return (
    <div>
      <div>{what}</div>
      {error && (
        <details className="vc-review-details">
          <summary>{t("reviewErrorDetails")}</summary>
          <div className="u-prewrap" dir={textDir(error)}>{error}</div>
        </details>
      )}
    </div>
  );
}

/** One answer, as a row of the card. */
interface RowSpec {
  /** The key of the row's edit box (editKey). */
  k: string;
  chosen: Chosen;
  l: Lang;
  tone: "bank" | "level" | "best" | "own";
  label: ReactNode;
  /** The label in words, for the text box's name. */
  name: string;
  /** What the label means (a tooltip). */
  help?: string;
  meta?: ReactNode;
  /** A line under the label. */
  sub?: ReactNode;
  original: string;
  placeholder?: string;
  level?: AnswerLevel;
}

export function ReviewQueue({ exerciseId, onViewChat }: {
  exerciseId: string | null;
  /** Open the student's whole chat (the dashboard's chat view) for a card. */
  onViewChat?: (r: PendingReview) => void;
}) {
  const { t, lang } = useLang();
  const toast = useToast();
  const confirm = useConfirm();
  const titleId = useId();
  // null until the server has said whether review mode is on.
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [modeSaving, setModeSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [cfg, setCfg] = useState<ReviewConfig | null>(null);
  const [allPending, setPending] = useState<PendingReview[]>([]);
  // The first list has arrived (until then: "loading", not "no questions").
  const [loaded, setLoaded] = useState(false);
  // Only the exercise the live view follows.
  const pending = allPending.filter((r) => r.exercise_id === exerciseId);
  const elsewhere = allPending.length - pending.length;
  const stale = allPending.filter((r) => !r.waiting).length;
  // What each card is doing right now (a send from one of its rows, a delete, drafting again), by card:
  // an action on one card never frees or blocks another card's buttons.
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [staleBusy, setStaleBusy] = useState(false);
  // A card being drafted again and failing.
  const [regenError, setRegenError] = useState<Record<number, string>>({});
  // Teacher edits, keyed by editKey() so each row and language edits on its own.
  // Separate state so the 2s poll never clobbers them.
  const [edits, setEdits] = useState<Record<string, string>>({});
  // Per-card language to view/send; defaults to the language the student wrote in.
  const [cardLang, setCardLang] = useState<Record<number, Lang>>({});
  // Per-card level shown in the question-bank row.
  const [bankLevel, setBankLevel] = useState<Record<number, AnswerLevel>>({});
  // Per-card "save to the question bank" (default from the settings).
  const [saveBank, setSaveBank] = useState<Record<number, boolean>>({});
  // Deleting: tell the student (per card; default yes unless it looks sent by mistake).
  const [notify, setNotify] = useState<Record<number, boolean>>({});
  // Chat entries before the question shown whole (default: cut to two lines), keyed by `${reviewId}:${index}`.
  const [openEntry, setOpenEntry] = useState<Record<string, boolean>>({});
  // A poll asked before one of our own actions finished can still list what that
  // action removed or changed: its answer is dropped (actionSeq). The questions
  // we answered or deleted stay off the list until the server stops listing them (handled).
  const actionSeq = useRef(0);
  const handled = useRef(new Set<number>());
  // Goes up after each answer sent: "Answered recently" loads again at once.
  const [answeredTick, setAnsweredTick] = useState(0);

  const markBusy = (id: number, what: string | null) =>
    setBusy((b) => {
      const next = { ...b };
      if (what) next[id] = what;
      else delete next[id];
      return next;
    });

  /** The row's edit box: per card, answer, language, and for the bank's answer per level too. */
  const editKey = (id: number, chosen: Chosen, l: Lang, level?: AnswerLevel) =>
    chosen === "bank" && level ? `${id}:bank.${level}:${l}` : `${id}:${chosen}:${l}`;
  const langOf = (r: PendingReview): Lang => cardLang[r.id] ?? r.suggested_lang ?? lang;

  const clearEdits = (id: number, slots?: AnswerSlot[]) =>
    setEdits((e) => {
      const next = { ...e };
      for (const k of Object.keys(next)) {
        if (slots ? slots.some((s) => k.startsWith(`${id}:${s}:`)) : k.startsWith(`${id}:`)) delete next[k];
      }
      return next;
    });

  /** A question we answered or deleted: off the list now, and kept off while an older poll still lists it. */
  const settle = (id: number) => {
    handled.current.add(id);
    actionSeq.current += 1;
    setPending((p) => p.filter((x) => x.id !== id));
    clearEdits(id);
  };

  const loadSettings = () => {
    setLoadError(false);
    api.getReviewMode().then((r) => setEnabled(r.enabled)).catch(() => setLoadError(true));
    api.reviewConfig().then(setCfg).catch(() => setLoadError(true));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadSettings, []);

  useEffect(() => {
    if (!enabled) {
      setPending([]);
      setLoaded(false);
      handled.current.clear();
      return;
    }
    let alive = true;
    const tick = () => {
      const asked = actionSeq.current;
      api.pendingReviews().then((list) => {
        if (!alive || asked !== actionSeq.current) return;
        const listed = new Set(list.map((r) => r.id));
        for (const id of [...handled.current]) if (!listed.has(id)) handled.current.delete(id);
        setPending(list.filter((r) => !handled.current.has(r.id)));
        setLoaded(true);
      }).catch(() => { /* a background poll: the page's banner says when the server is unreachable */ });
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => { alive = false; window.clearInterval(id); };
  }, [enabled]);

  const toggle = async (next: boolean) => {
    if (!next && allPending.length > 0 && !(await confirm({
      title: t("reviewOffTitle"),
      body: t("reviewOffBody", { n: allPending.length }),
      confirmLabel: t("reviewOffConfirm"),
    }))) return;
    setEnabled(next);
    setModeSaving(true);
    try {
      await api.setReviewMode(next);
    } catch (e) {
      setEnabled(!next);
      toast.error(t("reviewModeSaveFailed"), e);
    } finally {
      setModeSaving(false);
    }
  };

  const changeConfig = (change: Parameters<typeof api.setReviewConfig>[0]) =>
    api.setReviewConfig(change).then(setCfg).catch((e) => toast.error(t("reviewConfigFailed"), e));

  const remove = async (r: PendingReview) => {
    const tell = notify[r.id] ?? !r.looks_like_noise;
    const name = r.username;
    const body = r.waiting ? t("reviewDeleteBodyNow", { name })
      : tell ? t("reviewDeleteBodyLater", { name }) : t("reviewDeleteBodySilent", { name });
    if (!(await confirm({
      title: t("reviewDeleteTitle", { name }), body, confirmLabel: t("reviewDeleteConfirm"), danger: true,
    }))) return;
    markBusy(r.id, "delete");
    try {
      await api.deleteReview(r.id, tell);
      settle(r.id);
    } catch (e) {
      toast.error(t("reviewDeleteFailed"), e);
    } finally {
      markBusy(r.id, null);
    }
  };

  const removeStale = async () => {
    if (!(await confirm({
      title: t("reviewDeleteStaleConfirm", { n: stale }),
      body: t("reviewDeleteStaleBody"),
      confirmLabel: t("reviewDeleteStaleBtn", { n: stale }),
      danger: true,
    }))) return;
    setStaleBusy(true);
    try {
      const res = await api.deleteStaleReviews(false);
      actionSeq.current += 1;
      setPending((p) => p.filter((x) => x.waiting));
      toast.success(t("reviewDeleteStaleDone", { n: res.deleted }));
    } catch (e) {
      toast.error(t("reviewDeleteStaleFailed"), e);
    } finally {
      setStaleBusy(false);
    }
  };

  /** What a send did, in a toast; a part that failed (saving, the class) in its own. */
  const report = (r: PendingReview, res: SelectResult) => {
    const name = r.username;
    if (res.bank_error) toast.error(t("reviewBankFailed"), new Error(res.bank_error));
    if (res.class_error) toast.error(t("reviewClassFailed"), new Error(res.class_error));
    if (res.bank_error || res.class_error) return;
    const parts = [res.delivered === "later" ? t("reviewToastSentLater", { name }) : t("reviewToastSent", { name })];
    if (res.saved_to_bank) parts.push(t("reviewToastSaved"));
    if (res.sent_to_class) parts.push(t("reviewToastClass", { n: res.sent_to_class }));
    toast.success(parts.join(" "));
  };

  const pick = async (r: PendingReview, rowKey: string, chosen: Chosen, l: Lang, text: string, toClass = false,
                      level?: AnswerLevel) => {
    markBusy(r.id, toClass ? `${rowKey}:all` : rowKey);
    try {
      const res = await api.selectReview(r.id, chosen, l, text, {
        save_to_bank: saveBank[r.id] ?? cfg?.save_to_bank ?? true,
        send_to_class: toClass,
        ...(level ? { level } : {}),
      });
      settle(r.id);
      report(r, res);
      setAnsweredTick((n) => n + 1);
    } catch (e) {
      toast.error(t("reviewSendFailed"), e);
    } finally {
      markBusy(r.id, null);
    }
  };

  const askAll = async (r: PendingReview, rowKey: string, chosen: Chosen, l: Lang, text: string,
                        level?: AnswerLevel) => {
    markBusy(r.id, `${rowKey}:all`);
    let count: number | null = null;
    try {
      count = (await api.broadcastRecipients(r.exercise_id ?? "", r.course_id)).count;
    } catch {
      count = null; // the confirmation says the number couldn't be checked
    } finally {
      markBusy(r.id, null);
    }
    const body = count === null ? t("reviewSendAllUnknown")
      : count > 0 ? t("reviewSendAllConfirm", { n: count }) : t("reviewSendAllNone");
    if (!(await confirm({ title: t("reviewSendAllTitle"), body, confirmLabel: t("reviewSendAll") }))) return;
    await pick(r, rowKey, chosen, l, text, true, level);
  };

  const redo = async (r: PendingReview, m?: RegenModel, slots?: AnswerSlot[]) => {
    setRegenError((x) => { const next = { ...x }; delete next[r.id]; return next; });
    markBusy(r.id, m ? `redo:${m.key}` : `retry:${(slots ?? []).join(",")}`);
    try {
      const fresh = await api.regenerateReview(r.id, m?.key, slots);
      // The rows drafted again show the new drafts, not the lecturer's edit of the old ones.
      clearEdits(r.id, slots ?? (m ? LEVELS : []));
      actionSeq.current += 1;
      setPending((p) => p.map((x) => (x.id === r.id ? fresh : x)));
    } catch (e) {
      setRegenError((x) => ({ ...x, [r.id]: describeError(e, t) }));
    } finally {
      markBusy(r.id, null);
    }
  };

  /** One answer, a full-width row: what it is, the text to edit, and the ways to send it. */
  const answerRow = (r: PendingReview, row: RowSpec) => {
    const value = edits[row.k] ?? row.original;
    const edited = edits[row.k] !== undefined && edits[row.k] !== row.original;
    const doing = busy[r.id];
    const empty = !value.trim();
    return (
      <div key={row.k} className="vc-review-row" data-tone={row.tone}>
        <div className="vc-review-row__head">
          <span className="vc-review-row__label" title={row.help}>{row.label}</span>
          {row.meta}
          {edited && <span className="vc-badge vc-badge--warning">{t("edited")}</span>}
        </div>
        {row.sub}
        <Textarea
          value={value}
          placeholder={row.placeholder}
          rows={rowsFor(value)}
          spellCheck={false}
          aria-label={t("reviewAnswerText", { label: row.name })}
          onChange={(e) => setEdits((prev) => ({ ...prev, [row.k]: e.target.value }))}
        />
        <div className="vc-review-row__actions">
          <Button size="sm" variant="brand-soft" icon={<Send />} busy={doing === row.k} disabled={!!doing || empty}
                  onClick={() => pick(r, row.k, row.chosen, row.l, value, false, row.level)}>
            {doing === row.k ? t("sending") : t("send")}
          </Button>
          <Button size="sm" icon={<Megaphone />} busy={doing === `${row.k}:all`} disabled={!!doing || empty}
                  title={t("reviewSendAllTitle")}
                  onClick={() => askAll(r, row.k, row.chosen, row.l, value, row.level)}>
            {t("reviewSendAll")}
          </Button>
        </div>
      </div>
    );
  };

  const card = (r: PendingReview) => {
    const l = langOf(r);
    const doing = busy[r.id];
    const ready = r.answers.filter((a) => a.status === "ready");
    const failed = r.answers.filter((a) => a.status === "failed");
    const bank = r.bank_match;
    const bLevels = bank ? bankLevels(bank) : [];
    const bLevel = bankLevel[r.id] ?? (bLevels.includes("normal") ? "normal" : bLevels[0]);
    const bOriginal = bank && bLevel ? bank.answers[bLevel]?.[l] ?? "" : "";
    const draftingList = r.drafting.map((d) => `${t(d.level)} (${d.label ?? modelLabel(d.model)})`).join(", ");
    const tell = notify[r.id] ?? !r.looks_like_noise;
    const save = saveBank[r.id] ?? cfg?.save_to_bank ?? true;
    const status = r.step ? STEP_STATUS[r.step.status] : null;

    return (
      <article key={r.id} className="vc-review-card" data-notify-key={`question:${r.id}`} aria-label={`${r.username}: ${plain(r.question).slice(0, 80)}`}>
        {/* Who asked, when, and whether they are still waiting; deleting the question. */}
        <header className="vc-review-card__head">
          <div className="vc-review-card__who">
            <span className="vc-review-card__name" dir={textDir(r.username)}>{r.username}</span>
            <span className="u-muted u-sm"><Time value={r.created_at} /></span>
            {r.waiting ? (
              <span className="vc-badge vc-badge--success"><span className="vc-dot vc-dot--success" /> {t("reviewWaitingNow")}</span>
            ) : (
              <span className="vc-badge" title={t("reviewNotWaiting")}>{t("reviewStoppedWaiting")}</span>
            )}
            {r.looks_like_noise && <span className="vc-badge vc-badge--danger">{t("reviewNoise")}</span>}
          </div>
          <div className="vc-review-card__del">
            <span title={t("reviewDeleteNotifyHint")}>
              <Check checked={tell} disabled={!!doing} onChange={(v) => setNotify((m) => ({ ...m, [r.id]: v }))}>
                {t("reviewDeleteNotify")}
              </Check>
            </span>
            <Button size="sm" variant="danger-soft" icon={<Trash2 />} busy={doing === "delete"} disabled={!!doing}
                    onClick={() => remove(r)}>
              {t("reviewDelete")}
            </Button>
          </div>
        </header>

        {/* The question itself. */}
        <div className="vc-review-card__question" dir={textDir(r.question)}>{r.question}</div>
        {r.question_translation && (
          <div className="vc-review-card__translation">
            <div className="vc-review-card__translation-head">
              <Languages aria-hidden="true" />
              {t("reviewTranslated", { from: langName(r.question_lang, lang), to: langName(r.translated_to, lang) })}
            </div>
            <div className="u-prewrap" dir={textDir(r.question_translation)}>{r.question_translation}</div>
          </div>
        )}

        {/* Where the student is, and what the chat showed just before the question. */}
        <div className="vc-review-context">
          <div className="vc-review-where">
            <MapPin aria-hidden="true" />
            {r.step && status ? (
              <>
                <span className="vc-review-where__step">
                  {t("reviewStep", { label: r.step.label, total: r.step.total, title: r.step.title })}
                </span>
                <span className="vc-review-status" data-tone={status.tone}>{t(status.key)}</span>
              </>
            ) : (
              <span className="u-muted">{t("reviewNoSteps")}</span>
            )}
            {onViewChat && (
              <Button size="sm" variant="quiet" icon={<MessagesSquare />} className="u-push" onClick={() => onViewChat(r)}>
                {t("reviewFullChat")}
              </Button>
            )}
          </div>
          {r.before.entries.length > 0 ? (
            <div>
              <div className="vc-review-before__title">{t("reviewBefore")}</div>
              {r.before.entries.map((e, i) => {
                const key = `${r.id}:${i}`;
                const open = !!openEntry[key];
                return (
                  <button
                    key={key} type="button" className="vc-review-entry" aria-expanded={open}
                    title={open ? undefined : t("reviewEntryExpand")}
                    onClick={() => setOpenEntry((m) => ({ ...m, [key]: !open }))}
                  >
                    <span className="vc-review-entry__kind" data-author={e.author}>
                      {t(entryLabel(e))}{e.step != null && e.kind === "step" ? ` ${e.step}` : ""}
                    </span>
                    <span className="vc-review-entry__text" data-open={open} dir={textDir(plain(e.content))}>{plain(e.content)}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="u-muted u-xs">{t("reviewNoBefore")}</div>
          )}
        </div>

        {/* Options for this question's answer: save it to the bank, its language, draft again. */}
        <div className="vc-review-card__bar">
          <Check checked={save} onChange={(v) => setSaveBank((m) => ({ ...m, [r.id]: v }))}>{t("reviewSaveToBank")}</Check>
          <div className="vc-review-card__tools">
            <span className="vc-review-card__tools-label" aria-hidden="true">{t("answersIn")}</span>
            <div className="vc-segmented" role="group" aria-label={t("answersIn")}>
              {(["en", "he"] as Lang[]).map((opt) => {
                const name = opt === "en" ? t("reviewTranslateEn") : t("reviewTranslateHe");
                return (
                  <button key={opt} type="button" aria-pressed={l === opt} aria-label={name} title={name}
                          onClick={() => setCardLang((m) => ({ ...m, [r.id]: opt }))}>
                    {opt === "en" ? "EN" : "עב"}
                  </button>
                );
              })}
            </div>
            {(cfg?.regen_models ?? []).map((m) => (
              <Button key={m.key} size="sm" variant="quiet" icon={<RefreshCw />} busy={doing === `redo:${m.key}`}
                      disabled={!!doing} title={t("reviewRegenHint", { m: m.label })} onClick={() => redo(r, m)}>
                {t("regenerate", { m: m.label })}
              </Button>
            ))}
          </div>
        </div>

        {regenError[r.id] && (
          <Notice tone="danger"><DraftError what={t("regenFailed")} error={regenError[r.id]} /></Notice>
        )}

        <div className="vc-review-rows">
          {bank && bLevel && answerRow(r, {
            k: editKey(r.id, "bank", l, bLevel), chosen: "bank", l, tone: "bank", level: bLevel,
            label: <><BookOpen aria-hidden="true" /> {t("fromBank")}</>,
            name: `${t("fromBank")} (${t(bLevel)})`,
            meta: (
              <>
                <span className="vc-badge vc-badge--success">{t("bankMatch", { p: Math.round(bank.score * 100) })}</span>
                {bLevels.length > 1 ? (
                  <div className="vc-segmented" role="group" aria-label={t("reviewBankLevel")}>
                    {bLevels.map((k) => (
                      <button key={k} type="button" aria-pressed={bLevel === k} title={t(LEVEL_HELP[k])}
                              onClick={() => setBankLevel((m) => ({ ...m, [r.id]: k }))}>
                        {t(k)}
                      </button>
                    ))}
                  </div>
                ) : (
                  <span className="vc-review-row__meta" title={t(LEVEL_HELP[bLevel])}>{t(bLevel)}</span>
                )}
              </>
            ),
            sub: (
              <div className="vc-review-row__sub" dir={textDir(bank.question)}>
                <span className="vc-review-row__sub-label">{t("bankQuestion")}:</span> {bank.question}
              </div>
            ),
            original: bOriginal,
          })}

          {/* The finished answers, each a row, the first that finished on top. */}
          {ready.map((a) => {
            const by = a.label ?? modelLabel(a.model);
            const meta = [a.slot === "best" ? null : by, a.seconds != null ? t("reviewSeconds", { s: a.seconds }) : null]
              .filter(Boolean).join(" · ");
            return answerRow(r, {
              k: editKey(r.id, a.slot, l), chosen: a.slot, l, tone: a.slot === "best" ? "best" : "level",
              label: <><Pips level={a.level} /> {t(a.level)}</>,
              name: a.slot === "best" ? `${t(a.level)} (${t("reviewExtraBy", { m: by })})` : t(a.level),
              help: a.slot === "best" ? `${t(LEVEL_HELP[a.level])} ${t("reviewLevelHelpBest")}` : t(LEVEL_HELP[a.level]),
              meta: (
                <>
                  {a.slot === "best" && (
                    <span className="vc-badge vc-badge--info"><Sparkles aria-hidden="true" /> {t("reviewExtraBy", { m: by })}</span>
                  )}
                  {meta && <span className="vc-review-row__meta">{meta}</span>}
                </>
              ),
              original: answerText(a, l),
            });
          })}

          {failed.map((a) => (
            <div key={`${a.slot}-failed`} className="vc-review-row" data-tone="failed">
              <div className="vc-review-row__head">
                <span className="vc-review-row__label" title={t(LEVEL_HELP[a.level])}><Pips level={a.level} /> {t(a.level)}</span>
                {a.slot === "best" && (
                  <span className="vc-badge vc-badge--info">
                    <Sparkles aria-hidden="true" /> {t("reviewExtraBy", { m: a.label ?? modelLabel(a.model) })}
                  </span>
                )}
                <Button size="sm" icon={<RotateCcw />} className="u-push" busy={doing === `retry:${a.slot}`}
                        disabled={!!doing} onClick={() => redo(r, undefined, [a.slot])}>
                  {t("reviewRetry")}
                </Button>
              </div>
              <div className="u-sm u-danger">
                <DraftError what={t("reviewAnswerFailed", { m: a.label ?? modelLabel(a.model) })} error={a.error} />
              </div>
            </div>
          ))}

          {r.drafting.length > 0 && (
            <div className="vc-review-drafting"><Spinner /> {t("reviewDrafting", { list: draftingList })}</div>
          )}
          {ready.length === 0 && r.drafting.length > 0 && !bank && (
            <div className="u-muted u-sm">{t("reviewNoAnswersYet")}</div>
          )}

          {/* The teacher's own text, always possible. */}
          {answerRow(r, {
            k: editKey(r.id, "own", l), chosen: "own", l, tone: "own",
            label: <><PenLine aria-hidden="true" /> {t("reviewOwn")}</>, name: t("reviewOwn"),
            original: "", placeholder: t("reviewOwnPlaceholder"),
          })}
        </div>
      </article>
    );
  };

  const best = cfg?.best_answer;

  return (
    <section className="vc-card vc-review" data-on={enabled === true} data-notify-section="question" aria-labelledby={titleId}>
      <div className="vc-review__head">
        <div className="vc-review__titles">
          <h2 className="vc-review__title" id={titleId}>
            <MessageCircleQuestion aria-hidden="true" />
            {t("reviewMode")}
            {enabled && pending.length > 0 && (
              <span className="vc-badge vc-badge--solid-brand vc-badge--count">{pending.length}</span>
            )}
          </h2>
          {enabled !== null && <p className="vc-review__hint">{enabled ? t("reviewOnHint") : t("reviewOffHint")}</p>}
        </div>
        <div className="vc-review__switch">
          {enabled !== null ? (
            <Switch checked={enabled} disabled={modeSaving} onChange={toggle} label={t("reviewSwitchLabel")}>
              {enabled ? t("reviewScopeOn") : t("reviewScopeOff")}
            </Switch>
          ) : loadError ? (
            <>
              <span className="u-sm u-danger">{t("reviewModeLoadFailed")}</span>
              <Button size="sm" onClick={loadSettings}>{t("retry")}</Button>
            </>
          ) : (
            <span className="u-row u-sm u-muted"><Spinner /> {t("reviewModeChecking")}</span>
          )}
        </div>
      </div>

      {enabled && (
        <div className="vc-review__body">
          {loadError && (
            <Notice tone="warning" action={<Button size="sm" onClick={loadSettings}>{t("retry")}</Button>}>
              {t("reviewSettingsLoadFailed")}
            </Notice>
          )}
          {cfg && (
            <div className="vc-review-options">
              <label className="vc-review-options__item">
                <span>{t("reviewTranslateTo")}</span>
                <Select small inline value={cfg.translate_to}
                        onChange={(e) => changeConfig({ translate_to: e.target.value as TranslateTo })}>
                  <option value="he">{t("reviewTranslateHe")}</option>
                  <option value="en">{t("reviewTranslateEn")}</option>
                  <option value="off">{t("reviewTranslateOff")}</option>
                </Select>
              </label>
              {best && (best.available ? (
                <span className="vc-review-options__item">
                  <Check checked={best.enabled} onChange={(v) => changeConfig({ best_answer: v })}>
                    {t("reviewBest", { m: best.label ?? modelLabel(best.model) })}
                  </Check>
                  <label className="vc-review-options__item">
                    <span>{t("reviewBestLevel")}</span>
                    <Select small inline value={best.level} disabled={!best.enabled}
                            onChange={(e) => changeConfig({ best_level: e.target.value as AnswerLevel })}>
                      {LEVELS.map((k) => <option key={k} value={k}>{t(k)}</option>)}
                    </Select>
                  </label>
                </span>
              ) : (
                <span className="u-muted">{t("reviewBestOff", { m: best.label ?? "Opus" })}</span>
              ))}
              <Check checked={cfg.save_to_bank} onChange={(v) => changeConfig({ save_to_bank: v })}>
                {t("reviewSaveDefault")}
              </Check>
            </div>
          )}

          {elsewhere > 0 && <Notice tone="info">{t("otherExercisesWaiting", { n: elsewhere })}</Notice>}
          {stale > 0 && (
            <div>
              <Button size="sm" variant="danger-soft" icon={<Trash2 />} busy={staleBusy} onClick={removeStale}>
                {t("reviewDeleteStale", { n: stale })}
              </Button>
            </div>
          )}

          {!loaded ? (
            <Loading />
          ) : pending.length === 0 ? (
            <EmptyState icon={<Inbox />} title={t("noQuestions")}>{t("reviewEmptyText")}</EmptyState>
          ) : (
            <>
              <details className="vc-review-legend">
                <summary>{t("reviewLegendTitle")}</summary>
                <ul className="vc-review-legend__list">
                  {LEVELS.map((k) => (
                    <li key={k}>
                      <Pips level={k} />
                      <span className="vc-review-legend__name">{t(k)}</span>
                      <span>{t(LEVEL_HELP[k])}</span>
                    </li>
                  ))}
                </ul>
              </details>
              {pending.map(card)}
            </>
          )}
          <AnsweredRecently exerciseId={exerciseId} refresh={answeredTick} plain={plain} />
        </div>
      )}
    </section>
  );
}
