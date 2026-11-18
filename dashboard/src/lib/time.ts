import type { Lang } from "../types";

/** The server writes times in UTC without saying so ("2026-11-13 13:48:10").
 *  Read them as UTC; a value that carries its own zone is taken as it is. */
export function parseServerTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  let s = value.trim().replace(" ", "T");
  if (!/[zZ]$|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const locale = (lang: Lang) => (lang === "he" ? "he-IL" : "en-GB");

export function formatClock(d: Date, lang: Lang): string {
  return d.toLocaleTimeString(locale(lang), { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function formatDateTime(d: Date, lang: Lang): string {
  return d.toLocaleString(locale(lang), {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

/** "12 Nov 2026" (the day only). */
export function formatDate(d: Date, lang: Lang): string {
  return d.toLocaleDateString(locale(lang), { day: "numeric", month: "short", year: "numeric" });
}

/** "just now", "3 min ago", "2 hours ago"; older than a day: the date and time. */
export function relativeTime(d: Date, lang: Lang, now: Date = new Date()): string {
  const sec = Math.round((now.getTime() - d.getTime()) / 1000);
  if (sec < 45) return lang === "he" ? "עכשיו" : "just now";
  const rtf = new Intl.RelativeTimeFormat(locale(lang), { numeric: "always", style: "short" });
  if (sec < 3600) return rtf.format(-Math.round(sec / 60), "minute");
  if (sec < 86_400) return rtf.format(-Math.round(sec / 3600), "hour");
  return formatDateTime(d, lang);
}
