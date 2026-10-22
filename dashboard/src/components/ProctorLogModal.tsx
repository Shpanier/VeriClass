import { useEffect, useState } from "react";
import { api } from "../api";
import type { Paste, ProctorEvent, Student } from "../types";
import {
  arrivedLate, eventTime, formatAway, isIdeAlertKind, isLeaveKind, isTerminalAlertKind, kindLabel,
} from "../proctor";
import { useLang, type StringKey } from "../i18n";

const TRANSLATED_KINDS = new Set([
  "exam_started", "focus_lost", "minimized",
  "fullscreen_exited", "focus_regained", "window_restored",
  "blocked_command", "stock_terminal_opened",
  "fullscreen_restored", "tool_window_opened", "other_window_opened", "other_window_closed",
  "file_opened", "paste_external", "paste_internal",
  "other_app_in_front", "window_unmaximized", "window_maximized",
]);

/**
 * Full proctor trail for one student, newest first: leaving and returning to
 * the IDE, panels and windows that aren't allowed (with how they were opened),
 * editor tabs, and pastes with the pasted text. Polls every 2s like the chat viewer.
 */
export function ProctorLogModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [events, setEvents] = useState<ProctorEvent[]>([]);
  const [pastes, setPastes] = useState<Paste[]>([]);

  useEffect(() => {
    const tick = () => {
      api.proctorEvents(student.session_id).then(setEvents).catch(console.error);
      api.pastes(student.session_id).then(setPastes).catch(console.error);
    };
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
          width: 720,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>
            🎥 {t("proctorLog")} · {student.username}
            {student.exam_state && student.exam_state !== "ok" && (
              <span style={{ color: "#b91c1c", marginInlineStart: 8 }} className="proctor-flash">
                · {t(`state_${student.exam_state}` as StringKey)}
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

        <details style={{ marginTop: 12 }} open={pastes.some((p) => p.source === "outside")}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>📋 {t("pastesTitle", { n: pastes.length })}</summary>
          <div style={{ maxHeight: "35vh", overflowY: "auto", border: "1px solid #eee", borderRadius: 6, marginTop: 6 }}>
            {pastes.length === 0 && <p style={{ color: "#888", padding: 12, margin: 0 }}>{t("noPastes")}</p>}
            {pastes.map((p) => (
              <PasteRow key={p.id} p={p} />
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}

function EventRow({ e }: { e: ProctorEvent }) {
  const { t } = useLang();
  const terminal = isTerminalAlertKind(e.kind);
  const ide = isIdeAlertKind(e.kind);
  // Terminal and in-IDE violations get the same red treatment as leaving the IDE.
  const leave = isLeaveKind(e.kind) || terminal || ide;
  const returned = ["focus_regained", "window_restored", "fullscreen_restored", "other_window_closed"].includes(e.kind);
  const icon = terminal ? "🚫" : e.kind === "paste_external" ? "📋" : ide ? "🟠" : leave ? "🔴" : returned ? "🟢" : "•";
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
        {e.detail && (
          <div
            dir={terminal ? "ltr" : "auto"}
            style={{
              fontSize: 12,
              color: "#666",
              fontFamily: terminal ? "ui-monospace, Menlo, Consolas, monospace" : undefined,
            }}
          >
            {e.detail}
          </div>
        )}
      </div>
      <span style={{ fontSize: 11, color: "#999", whiteSpace: "nowrap", textAlign: "end" }}>
        {eventTime(e)}
        {arrivedLate(e) && <div style={{ color: "#a16207" }} title={e.created_at}>{t("arrivedLate")}</div>}
        {e.via === "export" && <div style={{ color: "#7c3aed" }}>{t("fromExport")}</div>}
      </span>
    </div>
  );
}

function PasteRow({ p }: { p: Paste }) {
  const { t } = useLang();
  const outside = p.source === "outside";
  return (
    <div style={{ padding: "8px 12px", borderBottom: "1px solid #f0f0f0", background: outside ? "#fef2f2" : "white" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 13 }}>
        <strong style={{ color: outside ? "#991b1b" : "#111" }}>
          {t(`pasteFrom_${p.source}` as StringKey)} · {t(`pasteInto_${p.target}` as StringKey)}
        </strong>
        {p.file && <code dir="ltr" style={{ fontSize: 12, color: "#6b7280" }}>{p.file}</code>}
        <span style={{ fontSize: 12, color: "#6b7280" }}>{t("pasteSize", { chars: p.chars, lines: p.lines })}</span>
        <span style={{ marginInlineStart: "auto", fontSize: 11, color: "#999" }}>
          {eventTime(p)}
          {p.via === "export" && <span style={{ color: "#7c3aed" }}> · {t("fromExport")}</span>}
        </span>
      </div>
      <pre
        dir="ltr"
        style={{
          margin: "4px 0 0", padding: 8, background: "#0f172a", color: "#e2e8f0", borderRadius: 4,
          fontSize: 12, maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}
      >
        {p.text}
      </pre>
    </div>
  );
}
