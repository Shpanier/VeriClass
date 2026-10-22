import type { Student } from "../types";
import { alertTotal, needsAttention, STATE_STYLE } from "../proctor";
import { useLang, type StringKey } from "../i18n";

/**
 * Loud, sticky red bar that appears at the top of the dashboard whenever a
 * student needs attention right now (outside the IDE, another window open, not
 * full screen, no signal), or has raised an alert at least once this session.
 * Each name is a button that opens that student's proctor log. The accompanying
 * alert sound is driven by App (so it fires once per new violation, not on
 * every render).
 */
export function ProctorBanner({
  students,
  onInspect,
}: {
  students: Student[];
  onInspect: (sessionId: string) => void;
}) {
  const { t } = useLang();
  const away = students.filter(needsAttention);
  const everLeft = students.filter((s) => alertTotal(s) > 0);
  if (away.length === 0 && everLeft.length === 0) return null;

  const totalAlerts = students.reduce((n, s) => n + s.focus_alerts, 0);
  const totalBlocked = students.reduce((n, s) => n + (s.terminal_alerts ?? 0), 0);
  const totalIde = students.reduce((n, s) => n + (s.ide_alerts ?? 0), 0);

  return (
    <div
      className={away.length > 0 ? "proctor-pulse" : undefined}
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        background: away.length > 0 ? "#b91c1c" : "#9a3412",
        color: "white",
        borderRadius: 10,
        padding: "12px 16px",
        marginBottom: 16,
        boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 20 }} className={away.length > 0 ? "proctor-flash" : undefined}>
          🚨
        </span>
        <strong style={{ fontSize: 16 }}>
          {away.length > 0
            ? t("bannerAttention", { n: away.length })
            : t("bannerViolations")}
        </strong>
        <span style={{ opacity: 0.9, fontSize: 13 }}>
          {t("bannerSummary", { leaves: totalAlerts, students: everLeft.length })}
          {totalBlocked > 0 && <> {t("bannerBlocked", { n: totalBlocked })}</>}
          {totalIde > 0 && <> {t("bannerIde", { n: totalIde })}</>}
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
        {(away.length > 0 ? away : everLeft).map((s) => (
          <button
            key={s.session_id}
            onClick={() => onInspect(s.session_id)}
            title={t("openProctorLogTitle")}
            style={{
              background: "rgba(255,255,255,0.16)",
              color: "white",
              border: "1px solid rgba(255,255,255,0.5)",
              borderRadius: 999,
              padding: "4px 12px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {needsAttention(s) && s.exam_state ? STATE_STYLE[s.exam_state].icon : "⚠️"} {s.username}
            {needsAttention(s) && s.exam_state && <> · {t(`state_${s.exam_state}` as StringKey)}</>} ({alertTotal(s)})
          </button>
        ))}
      </div>
    </div>
  );
}
