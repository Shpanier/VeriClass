import { Siren, TriangleAlert } from "lucide-react";
import type { Student } from "../types";
import { alertTotal, needsAttention } from "../proctor";
import { useLang, type StringKey } from "../i18n";
import { Button } from "./ui";

/**
 * The exam alert bar (IDE plugin), sticky under the top bar. Solid red and
 * pulsing whenever a student needs attention right now (outside the IDE,
 * another window open, not full screen, no signal); a calmer red card when
 * students only raised alerts earlier in the session. Each name is a button
 * that opens that student's exam log. The alert sound is driven by App (so it
 * fires once per new alert, not on every render).
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

  const now = away.length > 0;
  const totalAlerts = students.reduce((n, s) => n + s.focus_alerts, 0);
  const totalBlocked = students.reduce((n, s) => n + (s.terminal_alerts ?? 0), 0);
  const totalIde = students.reduce((n, s) => n + (s.ide_alerts ?? 0), 0);
  const summary = [t("bannerSummary", { leaves: totalAlerts, students: everLeft.length })];
  if (totalBlocked > 0) summary.push(t("bannerBlocked", { n: totalBlocked }));
  if (totalIde > 0) summary.push(t("bannerIde", { n: totalIde }));

  const title = !now ? t("bannerViolations")
    : away.length === 1 ? t("pbOneAttention") : t("bannerAttention", { n: away.length });
  const cls = ["vc-card", "vc-card--danger", "vc-students-alarm", now ? "vc-students-alarm--now proctor-pulse" : ""]
    .filter(Boolean).join(" ");

  return (
    <section className={cls} aria-label={title}>
      <div className="vc-students-alarm__head">
        <span className={now ? "vc-students-alarm__icon proctor-flash" : "vc-students-alarm__icon"} aria-hidden="true">
          <Siren />
        </span>
        <h2 className="vc-students-alarm__title"><span role="alert">{title}</span></h2>
        <span className="vc-students-alarm__summary">{summary.join(" · ")}</span>
      </div>

      <div className="vc-students-alarm__people">
        {(now ? away : everLeft).map((s) => {
          const n = alertTotal(s);
          return (
            <Button
              key={s.session_id}
              size="sm"
              variant={now ? "secondary" : "danger-soft"}
              icon={<TriangleAlert />}
              title={t("openProctorLogTitle")}
              onClick={() => onInspect(s.session_id)}
            >
              <bdi>{s.username}</bdi>
              {needsAttention(s) && s.exam_state && <span>· {t(`state_${s.exam_state}` as StringKey)}</span>}
              {n > 0 && (
                <span className="vc-badge vc-badge--danger">{n === 1 ? t("pbOneAlert") : t("pbAlerts", { n })}</span>
              )}
            </Button>
          );
        })}
      </div>
    </section>
  );
}
