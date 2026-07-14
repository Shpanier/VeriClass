import { useEffect, useState } from "react";
import { api } from "../api";
import type { GradeRecommendation, Student, Submission } from "../types";
import { useLang, type StringKey } from "../i18n";

// Band -> pill colors. `flagged` is the correct-but-plug-and-play case the
// teacher most needs to see, so it reads red like the proctor alerts.
const BAND_STYLE: Record<string, { bg: string; fg: string }> = {
  excellent: { bg: "#10b981", fg: "white" },
  good: { bg: "#3b82f6", fg: "white" },
  review: { bg: "#f59e0b", fg: "white" },
  flagged: { bg: "#b91c1c", fg: "white" },
  fail: { bg: "#6b7280", fg: "white" },
};

function bandStyle(band: string | null | undefined) {
  return (band && BAND_STYLE[band]) || { bg: "#9ca3af", fg: "white" };
}

/**
 * Every "Send to teacher" submission for one student, newest first. Each shows
 * the source file they sent and the console output captured at that moment.
 * Polls every 3s so a submission made during class appears without a refresh.
 */
export function SubmissionsModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [subs, setSubs] = useState<Submission[]>([]);

  useEffect(() => {
    const tick = () =>
      api.submissions(student.session_id).then(setSubs).catch(console.error);
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [student.session_id]);

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
          width: 820,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>
            📤 {t("submissions")} · {student.username} · {student.variant}
          </h3>
          <button onClick={onClose}>{t("close")}</button>
        </header>

        <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
          {t("submissionsFooter", { n: subs.length })}
        </div>

        <div style={{ marginTop: 12, flex: 1, overflowY: "auto" }}>
          <GradePanel sessionId={student.session_id} />
          {subs.length === 0 && (
            <p style={{ color: "#888", padding: 12 }}>{t("noSubmissions")}</p>
          )}
          {subs.map((sub) => (
            <SubmissionCard key={sub.id} sub={sub} />
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * The recommended grade for a session: correctness (from the real compile/run)
 * blended 30/70 with the LLM's wise-use judgment. Computed on demand — the
 * teacher clicks "Recommend grade" — and overridable. Mirrors the probe
 * auto-grade + override pattern.
 */
function GradePanel({ sessionId }: { sessionId: string }) {
  const { t, lang } = useLang();
  const [grade, setGrade] = useState<GradeRecommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ov, setOv] = useState("");

  useEffect(() => {
    api.gradeFor(sessionId).then(setGrade).catch(() => {});
  }, [sessionId]);

  const compute = () => {
    setLoading(true);
    setErr(null);
    api
      .recommendGrade(sessionId, lang)
      .then((g) => setGrade(g))
      .catch((e) => setErr(String(e?.message || e)))
      .finally(() => setLoading(false));
  };

  const saveOverride = () => {
    const n = Number(ov);
    if (Number.isNaN(n) || n < 0 || n > 100) return;
    api
      .overrideGrade(sessionId, n)
      .then(() => api.gradeFor(sessionId).then(setGrade))
      .then(() => setOv(""))
      .catch((e) => setErr(String(e?.message || e)));
  };

  const bs = bandStyle(grade?.band);
  const bandKey = (grade?.band ? `band_${grade.band}` : "") as StringKey;

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        marginBottom: 14,
        padding: 12,
        background: "#fbfaff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <strong style={{ fontSize: 13 }}>🎯 {t("recommendedGrade")}</strong>
        {grade?.band && (
          <span
            style={{
              background: bs.bg,
              color: bs.fg,
              fontSize: 11,
              fontWeight: 700,
              padding: "2px 10px",
              borderRadius: 999,
            }}
          >
            {t(bandKey)}
          </span>
        )}
        <button
          onClick={compute}
          disabled={loading}
          style={{
            marginLeft: "auto",
            background: loading ? "#a78bda" : "#7c3aed",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "6px 12px",
            fontWeight: 600,
            cursor: loading ? "default" : "pointer",
          }}
        >
          {loading ? t("recommending") : grade ? t("recomputeGrade") : t("recommendGrade")}
        </button>
      </div>

      {err && <div style={{ color: "#b91c1c", fontSize: 12, marginTop: 8 }}>{err}</div>}

      {!grade && !loading && !err && (
        <p style={{ color: "#6b7280", fontSize: 13, margin: "10px 2px 2px" }}>{t("noGradeYet")}</p>
      )}

      {grade && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", gap: 18, alignItems: "flex-end", flexWrap: "wrap" }}>
            <BigScore
              value={grade.override_grade ?? grade.recommended}
              overridden={grade.override_grade != null}
            />
            <SubScore label={t("correctness")} value={grade.correctness} />
            <SubScore label={t("wiseUse")} value={grade.wise_use} accent="#7c3aed" />
          </div>

          {grade.wise_use == null && (
            <div style={{ color: "#b45309", fontSize: 12, marginTop: 8 }}>{t("gradeUnavailable")}</div>
          )}

          {grade.rationale && (
            <div style={{ marginTop: 10, fontSize: 13, color: "#374151" }}>
              <span style={{ color: "#6b7280" }}>{t("gradeWhy")}: </span>
              {grade.rationale}
            </div>
          )}

          {grade.components?.signals && grade.components.signals.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingInlineStart: 18, fontSize: 12.5, lineHeight: 1.6 }}>
              {grade.components.signals.map((sig, i) => (
                <li key={i} style={{ color: sig.trim().startsWith("-") ? "#b91c1c" : "#047857" }}>
                  {sig.replace(/^[+-]\s*/, "")}
                </li>
              ))}
            </ul>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}>
            <span style={{ fontSize: 12, color: "#6b7280" }}>{t("overrideLabel")}:</span>
            <input
              type="number"
              min={0}
              max={100}
              value={ov}
              onChange={(e) => setOv(e.target.value)}
              placeholder="0–100"
              style={{ width: 80, padding: "4px 6px", border: "1px solid #d1d5db", borderRadius: 6 }}
            />
            <button
              onClick={saveOverride}
              disabled={ov === ""}
              style={{
                background: "#374151",
                color: "white",
                border: "none",
                borderRadius: 6,
                padding: "5px 12px",
                fontWeight: 600,
                cursor: ov === "" ? "default" : "pointer",
                opacity: ov === "" ? 0.6 : 1,
              }}
            >
              {t("saveOverride")}
            </button>
            {grade.override_grade != null && (
              <span style={{ fontSize: 12, color: "#374151" }}>
                {t("gradeOverridden", { g: grade.override_grade })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function BigScore({ value, overridden }: { value: number | null; overridden: boolean }) {
  return (
    <div style={{ lineHeight: 1 }}>
      <span style={{ fontSize: 34, fontWeight: 800, color: overridden ? "#374151" : "#111" }}>
        {value == null ? "—" : Math.round(value)}
      </span>
      <span style={{ fontSize: 15, color: "#9ca3af" }}> / 100</span>
    </div>
  );
}

function SubScore({ label, value, accent = "#111" }: { label: string; value: number | null; accent?: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#6b7280" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: accent }}>
        {value == null ? "—" : Math.round(value)}
      </div>
    </div>
  );
}

function SubmissionCard({ sub }: { sub: Submission }) {
  const { t } = useLang();
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, marginBottom: 14, overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          padding: "8px 12px",
          background: "#f9fafb",
          borderBottom: "1px solid #e5e7eb",
        }}
      >
        <strong style={{ fontSize: 13 }}>
          📄 {sub.filename || "source"}
          {sub.language && <span style={{ color: "#9ca3af", fontWeight: 400 }}> · {sub.language}</span>}
        </strong>
        <span style={{ fontSize: 11, color: "#999" }}>{sub.created_at}</span>
      </div>

      {(sub.compile_ok === 0 || (sub.run_report && sub.run_report.length > 0)) && (
        <div style={{ display: "flex", gap: 8, padding: "6px 12px", fontSize: 11.5, alignItems: "center", flexWrap: "wrap" }}>
          {sub.compile_ok === 0 && (
            <span style={{ background: "#b91c1c", color: "white", padding: "1px 8px", borderRadius: 999, fontWeight: 700 }}>
              ⚠ {t("compileFailed")}
            </span>
          )}
          {sub.run_report && sub.run_report.length > 0 && (
            <span style={{ color: "#374151" }}>
              ✓ {sub.run_report.filter((c) => c.passed).length}/{sub.run_report.length}
            </span>
          )}
          {sub.run_report?.map((c, i) => (
            <span
              key={i}
              title={`${c.input} → ${c.actual} (expected ${c.expected})`}
              style={{ color: c.passed ? "#047857" : "#b91c1c", fontFamily: "ui-monospace, monospace" }}
            >
              {c.passed ? "✓" : "✗"}
            </span>
          ))}
        </div>
      )}

      <Section label={t("sourceCode")} text={sub.source_code} background="#fafafa" />
      <Section
        label={t("consoleOutput")}
        text={sub.console_output || ""}
        placeholder={t("noConsole")}
        background="#0b1021"
        color="#d1d5db"
      />
    </div>
  );
}

function Section({
  label,
  text,
  placeholder,
  background,
  color = "#111",
}: {
  label: string;
  text: string;
  placeholder?: string;
  background: string;
  color?: string;
}) {
  const empty = text.trim().length === 0;
  return (
    <div>
      <div style={{ fontSize: 11, color: "#6b7280", padding: "6px 12px 0" }}>{label}</div>
      <pre
        style={{
          margin: 0,
          padding: "8px 12px 12px",
          maxHeight: 260,
          overflow: "auto",
          background,
          color: empty ? "#9ca3af" : color,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 12.5,
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {empty ? placeholder ?? "" : text}
      </pre>
    </div>
  );
}
