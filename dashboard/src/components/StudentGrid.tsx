import type { ParamLabel, Student } from "../types";
import { renderParams } from "../params";
import { alertTotal, needsAttention, STATE_STYLE } from "../proctor";
import { useLang, type StringKey } from "../i18n";

interface Props {
  students: Student[];
  paramLabels?: ParamLabel[];
  onModeChange: (sessionId: string, mode: "mentor" | "coding_partner") => void;
  onAskThem: (sessionId: string) => void;
  onViewChat: (sessionId: string) => void;
  onProctorLog: (sessionId: string) => void;
  onViewSubmissions: (sessionId: string) => void;
  onTerminalLog: (sessionId: string) => void;
}

export function StudentGrid({ students, paramLabels, onModeChange, onAskThem, onViewChat, onProctorLog, onViewSubmissions, onTerminalLog }: Props) {
  if (students.length === 0) return null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 16,
      }}
    >
      {students.map((s) => (
        <StudentCard
          key={s.session_id}
          s={s}
          paramLabels={paramLabels}
          onModeChange={onModeChange}
          onAskThem={onAskThem}
          onViewChat={onViewChat}
          onProctorLog={onProctorLog}
          onViewSubmissions={onViewSubmissions}
          onTerminalLog={onTerminalLog}
        />
      ))}
    </div>
  );
}

function StudentCard({
  s,
  paramLabels,
  onModeChange,
  onAskThem,
  onViewChat,
  onProctorLog,
  onViewSubmissions,
  onTerminalLog,
}: {
  s: Student;
  paramLabels?: ParamLabel[];
  onModeChange: Props["onModeChange"];
  onAskThem: Props["onAskThem"];
  onViewChat: Props["onViewChat"];
  onProctorLog: Props["onProctorLog"];
  onViewSubmissions: Props["onViewSubmissions"];
  onTerminalLog: Props["onTerminalLog"];
}) {
  const { t } = useLang();
  const params = renderParams(s.variant_params, paramLabels);
  const initials = s.username
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  // Running the exam client at all means at least an `exam_started` event exists.
  const examClient = s.exam_state != null || s.focus_alerts > 0;
  const terminalAlerts = s.terminal_alerts ?? 0;
  const usesTerminal = (s.terminal_count ?? 0) > 0 || terminalAlerts > 0;
  const alerts = alertTotal(s);
  const state = s.exam_state ? STATE_STYLE[s.exam_state] : null;
  const attention = needsAttention(s);
  return (
    <div
      className={attention ? "proctor-pulse" : undefined}
      style={{
        border: `${attention ? 2 : 1}px solid ${attention && state ? state.color : "#ddd"}`,
        borderRadius: 8,
        padding: 16,
        background: attention && state ? state.bg : "white",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            width: 36,
            height: 36,
            flexShrink: 0,
            borderRadius: "50%",
            background: attention && state ? state.color : "#3b82f6",
            color: "white",
            display: "grid",
            placeItems: "center",
            fontWeight: 600,
          }}
        >
          {initials}
        </div>
        <strong>{s.username}</strong>
        {s.exam_state && state && (
          <span
            className={attention ? "proctor-flash" : undefined}
            title={s.exam_state === "no_signal" ? t("stateNoSignalHint") : s.exam_state_detail ?? undefined}
            style={{
              marginInlineStart: "auto",
              background: attention ? state.color : state.bg,
              color: attention ? "white" : state.color,
              fontSize: 11,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 999,
              whiteSpace: "nowrap",
            }}
          >
            {state.icon} {t(`state_${s.exam_state}` as StringKey)}
          </span>
        )}
      </div>
      {s.exam_state === "other_window" && s.exam_state_detail && (
        <div dir="auto" style={{ fontSize: 12, fontWeight: 700, color: STATE_STYLE.other_window.color, marginTop: 4, textAlign: "start" }}>
          {s.exam_state_detail}
        </div>
      )}
      {s.live && <LiveLine s={s} />}
      {s.last_alert_kind && (
        <div
          title={s.last_alert_detail ?? undefined}
          style={{
            fontSize: 12, color: "#7f1d1d", marginTop: 4, overflow: "hidden",
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          }}
        >
          ⚠ {t("lastAlert")}: <strong>{t(`kind_${s.last_alert_kind}` as StringKey)}</strong>
          {s.last_alert_detail && <span style={{ color: "#6b7280" }}> — <bdi>{s.last_alert_detail}</bdi></span>}
          <span style={{ color: "#9ca3af" }}> · {s.last_alert_at}</span>
        </div>
      )}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "8px 0" }}>
        <Chip>{s.exercise}</Chip>
        <Chip>{s.variant}</Chip>
        <Chip color={s.mode === "mentor" ? "#10b981" : "#f59e0b"}>
          {s.mode === "mentor" ? t("mentor") : t("codingPartner")}
        </Chip>
        <Chip>🔎 {s.probe_count}</Chip>
        {terminalAlerts > 0 && <Chip color="#b91c1c">🚫 {t("blockedN", { n: terminalAlerts })}</Chip>}
        {(s.paste_count ?? 0) > 0 && <Chip>{t("pastesN", { n: s.paste_count ?? 0 })}</Chip>}
        {s.recommended_grade != null && (
          <Chip color={bandColor(s.grade_band)}>
            🎯 {Math.round(s.grade_override ?? s.recommended_grade)}
          </Chip>
        )}
      </div>
      {params.length > 0 && (
        <div style={{ fontSize: 12, color: "#4b5563", marginBottom: 6, lineHeight: 1.5 }}>
          {params.map((p, i) => (
            <span key={i}>
              {i > 0 && <span style={{ color: "#d1d5db" }}> · </span>}
              <span style={{ color: "#6b7280" }}>{p.label}:</span>{" "}
              <span style={{ fontWeight: 600 }} dir="auto">{p.value}</span>
            </span>
          ))}
        </div>
      )}
      <div style={{ fontSize: 12, color: "#666" }}>{t("lastActive", { t: s.last_active_at })}</div>
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <select
          value={s.mode}
          onChange={(e) => onModeChange(s.session_id, e.target.value as "mentor" | "coding_partner")}
        >
          <option value="mentor">{t("mentor")}</option>
          <option value="coding_partner">{t("codingPartner")}</option>
        </select>
        <button
          onClick={() => onViewChat(s.session_id)}
          style={{
            background: "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "6px 12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          💬 {t("viewChat")}
        </button>
        <button
          onClick={() => onAskThem(s.session_id)}
          style={{
            background: "#f97316",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "6px 12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          🔎 {t("askThem")}
        </button>
        <button
          onClick={() => onViewSubmissions(s.session_id)}
          title={t("openSubmissionsTitle")}
          style={{
            background: (s.submission_count ?? 0) > 0 ? "#7c3aed" : "#6b7280",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "6px 12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          📤 {(s.submission_count ?? 0) > 0 ? t("submissionsN", { n: s.submission_count ?? 0 }) : t("submissions")}
        </button>
        {examClient && (
          <button
            onClick={() => onProctorLog(s.session_id)}
            title={t("openProctorLogTitle")}
            style={{
              background: alerts > 0 ? "#b91c1c" : "#6b7280",
              color: "white",
              border: "none",
              borderRadius: 6,
              padding: "6px 12px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            🎥 {alerts > 0 ? t("alerts", { n: alerts }) : t("proctorLog")}
          </button>
        )}
        {usesTerminal && (
          <button
            onClick={() => onTerminalLog(s.session_id)}
            title={t("openTerminalLogTitle")}
            style={{
              background: terminalAlerts > 0 ? "#b91c1c" : "#0f172a",
              color: "white",
              border: "none",
              borderRadius: 6,
              padding: "6px 12px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            ⌨ {t("terminalN", { n: s.terminal_count ?? 0 })}
          </button>
        )}
      </div>
    </div>
  );
}

/** What the exam client reports right now: the editor tabs and reports it couldn't send yet. */
function LiveLine({ s }: { s: Student }) {
  const { t } = useLang();
  const live = s.live!;
  const files = live.open_files ?? [];
  const unsent = live.unsent_reports ?? 0;
  return (
    <div style={{ fontSize: 12, color: "#4b5563", marginTop: 4, lineHeight: 1.5 }}>
      {files.length > 0 && (
        <div dir="ltr" style={{ textAlign: "start" }}>
          <span style={{ color: "#6b7280" }}>{t("liveTabs")}:</span>{" "}
          {files.map((f, i) => (
            <span key={f}>
              {i > 0 && ", "}
              <span style={{ fontWeight: f === live.active_file ? 700 : 400 }}>{f}</span>
            </span>
          ))}
        </div>
      )}
      {unsent > 0 && <div style={{ color: "#a16207" }}>⏳ {t("unsentReports", { n: unsent })}</div>}
    </div>
  );
}

// Band -> chip color, matching the SubmissionsModal grade pills.
function bandColor(band?: string | null): string {
  switch (band) {
    case "excellent": return "#10b981";
    case "good": return "#3b82f6";
    case "review": return "#f59e0b";
    case "flagged": return "#b91c1c";
    case "fail": return "#6b7280";
    default: return "#8b5cf6";
  }
}

function Chip({ children, color = "#e5e7eb" }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      style={{
        background: color,
        color: color === "#e5e7eb" ? "#111" : "white",
        padding: "2px 8px",
        borderRadius: 12,
        fontSize: 12,
      }}
    >
      {children}
    </span>
  );
}
