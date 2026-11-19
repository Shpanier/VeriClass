import "../styles/students.css";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AppWindow, Ban, ChevronDown, CircleHelp, ClipboardPaste, FileUp, Hourglass, MessagesSquare, Minimize2, MonitorCheck,
  MonitorOff, MonitorX, Search, SquareTerminal, TriangleAlert, Users, Video, WifiOff,
} from "lucide-react";
import type { ExamState, ParamLabel, Student } from "../types";
import { renderParams } from "../params";
import { alertTotal, needsAttention } from "../proctor";
import { useLang, type StringKey, type Translate } from "../i18n";
import { useFeatures } from "../app/features";
import { Button, EmptyState, Input, Loading, Select, Time } from "./ui";
import { textDir } from "../lib/textDir";

type Mode = Student["mode"];

/** What the page does for one student: the same buttons on a student card and
 *  on a student's row in the class-pacing panel (App.tsx opens the dialogs). */
export interface StudentHandlers {
  onModeChange: (sessionId: string, mode: "mentor" | "coding_partner") => void | Promise<void>;
  onAskThem: (s: Student) => void;
  onViewChat: (s: Student) => void;
  onProctorLog: (s: Student) => void;
  onViewSubmissions: (s: Student) => void;
  onTerminalLog: (s: Student) => void;
}

interface Props {
  students: Student[];
  /** False until the first list of students arrived: shows "loading" instead of "nobody here". */
  loaded?: boolean;
  paramLabels?: ParamLabel[];
  handlers: StudentHandlers;
}

// ---- exam helpers, shared with the alert bar and the exam log (IDE plugin) ----

// Event kinds that have a translated label (kind_<kind> in the strings).
const EXAM_KINDS = new Set([
  "exam_started", "focus_lost", "minimized",
  "fullscreen_exited", "focus_regained", "window_restored",
  "blocked_command", "stock_terminal_opened",
  "fullscreen_restored", "tool_window_opened", "other_window_opened", "other_window_closed",
  "file_opened", "paste_external", "paste_internal",
  "other_app_in_front", "window_unmaximized", "window_maximized", "ide_closed",
]);

/** An exam event kind in words; a kind this dashboard doesn't know yet shows as itself. */
export function examKindLabel(kind: string, t: Translate): string {
  return EXAM_KINDS.has(kind) ? t(`kind_${kind}` as StringKey) : kind.replace(/_/g, " ");
}

export type Tone = "success" | "warning" | "danger" | "neutral";

/** How serious a live exam state is. */
export function examStateTone(state: ExamState): Tone {
  switch (state) {
    case "ok": return "success";
    case "away": case "ide_closed": return "danger";
    case "no_signal": return "neutral";
    default: return "warning";
  }
}

const STATE_ICON: Record<ExamState, ReactNode> = {
  ok: <MonitorCheck aria-hidden="true" />,
  away: <MonitorX aria-hidden="true" />,
  other_window: <AppWindow aria-hidden="true" />,
  not_fullscreen: <Minimize2 aria-hidden="true" />,
  not_maximized: <Minimize2 aria-hidden="true" />,
  ide_closed: <MonitorOff aria-hidden="true" />,
  no_signal: <WifiOff aria-hidden="true" />,
};

/** The live exam state as a labelled pill: an icon and the words. */
export function ExamStatePill({ state, detail, flash, className }: {
  state: ExamState;
  detail?: string | null;
  /** Needs attention now: a solid colour that blinks. */
  flash?: boolean;
  className?: string;
}) {
  const { t } = useLang();
  const tone = examStateTone(state);
  const look = flash && (tone === "danger" || tone === "warning") ? `vc-badge--solid-${tone}`
    : tone === "neutral" ? "" : `vc-badge--${tone}`;
  const cls = ["vc-badge", look, flash ? "proctor-flash" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <span className={cls} title={state === "no_signal" ? t("stateNoSignalHint") : detail ?? undefined}>
      {STATE_ICON[state]}
      <span>{t(`state_${state}` as StringKey)}</span>
    </span>
  );
}

/** How long a student was away, in the dashboard's language. */
export function awayText(ms: number | null, t: Translate): string {
  if (ms == null) return "";
  const s = Math.round(ms / 1000);
  return s < 60 ? t("plSeconds", { n: s }) : t("plMinSec", { m: Math.floor(s / 60), s: s % 60 });
}

/** A grade band as a badge colour, the same on the cards and in the submissions dialog. */
export function bandBadge(band?: string | null): string {
  switch (band) {
    case "excellent": return "vc-badge--success";
    case "good": return "vc-badge--info";
    case "review": return "vc-badge--warning";
    case "flagged": return "vc-badge--danger";
    case "fail": return "";
    default: return "vc-badge--brand";
  }
}

// ---- the grid ----

type Sort = "active" | "name" | "attention";

// Open or closed, remembered in this browser (closed at first: one line).
const OPEN_KEY = "vc.students.open";

function savedOpen(): boolean {
  try { return localStorage.getItem(OPEN_KEY) === "1"; } catch { return false; }
}

/** One card per student connected to the followed exercise in the last 30
 *  minutes. With more than 8, a search box and a sort order appear above. */
export function StudentGrid({ students, loaded = true, paramLabels, handlers }: Props) {
  const { t } = useLang();
  const { plugin } = useFeatures();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("active");
  const [open, setOpen] = useState(savedOpen);
  const toggle = () => setOpen((was) => {
    try { localStorage.setItem(OPEN_KEY, was ? "0" : "1"); } catch { /* ignore */ }
    return !was;
  });

  // The toolbar stays while a search or another order is in use, so the
  // lecturer can always see why the list looks the way it does.
  const tools = students.length > 8 || query !== "" || sort !== "active";
  const order: Sort = sort === "attention" && !plugin ? "active" : sort;

  const shown = useMemo(() => {
    if (!tools) return students;
    const q = query.trim().toLocaleLowerCase();
    const list = q ? students.filter((s) => s.username.toLocaleLowerCase().includes(q)) : [...students];
    // "Last active" is the server's own order (most recent first): nothing to do.
    if (order === "name") list.sort((a, b) => a.username.localeCompare(b.username));
    if (order === "attention") {
      const rank = (s: Student) => (needsAttention(s) ? 2 : alertTotal(s) > 0 ? 1 : 0);
      list.sort((a, b) => rank(b) - rank(a) || alertTotal(b) - alertTotal(a));
    }
    return list;
  }, [students, tools, query, order]);

  // A version tells students apart only when they don't all have the same one.
  const versions = useMemo(() => new Set(students.map((s) => s.variant)).size, [students]);

  return (
    <section className="vc-section vc-students-section" data-open={open} aria-labelledby="vc-students-title">
      <div className="vc-section__head">
        <h2 className="vc-section__title" id="vc-students-title">
          <button type="button" className="vc-section__toggle" aria-expanded={open} aria-controls="vc-students-body"
                  title={open ? t("sgCollapse") : t("sgExpand")} onClick={toggle}>
            <ChevronDown className="vc-section__chev" aria-hidden="true" />
            <Users aria-hidden="true" /> {t("sgTitle")}
            <span className="vc-badge vc-badge--count">{students.length}</span>
          </button>
        </h2>
        {open && students.length > 0 && <span className="vc-section__hint">{t("sgModeLegend")}</span>}
        {!open && <span className="vc-section__hint">{students.length > 0 ? t("sgClosedHint") : t("sgClosedEmpty")}</span>}
        {open && tools && (
          <div className="vc-section__actions vc-students-toolbar">
            <label className="vc-students-toolbar__search">
              <span className="u-sr">{t("sgSearch")}</span>
              <Search aria-hidden="true" />
              <Input type="search" small value={query} placeholder={t("sgSearch")}
                     onChange={(e) => setQuery(e.target.value)} />
            </label>
            <label className="u-row u-gap-6 u-sm u-soft">
              {t("sgSort")}
              <Select small inline value={order} onChange={(e) => setSort(e.target.value as Sort)}>
                <option value="active">{t("sgSortActive")}</option>
                <option value="name">{t("sgSortName")}</option>
                {plugin && <option value="attention">{t("sgSortAttention")}</option>}
              </Select>
            </label>
          </div>
        )}
      </div>

      <div id="vc-students-body" hidden={!open}>
      {!open ? null : students.length === 0 && !loaded ? (
        <div className="vc-card vc-card--flat"><Loading /></div>
      ) : students.length === 0 ? (
        <div className="vc-card vc-card--flat">
          <EmptyState icon={<Users />} title={t("sgEmptyTitle")}>{t("sgEmptyText")}</EmptyState>
        </div>
      ) : shown.length === 0 ? (
        <div className="vc-card vc-card--flat">
          <EmptyState icon={<Search />} title={t("sgNoMatch", { q: query.trim() })}
                      actions={<Button size="sm" onClick={() => setQuery("")}>{t("sgClearSearch")}</Button>} />
        </div>
      ) : (
        <div className="vc-grid">
          {shown.map((s) => (
            <StudentCard
              key={s.session_id}
              s={s}
              plugin={plugin}
              showVersion={versions > 1}
              paramLabels={paramLabels}
              handlers={handlers}
            />
          ))}
        </div>
      )}
      </div>
    </section>
  );
}

/** How urgently a student's exam state needs the lecturer (IDE plugin), or null. */
export function attentionTone(s: Student, plugin: boolean): Tone | null {
  const state = plugin ? s.exam_state ?? null : null;
  return plugin && needsAttention(s) && state ? examStateTone(state) : null;
}

function initialsOf(name: string): string {
  return name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

function StudentCard({ s, plugin, showVersion, paramLabels, handlers }: {
  s: Student;
  plugin: boolean;
  showVersion: boolean;
  paramLabels?: ParamLabel[];
  handlers: StudentHandlers;
}) {
  const { t } = useLang();
  const state = plugin ? s.exam_state ?? null : null;
  const attention = plugin && needsAttention(s);
  const tone = attentionTone(s, plugin);

  const cardCls = [
    "vc-card", "vc-students-card",
    tone ? "vc-students-card--alert proctor-pulse" : "",
    tone === "danger" ? "vc-card--danger" : tone === "warning" ? "vc-card--warning" : tone === "neutral" ? "vc-card--muted" : "",
  ].filter(Boolean).join(" ");
  const avatarCls = ["vc-students-avatar", tone ? `vc-students-avatar--${tone === "neutral" ? "muted" : tone}` : ""]
    .filter(Boolean).join(" ");

  return (
    <article className={cardCls} aria-labelledby={`vc-student-${s.session_id}`}>
      <div className="vc-students-card__head">
        <span className={avatarCls} aria-hidden="true">{initialsOf(s.username)}</span>
        <div className="vc-students-card__who">
          <h3 className="vc-students-card__name u-truncate" id={`vc-student-${s.session_id}`} title={s.username}>
            <span dir={textDir(s.username)}>{s.username}</span>
          </h3>
          <div className="vc-students-card__meta">{t("lastActive")} <Time value={s.last_active_at} /></div>
        </div>
        {state && <ExamStatePill state={state} detail={s.exam_state_detail} flash={attention} className="vc-students-pill" />}
      </div>

      <StudentSignals s={s} plugin={plugin} showVersion={showVersion} paramLabels={paramLabels} />

      <div className="vc-students-card__foot">
        <TutorMode s={s} onModeChange={handlers.onModeChange} />
        <StudentActions s={s} handlers={handlers} />
        <StudentTools s={s} plugin={plugin} handlers={handlers} />
      </div>
    </article>
  );
}

/** What the lecturer should know about a student at a glance: the IDE plugin's
 *  exam notes, the questions asked, pastes, the grade, the version's parameters. */
export function StudentSignals({ s, plugin, showVersion, paramLabels }: {
  s: Student;
  plugin: boolean;
  showVersion: boolean;
  paramLabels?: ParamLabel[];
}) {
  const { t } = useLang();
  const params = renderParams(s.variant_params, paramLabels);
  const terminalAlerts = plugin ? s.terminal_alerts ?? 0 : 0;
  const pastes = plugin ? s.paste_count ?? 0 : 0;
  const grade = plugin && s.recommended_grade != null ? Math.round(s.grade_override ?? s.recommended_grade) : null;
  const badges = (showVersion && !!s.variant) || s.probe_count > 0 || terminalAlerts > 0 || pastes > 0 || grade != null;

  return (
    <>
      {plugin && s.exam_state === "other_window" && s.exam_state_detail && (
        <div className="vc-students-note u-warning u-bold">
          <AppWindow aria-hidden="true" />
          <span className="vc-students-note__text" dir={textDir(s.exam_state_detail)}>{s.exam_state_detail}</span>
        </div>
      )}
      {plugin && s.live && <LiveLine s={s} />}
      {plugin && s.last_alert_kind && (
        <div className="vc-students-note u-danger" title={s.last_alert_detail ?? undefined}>
          <TriangleAlert aria-hidden="true" />
          <span className="vc-students-note__text">
            {t("lastAlert")}: <strong>{examKindLabel(s.last_alert_kind, t)}</strong>
            {s.last_alert_detail && <span className="u-soft"> · <bdi>{s.last_alert_detail}</bdi></span>}
            {s.last_alert_at && <span className="u-soft"> · <Time value={s.last_alert_at} mode="clock" /></span>}
          </span>
        </div>
      )}

      {badges && (
        <div className="vc-students-badges">
          {showVersion && s.variant && (
            <span className="vc-badge"><span>{t("sgVersion", { v: s.variant })}</span></span>
          )}
          {s.probe_count > 0 && (
            <span className="vc-badge vc-badge--info" title={t("sgQuestionsTitle")}>
              <CircleHelp aria-hidden="true" />
              {s.probe_count === 1 ? t("sgOneQuestionAsked") : t("sgQuestionsAsked", { n: s.probe_count })}
            </span>
          )}
          {terminalAlerts > 0 && (
            <span className="vc-badge vc-badge--danger"><Ban aria-hidden="true" /> {t("blockedN", { n: terminalAlerts })}</span>
          )}
          {pastes > 0 && (
            <span className="vc-badge"><ClipboardPaste aria-hidden="true" /> {t("pastesN", { n: pastes })}</span>
          )}
          {grade != null && (
            <span className={`vc-badge ${bandBadge(s.grade_band)}`}
                  title={s.grade_band ? t(`band_${s.grade_band}` as StringKey) : undefined}>
              {t("sgGrade", { g: grade })}
            </span>
          )}
        </div>
      )}

      {params.length > 0 && (
        <div className="vc-students-params">
          {params.map((p, i) => (
            <span key={i}>
              {i > 0 && <span className="u-muted"> · </span>}
              <span className="vc-students-params__label">{p.label}:</span>{" "}
              <span className="vc-students-params__value" dir={textDir(p.value)}>{p.value}</span>
            </span>
          ))}
        </div>
      )}
    </>
  );
}

/** The tutor's mode for this student (mentor / coding partner). */
export function TutorMode({ s, onModeChange }: { s: Student; onModeChange: StudentHandlers["onModeChange"] }) {
  const { t } = useLang();
  // The tutor mode the lecturer just picked, shown until the server's next
  // list says what it really is (the page shows a message if the change failed).
  const [pending, setPending] = useState<{ mode: Mode; settled: boolean } | null>(null);
  useEffect(() => { setPending((p) => (p?.settled ? null : p)); }, [s]);
  const saving = pending != null && !pending.settled;
  const changeMode = async (mode: Mode) => {
    setPending({ mode, settled: false });
    try {
      // The page's handler is async: wait for it, so the control stays busy until it answers.
      await onModeChange(s.session_id, mode);
    } catch {
      // The page reports a failed change itself.
    } finally {
      setPending({ mode, settled: true });
    }
  };
  return (
    <label className="vc-students-mode" title={t("sgModeLegend")}>
      {t("sgMode")}
      <Select small inline value={pending?.mode ?? s.mode} disabled={saving} aria-busy={saving || undefined}
              onChange={(e) => void changeMode(e.target.value as Mode)}>
        <option value="mentor">{t("sgMentor")}</option>
        <option value="coding_partner">{t("sgCodingPartner")}</option>
      </Select>
      {saving && <><span className="vc-spinner" aria-hidden="true" /><span className="u-sr">{t("sgSaving")}</span></>}
    </label>
  );
}

/** "View chat" and "Ask them". */
export function StudentActions({ s, handlers }: { s: Student; handlers: StudentHandlers }) {
  const { t } = useLang();
  return (
    <div className="vc-students-actions">
      <Button variant="primary" size="sm" icon={<MessagesSquare />} onClick={() => handlers.onViewChat(s)}>
        {t("viewChat")}
      </Button>
      <Button size="sm" icon={<CircleHelp />} title={t("sgAskTitle")} onClick={() => handlers.onAskThem(s)}>
        {t("askThem")}
      </Button>
    </div>
  );
}

/** The IDE plugin's records of a student: submissions, the exam log, the terminal. */
export function StudentTools({ s, plugin, handlers }: { s: Student; plugin: boolean; handlers: StudentHandlers }) {
  const { t } = useLang();
  if (!plugin) return null;
  // Running the exam client at all means at least an `exam_started` event exists.
  const examClient = s.exam_state != null || s.focus_alerts > 0;
  const terminalAlerts = s.terminal_alerts ?? 0;
  const usesTerminal = (s.terminal_count ?? 0) > 0 || terminalAlerts > 0;
  const alerts = alertTotal(s);
  const submissions = s.submission_count ?? 0;
  return (
    <div className="vc-students-tools">
      <Button variant="quiet" size="sm" icon={<FileUp />} title={t("openSubmissionsTitle")}
              onClick={() => handlers.onViewSubmissions(s)}>
        {submissions > 0 ? t("submissionsN", { n: submissions }) : t("submissions")}
      </Button>
      {examClient && (
        <Button variant={alerts > 0 ? "danger-soft" : "quiet"} size="sm" icon={<Video />}
                title={t("openProctorLogTitle")} onClick={() => handlers.onProctorLog(s)}>
          {alerts > 0 ? t("alerts", { n: alerts }) : t("proctorLog")}
        </Button>
      )}
      {usesTerminal && (
        <Button variant={terminalAlerts > 0 ? "danger-soft" : "quiet"} size="sm" icon={<SquareTerminal />}
                title={t("openTerminalLogTitle")} onClick={() => handlers.onTerminalLog(s)}>
          {t("terminalN", { n: s.terminal_count ?? 0 })}
        </Button>
      )}
    </div>
  );
}

/** What the exam client reports right now: the editor tabs and reports it couldn't send yet. */
function LiveLine({ s }: { s: Student }) {
  const { t } = useLang();
  const live = s.live!;
  const files = live.open_files ?? [];
  const unsent = live.unsent_reports ?? 0;
  if (files.length === 0 && unsent === 0) return null;
  return (
    <div className="vc-students-live">
      {files.length > 0 && (
        <div className="vc-students-live__files">
          <span className="u-muted">{t("liveTabs")}:</span>{" "}
          <span dir="ltr">
            {files.map((f, i) => (
              <span key={f}>
                {i > 0 && ", "}
                <span className={f === live.active_file ? "vc-students-live__active" : undefined}>{f}</span>
              </span>
            ))}
          </span>
        </div>
      )}
      {unsent > 0 && (
        <div className="vc-students-note u-warning">
          <Hourglass aria-hidden="true" /> <span>{t("unsentReports", { n: unsent })}</span>
        </div>
      )}
    </div>
  );
}
