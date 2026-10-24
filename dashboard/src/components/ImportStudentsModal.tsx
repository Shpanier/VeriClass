import { useState } from "react";
import { api } from "../api";
import type { Course, RosterResult } from "../types";
import { useLang } from "../i18n";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/Button";
import { controlStyle } from "./ui/Field";

/** The file's bytes as base64, so a Hebrew CSV saved by Excel keeps its encoding. */
async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

/** Save text as a file (UTF-8 with a BOM, so Excel shows Hebrew correctly). */
function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Courses tab: a student list from CSV (backend/roster.py). Preview first, then
// import; the new students' login codes can be downloaded as a CSV.
export function ImportStudentsModal({
  courses,
  onClose,
  onImported,
}: {
  courses: Course[];
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useLang();
  const [file, setFile] = useState<File | null>(null);
  const [courseId, setCourseId] = useState<string>(courses.length === 1 ? courses[0].course_id : "");
  const [result, setResult] = useState<RosterResult | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.importStudents(await fileBase64(file), courseId || null, dryRun);
      setResult(r);
      if (!dryRun) {
        setDone(true);
        onImported();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const stamp = new Date().toISOString().slice(0, 10);

  return (
    <Modal onClose={onClose} width={860}>
      <h3 style={{ marginTop: 0 }}>{t("importStudentsTitle")}</h3>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0 }}>{t("importStudentsIntro")}</p>
      <pre dir="ltr" style={{ background: "#f9fafb", padding: 8, borderRadius: 6, fontSize: 12, margin: "0 0 12px" }}>
        name,email,student_id,course,group{"\n"}Israel Israeli,israel@example.ac.il,012345678,dl-2026,A
      </pre>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <input
          type="file"
          accept=".csv,.txt,text/csv"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setDone(false); }}
          disabled={done}
        />
        <select
          value={courseId}
          onChange={(e) => { setCourseId(e.target.value); setResult(null); }}
          disabled={done}
          style={{ ...controlStyle, width: 260 }}
          aria-label={t("importCourse")}
        >
          <option value="">{t("importNoCourse")}</option>
          {courses.map((c) => (
            <option key={c.course_id} value={c.course_id}>{c.name} ({c.course_id})</option>
          ))}
        </select>
        {!done && (
          <>
            <Button disabled={!file || busy} onClick={() => run(true)}>{t("importPreview")}</Button>
            <Button
              variant="primary"
              disabled={!result || busy || result.counts.new + result.counts.existing === 0}
              onClick={() => run(false)}
            >
              {t("importDo")}
            </Button>
          </>
        )}
      </div>

      {error && <p style={{ color: "#b91c1c", fontSize: 13 }}>{error}</p>}

      {result && (
        <>
          <p style={{ fontSize: 13, fontWeight: 600 }}>
            {t(done ? "importDone" : "importSummary", {
              n: result.counts.new, e: result.counts.existing, x: result.counts.errors,
            })}
          </p>
          {done && result.codes_csv && (
            <Button variant="neutral" onClick={() => download(`login-codes-${courseId || "students"}-${stamp}.csv`, result.codes_csv!)}
                    style={{ marginBottom: 10 }}>
              {t("importDownloadCodes")}
            </Button>
          )}
          <div style={{ maxHeight: 360, overflow: "auto", border: "1px solid #e5e7eb", borderRadius: 6 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  <th style={th}>#</th>
                  <th style={th}>{t("colName")}</th>
                  <th style={th}>Email</th>
                  <th style={th}>{t("importCourse")}</th>
                  <th style={th}>{t("importStatus")}</th>
                  {done && <th style={th}>{t("colUsername")}</th>}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={r.line} style={{ borderTop: "1px solid #f3f4f6" }}>
                    <td style={td}>{r.line}</td>
                    <td style={td} dir="auto">{r.username ?? r.name}</td>
                    <td style={td} dir="ltr">{r.email ?? ""}</td>
                    <td style={td}>{r.course ?? ""}</td>
                    <td style={{ ...td, color: r.error ? "#b91c1c" : r.status === "new" ? "#166534" : "#374151" }}>
                      {r.error ?? (r.status === "new" ? t("importNew") : t("importExisting"))}
                    </td>
                    {done && <td style={td}><code dir="ltr">{r.code ?? ""}</code></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
        <Button onClick={onClose}>{t("close")}</Button>
      </div>
    </Modal>
  );
}

const th: React.CSSProperties = { padding: "6px 8px", textAlign: "start", fontWeight: 600 };
const td: React.CSSProperties = { padding: "4px 8px", verticalAlign: "top" };
