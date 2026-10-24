import type { ExerciseSummary, FullExercise } from "../types";
import { useLang } from "../i18n";

/** The monitor tab's header: which exercise the live view follows (one at a
 *  time, never mixed), with the exercises that have students right now listed
 *  first, and a summary line for the chosen one. */
export function ExerciseHeader({
  exercises,
  liveCounts,
  selectedId,
  onSelect,
  exercise,
  studentCount,
}: {
  exercises: ExerciseSummary[];
  liveCounts: Map<string, number>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  exercise: FullExercise | null;
  studentCount: number;
}) {
  const { t, lang } = useLang();
  const titleOf = (ex: { title_en: string; title_he?: string | null }) =>
    lang === "he" ? ex.title_he ?? ex.title_en : ex.title_en;
  const count = (id: string) => liveCounts.get(id) ?? 0;

  const live = exercises.filter((ex) => count(ex.exercise_id) > 0)
    .sort((a, b) => count(b.exercise_id) - count(a.exercise_id));
  const idle = exercises.filter((ex) => count(ex.exercise_id) === 0);

  return (
    <header style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <label htmlFor="live-exercise" style={{ fontSize: 22, fontWeight: 700 }}>
          📘 {t("liveExercise")}:
        </label>
        <select
          id="live-exercise"
          value={selectedId ?? ""}
          onChange={(e) => onSelect(e.target.value)}
          style={{ fontSize: 15, padding: "6px 10px", borderRadius: 6, border: "1px solid #d1d5db",
                   background: "white", maxWidth: "100%" }}
        >
          {selectedId === null && <option value="">…</option>}
          {live.length > 0 && (
            <optgroup label={t("liveWithStudents")}>
              {live.map((ex) => (
                <option key={ex.exercise_id} value={ex.exercise_id}>
                  {ex.exercise_id} · {titleOf(ex)} ({count(ex.exercise_id)})
                </option>
              ))}
            </optgroup>
          )}
          {idle.length > 0 && (
            <optgroup label={t("liveNoStudents")}>
              {idle.map((ex) => (
                <option key={ex.exercise_id} value={ex.exercise_id}>
                  {ex.exercise_id} · {titleOf(ex)}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </div>
      {exercise && (
        <p style={{ color: "#555", marginTop: 6 }}>
          {titleOf(exercise)} · {t("variantsCount", { n: exercise.variants.length })} ·{" "}
          {studentCount === 0
            ? t("noStudents", { url: "http://lab.local:8011" })
            : t("studentsConnected", { n: studentCount })}
        </p>
      )}
    </header>
  );
}
