import type { Student } from "../types";
import { useLang } from "../i18n";

/**
 * Loud, sticky red bar that appears at the top of the dashboard whenever a
 * student is currently outside CLion, or has left it at least once this session.
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
  const away = students.filter((s) => s.away);
  const everLeft = students.filter((s) => s.focus_alerts > 0);
  if (away.length === 0 && everLeft.length === 0) return null;

  const totalAlerts = students.reduce((n, s) => n + s.focus_alerts, 0);

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
            ? t("bannerOutside", { n: away.length })
            : t("bannerViolations")}
        </strong>
        <span style={{ opacity: 0.9, fontSize: 13 }}>
          {t("bannerSummary", { leaves: totalAlerts, students: everLeft.length })}
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
            {s.away ? "🔴" : "⚠️"} {s.username} ({s.focus_alerts})
          </button>
        ))}
      </div>
    </div>
  );
}
