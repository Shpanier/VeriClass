import type { ParamLabel, Student } from "../types";
import { renderParams } from "../params";
import { useLang } from "../i18n";

interface Props {
  students: Student[];
  paramLabels?: ParamLabel[];
  onModeChange: (sessionId: string, mode: "mentor" | "coding_partner") => void;
  onAskThem: (sessionId: string) => void;
  onViewChat: (sessionId: string) => void;
  onProctorLog: (sessionId: string) => void;
}

export function StudentGrid({ students, paramLabels, onModeChange, onAskThem, onViewChat, onProctorLog }: Props) {
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
}: {
  s: Student;
  paramLabels?: ParamLabel[];
  onModeChange: Props["onModeChange"];
  onAskThem: Props["onAskThem"];
  onViewChat: Props["onViewChat"];
  onProctorLog: Props["onProctorLog"];
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
  const examClient = s.last_focus_kind != null || s.focus_alerts > 0;
  return (
    <div
      className={s.away ? "proctor-pulse" : undefined}
      style={{
        border: `${s.away ? 2 : 1}px solid ${s.away ? "#b91c1c" : "#ddd"}`,
        borderRadius: 8,
        padding: 16,
        background: s.away ? "#fef2f2" : "white",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            background: s.away ? "#b91c1c" : "#3b82f6",
            color: "white",
            display: "grid",
            placeItems: "center",
            fontWeight: 600,
          }}
        >
          {initials}
        </div>
        <strong>{s.username}</strong>
        {s.away ? (
          <span
            className="proctor-flash"
            style={{
              marginLeft: "auto",
              background: "#b91c1c",
              color: "white",
              fontSize: 11,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 999,
            }}
          >
            🔴 {t("outsideIde")}
          </span>
        ) : (
          s.focus_alerts > 0 && (
            <span
              style={{
                marginLeft: "auto",
                background: "#f59e0b",
                color: "white",
                fontSize: 11,
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: 999,
              }}
            >
              ⚠ {t("leftTimes", { n: s.focus_alerts })}
            </span>
          )
        )}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "8px 0" }}>
        <Chip>{s.exercise}</Chip>
        <Chip>{s.variant}</Chip>
        <Chip color={s.mode === "mentor" ? "#10b981" : "#f59e0b"}>
          {s.mode === "mentor" ? t("mentor") : t("codingPartner")}
        </Chip>
        <Chip>🔎 {s.probe_count}</Chip>
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
        {examClient && (
          <button
            onClick={() => onProctorLog(s.session_id)}
            title={t("openProctorLogTitle")}
            style={{
              background: s.focus_alerts > 0 ? "#b91c1c" : "#6b7280",
              color: "white",
              border: "none",
              borderRadius: 6,
              padding: "6px 12px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            🎥 {s.focus_alerts > 0 ? t("alerts", { n: s.focus_alerts }) : t("proctorLog")}
          </button>
        )}
      </div>
    </div>
  );
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
