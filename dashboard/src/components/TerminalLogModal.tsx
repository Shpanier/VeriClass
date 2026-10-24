import { useEffect, useState } from "react";
import { api } from "../api";
import type { Student, TerminalCommand, TerminalFullOutput } from "../types";
import { arrivedLate, eventTime } from "../proctor";
import { useLang } from "../i18n";

/**
 * One student's VeriClass-terminal log: every line they entered, newest first —
 * what ran (exit code, output) and what the plugin refused (and why). Polls
 * every 2s like the other live viewers. "Refused only" narrows to the alerts.
 */
export function TerminalLogModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [rows, setRows] = useState<TerminalCommand[]>([]);
  const [refusedOnly, setRefusedOnly] = useState(false);

  useEffect(() => {
    const tick = () => api.terminalCommands(student.session_id).then(setRows).catch(console.error);
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, [student.session_id]);

  const refused = rows.filter((r) => !r.allowed && !r.syntax_error);
  const shown = refusedOnly ? refused : rows;

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
          width: "min(860px, 94vw)",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <h3 style={{ margin: 0 }}>
            ⌨ {t("terminalLog")} · {student.username}
          </h3>
          <button onClick={onClose}>{t("close")}</button>
        </header>

        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 12, color: "#666", marginTop: 4 }}>
          <span>{t("terminalSummary", { n: rows.length, refused: refused.length })}</span>
          <label style={{ marginInlineStart: "auto", display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
            <input type="checkbox" checked={refusedOnly} onChange={(e) => setRefusedOnly(e.target.checked)} />
            {t("terminalRefusedOnly")}
          </label>
        </div>

        <div style={{ marginTop: 12, flex: 1, overflowY: "auto", border: "1px solid #eee", borderRadius: 6 }}>
          {shown.length === 0 && <p style={{ color: "#888", padding: 12 }}>{t("noTerminalCommands")}</p>}
          {shown.map((r) => (
            <CommandRow key={r.id} r={r} />
          ))}
        </div>
      </div>
    </div>
  );
}

function CommandRow({ r }: { r: TerminalCommand }) {
  const { t } = useLang();
  const [full, setFull] = useState<TerminalFullOutput | null>(null);
  const [loading, setLoading] = useState(false);
  const loadFull = () => {
    setLoading(true);
    api.terminalOutput(r.id).then(setFull).catch(console.error).finally(() => setLoading(false));
  };
  // Only the tail is in the row; the rest came in pieces.
  const hasMore = (r.output_chunks ?? 0) > 0 && (r.output_chars ?? 0) > (r.output_tail?.length ?? 0);
  const blocked = !r.allowed && !r.syntax_error;
  const failed = r.allowed && r.exit_code != null && r.exit_code !== 0;
  const status = blocked
    ? { icon: "🚫", text: t("terminalRefused"), color: "#991b1b" }
    : r.syntax_error
      ? { icon: "⚠", text: t("terminalSyntax"), color: "#92400e" }
      : failed
        ? { icon: "✗", text: t("terminalExit", { n: r.exit_code ?? "" }), color: "#b45309" }
        : { icon: "✓", text: t("terminalExit", { n: r.exit_code ?? 0 }), color: "#047857" };

  return (
    <div
      style={{
        padding: "8px 12px",
        borderBottom: "1px solid #f0f0f0",
        background: blocked ? "#fef2f2" : "white",
      }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
        <span style={{ color: status.color, fontWeight: 700, whiteSpace: "nowrap", fontSize: 12 }}>
          {status.icon} {status.text}
        </span>
        <code
          dir="ltr"
          style={{
            flex: 1,
            fontFamily: "ui-monospace, Menlo, Consolas, monospace",
            fontSize: 13,
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            fontWeight: blocked ? 700 : 500,
            color: blocked ? "#991b1b" : "#111",
          }}
        >
          <span style={{ color: "#9ca3af" }}>{r.cwd ? `${r.cwd}$ ` : "$ "}</span>
          {r.line}
        </code>
        <span style={{ fontSize: 11, color: "#999", whiteSpace: "nowrap" }}>
          {r.duration_ms != null && r.allowed ? `${(r.duration_ms / 1000).toFixed(1)}s · ` : ""}
          {eventTime(r)}
          {arrivedLate(r) && <span style={{ color: "#a16207" }} title={r.created_at}> · {t("arrivedLate")}</span>}
          {r.via === "export" && <span style={{ color: "#7c3aed" }}> · {t("fromExport")}</span>}
          {r.client_os && <span title={r.shell ?? undefined}> · {r.client_os.split(" ")[0]}</span>}
        </span>
      </div>
      {r.reason && (
        <div style={{ fontSize: 12, color: status.color, marginTop: 2 }} dir="ltr">
          {r.reason}
        </div>
      )}
      {r.output_tail && (
        <details style={{ marginTop: 4 }}>
          <summary style={{ fontSize: 12, color: "#6b7280", cursor: "pointer" }}>{t("terminalOutput")}</summary>
          <pre
            dir="ltr"
            style={{
              margin: "4px 0 0",
              padding: 8,
              background: "#0f172a",
              color: "#e2e8f0",
              borderRadius: 4,
              fontSize: 12,
              maxHeight: 240,
              overflow: "auto",
              whiteSpace: "pre-wrap",
            }}
          >
            {full ? full.output : r.output_tail}
          </pre>
          {hasMore && !full && (
            <button onClick={loadFull} disabled={loading} style={{ marginTop: 4, fontSize: 12 }}>
              {loading ? t("loading") : t("showFullOutput", { n: r.output_chars ?? 0 })}
            </button>
          )}
          {full && !full.complete && <div style={{ fontSize: 12, color: "#a16207" }}>{t("outputIncomplete")}</div>}
        </details>
      )}
    </div>
  );
}
