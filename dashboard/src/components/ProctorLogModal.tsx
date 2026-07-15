import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProctorEvent, Student } from "../types";
import { formatAway, isLeaveKind, kindLabel } from "../proctor";
import { useLang, type StringKey } from "../i18n";

const TRANSLATED_KINDS = new Set([
  "exam_started", "focus_lost", "minimized",
  "fullscreen_exited", "focus_regained", "window_restored",
]);

/**
 * Full proctor trail for one student: every time they left or returned to the
 * IDE during the exam, newest first. Polls every 2s like the chat viewer.
 */
export function ProctorLogModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [events, setEvents] = useState<ProctorEvent[]>([]);

  useEffect(() => {
    const tick = () =>
      api.proctorEvents(student.session_id).then(setEvents).catch(console.error);
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, [student.session_id]);

  const leaves = events.filter((e) => isLeaveKind(e.kind)).length;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "grid",
        placeItems: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          padding: 20,
          borderRadius: 8,
          width: 640,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>
            🎥 {t("proctorLog")} · {student.username}
            {student.away && (
              <span style={{ color: "#b91c1c", marginInlineStart: 8 }} className="proctor-flash">
                · {t("outsideIdeCaps")}
              </span>
            )}
          </h3>
          <button onClick={onClose}>{t("close")}</button>
        </header>

        <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
          {t("leaveEventsRecorded", { n: leaves })}
        </div>

        <div
          style={{
            marginTop: 12,
            flex: 1,
            overflowY: "auto",
            border: "1px solid #eee",
            borderRadius: 6,
          }}
        >
          {events.length === 0 && (
            <p style={{ color: "#888", padding: 12 }}>{t("noProctorEvents")}</p>
          )}
          {events.map((e) => (
            <EventRow key={e.id} e={e} />
          ))}
        </div>
      </div>
    </div>
  );
}

function EventRow({ e }: { e: ProctorEvent }) {
  const { t } = useLang();
  const leave = isLeaveKind(e.kind);
  const returned = e.kind === "focus_regained" || e.kind === "window_restored";
  const icon = leave ? "🔴" : returned ? "🟢" : "•";
  const label = TRANSLATED_KINDS.has(e.kind)
    ? t(`kind_${e.kind}` as StringKey)
    : kindLabel(e.kind);
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "baseline",
        padding: "8px 12px",
        borderBottom: "1px solid #f0f0f0",
        background: leave ? "#fef2f2" : "white",
      }}
    >
      <span>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: leave ? 700 : 500, color: leave ? "#991b1b" : "#111" }}>
          {label}
          {e.away_ms != null && (
            <span style={{ fontWeight: 400, color: "#666" }}> · {t("awayFor", { d: formatAway(e.away_ms) })}</span>
          )}
        </div>
        {e.detail && <div style={{ fontSize: 12, color: "#666" }}>{e.detail}</div>}
      </div>
      <span style={{ fontSize: 11, color: "#999", whiteSpace: "nowrap" }}>{e.created_at}</span>
    </div>
  );
}
