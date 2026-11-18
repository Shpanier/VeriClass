import { useEffect, useState } from "react";
import type { ExerciseSummary, Lang } from "../types";
import { parseServerTime } from "./time";

/** How the dashboard orders exercises, everywhere it lists them (the Exercises
 *  tab, the live exercise picker, a course's exercises, a new meeting). The
 *  lecturer picks it in the Exercises tab; it is kept in this browser. */
export type ExerciseSort = "added-desc" | "added-asc" | "changed-desc" | "name-asc" | "name-desc";
export const EXERCISE_SORTS: ExerciseSort[] = ["added-desc", "added-asc", "changed-desc", "name-asc", "name-desc"];

/** The Exercises tab's date filter: added or changed in this period. */
export type DateRange = "any" | "today" | "7d" | "30d" | "custom";
export const DATE_RANGES: DateRange[] = ["any", "today", "7d", "30d", "custom"];

const SORT_KEY = "vc.exercises.sort";
const SORT_EVENT = "vc-exercise-sort";
const DEFAULT_SORT: ExerciseSort = "added-desc";

function savedSort(): ExerciseSort {
  try {
    const v = localStorage.getItem(SORT_KEY);
    if (v && (EXERCISE_SORTS as string[]).includes(v)) return v as ExerciseSort;
  } catch { /* no storage: the default */ }
  return DEFAULT_SORT;
}

/** The chosen order, shared by every list on the page (and kept for next time). */
export function useExerciseSort(): [ExerciseSort, (s: ExerciseSort) => void] {
  const [sort, setSort] = useState<ExerciseSort>(savedSort);
  useEffect(() => {
    const follow = (e: Event) => setSort((e as CustomEvent<ExerciseSort>).detail);
    window.addEventListener(SORT_EVENT, follow);
    return () => window.removeEventListener(SORT_EVENT, follow);
  }, []);
  const choose = (s: ExerciseSort) => {
    try { localStorage.setItem(SORT_KEY, s); } catch { /* kept for this page only */ }
    window.dispatchEvent(new CustomEvent(SORT_EVENT, { detail: s }));
  };
  return [sort, choose];
}

type Titled = Pick<ExerciseSummary, "exercise_id" | "title_en" | "title_he">;

export function exerciseTitle(ex: Titled, lang: Lang): string {
  return (lang === "he" ? ex.title_he || ex.title_en : ex.title_en) || ex.exercise_id;
}

const time = (value?: string | null) => parseServerTime(value)?.getTime() ?? null;

/** A sorted copy. Dates: missing ones last; equal ones by name. Names: "Lab 2"
 *  before "Lab 10", Hebrew and English each in their own alphabet. */
export function sortExercises<T extends ExerciseSummary>(list: T[], sort: ExerciseSort, lang: Lang): T[] {
  const collator = new Intl.Collator(lang === "he" ? "he" : "en", { numeric: true, sensitivity: "base" });
  const byName = (a: T, b: T) =>
    collator.compare(exerciseTitle(a, lang), exerciseTitle(b, lang)) || a.exercise_id.localeCompare(b.exercise_id);
  const byDate = (key: "added_at" | "changed_at", dir: 1 | -1) => (a: T, b: T) => {
    const x = time(a[key]);
    const y = time(b[key]);
    if (x === null || y === null) return x === y ? byName(a, b) : x === null ? 1 : -1;
    return (x - y) * dir || byName(a, b);
  };
  const compare = {
    "added-desc": byDate("added_at", -1),
    "added-asc": byDate("added_at", 1),
    "changed-desc": byDate("changed_at", -1),
    "name-asc": byName,
    "name-desc": (a: T, b: T) => byName(b, a),
  }[sort];
  return [...list].sort(compare);
}

/** Local midnight of a "YYYY-MM-DD" date (an <input type="date"> value). */
function dayStart(day: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime() : null;
}

/** Whether the exercise was added or changed in the period. A custom period
 *  takes whole days, both ends included; an end left empty is open. */
export function inDateRange(ex: ExerciseSummary, range: DateRange, from = "", to = "", now = new Date()): boolean {
  if (range === "any") return true;
  let start: number | null = null;
  let end: number | null = null;
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (range === "today") start = midnight;
  else if (range === "7d") start = midnight - 6 * 86_400_000;
  else if (range === "30d") start = midnight - 29 * 86_400_000;
  else {
    start = dayStart(from);
    const last = dayStart(to);
    end = last === null ? null : last + 86_400_000;
    if (start === null && end === null) return true;
  }
  return [time(ex.added_at), time(ex.changed_at)].some(
    (t) => t !== null && (start === null || t >= start) && (end === null || t < end));
}
