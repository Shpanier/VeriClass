import { useEffect, useState } from "react";
import { useLang } from "../../i18n";
import { formatClock, formatDateTime, parseServerTime, relativeTime } from "../../lib/time";

/** A server timestamp, in the lecturer's own time zone.
 *    <Time value={s.last_active_at} />            "3 min ago" (hover: the full date and time)
 *    <Time value={e.created_at} mode="clock" />   "14:05:09"
 *    <Time value={m.created_at} mode="full" />    "13 Nov 2026, 14:05" */
export function Time({ value, mode = "relative" }: {
  value: string | null | undefined;
  mode?: "relative" | "clock" | "full";
}) {
  const { lang } = useLang();
  const [, tick] = useState(0);
  useEffect(() => {
    if (mode !== "relative") return;
    const id = window.setInterval(() => tick((n) => n + 1), 30_000);
    return () => window.clearInterval(id);
  }, [mode]);
  const date = parseServerTime(value);
  if (!date) return <span>{value ?? ""}</span>;
  const full = formatDateTime(date, lang);
  const text = mode === "clock" ? formatClock(date, lang) : mode === "full" ? full : relativeTime(date, lang);
  return <time dateTime={date.toISOString()} title={full} dir="auto">{text}</time>;
}
