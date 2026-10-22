import { useState } from "react";
import { api } from "../api";
import type { TraceVerifyResult } from "../types";
import { useLang, type StringKey } from "../i18n";

/**
 * A student's "Export my log" CSV, checked by the backend: was any row edited,
 * removed or reordered (signed chain), was the file cut short, and which rows
 * never reached the server. Those can be imported; they're then marked as
 * coming from the export everywhere they show.
 */
export function VerifyTraceModal({ onClose }: { onClose: () => void }) {
  const { t } = useLang();
  const [csv, setCsv] = useState<string | null>(null);
  const [result, setResult] = useState<TraceVerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (text: string, importMissing: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.verifyTrace(text, importMissing));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    const text = await f.text();
    setCsv(text);
    setResult(null);
    void run(text, false);
  };

  const missing = result?.missing_on_server ?? 0;

  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "grid", placeItems: "center", zIndex: 100 }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white", padding: 20, borderRadius: 8, width: 860, maxWidth: "95vw",
          maxHeight: "88vh", display: "flex", flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>{t("verifyTitle")}</h3>
          <button onClick={onClose}>{t("close")}</button>
        </header>
        <p style={{ fontSize: 13, color: "#4b5563" }}>{t("verifyHint")}</p>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
          <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e.target.files?.[0])} />
        </label>

        {busy && <p>{t("loading")}</p>}
        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

        {result && (
          <>
            <div
              style={{
                marginTop: 12, padding: "10px 12px", borderRadius: 6, fontWeight: 600,
                background: result.ok ? "#ecfdf5" : "#fef2f2", color: result.ok ? "#047857" : "#991b1b",
              }}
            >
              {result.ok
                ? t("verifyOk", { n: result.valid_rows ?? 0, student: result.student ?? "?" })
                : t("verifyBad", { error: result.error ?? "" })}
              {!result.ok && result.student && <span style={{ fontWeight: 400 }}> · {result.student}</span>}
            </div>
            <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "10px 0", fontSize: 13 }}>
              {(result.imported ?? 0) > 0 ? (
                <span style={{ color: "#7c3aed", fontWeight: 600 }}>{t("verifyImported", { n: result.imported ?? 0 })}</span>
              ) : missing > 0 ? (
                <>
                  <span style={{ color: "#a16207", fontWeight: 600 }}>{t("verifyMissing", { n: missing })}</span>
                  <button disabled={busy || !csv} onClick={() => csv && run(csv, true)}>
                    {t("verifyImport", { n: missing })}
                  </button>
                </>
              ) : (
                result.rows.length > 0 && <span style={{ color: "#047857" }}>{t("verifyNothingMissing")}</span>
              )}
            </div>
            <div style={{ flex: 1, overflowY: "auto", border: "1px solid #eee", borderRadius: 6 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead style={{ position: "sticky", top: 0, background: "#f9fafb" }}>
                  <tr>
                    {(["colRow", "colTime", "colKind", "colWhat", "colSigned", "colOnServer"] as StringKey[]).map((k) => (
                      <th key={k} style={{ textAlign: "start", padding: "6px 8px", borderBottom: "1px solid #e5e7eb" }}>{t(k)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((r, i) => (
                    <tr key={i} style={{ background: r.valid ? undefined : "#fef2f2" }}>
                      <td style={cell}>{r.seq ?? "?"}</td>
                      <td style={{ ...cell, whiteSpace: "nowrap" }}>{r.at_utc}</td>
                      <td style={cell}>{TRACE_KINDS.has(r.kind) ? t(`traceKind_${r.kind}` as StringKey) : r.kind}</td>
                      <td style={{ ...cell, fontFamily: "ui-monospace, Menlo, Consolas, monospace" }} dir="auto">{r.summary}</td>
                      <td style={cell}>{r.valid ? "✓" : "✗"}</td>
                      <td style={cell}>
                        {r.imported ? "⬆" : r.on_server === true ? "✓" : r.on_server === false ? "—" : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const TRACE_KINDS = new Set(["terminal", "proctor", "paste", "chat_user", "chat_tutor", "export_end"]);

const cell = { padding: "4px 8px", borderBottom: "1px solid #f3f4f6", verticalAlign: "top" } as const;
