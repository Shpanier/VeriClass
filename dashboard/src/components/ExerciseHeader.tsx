import "../styles/students.css";
import { useId } from "react";
import { Layers, ListOrdered, Users } from "lucide-react";
import type { ExerciseSummary, FullExercise } from "../types";
import { useLang } from "../i18n";
import { sortExercises, useExerciseSort } from "../lib/exerciseOrder";
import { Select } from "./ui";

/** The class page's heading: which exercise the live view follows (one at a
 *  time, never mixed), with the exercises that have students right now listed
 *  first (the rest in the order chosen in the Exercises tab), and a line of
 *  facts about the chosen one. */
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
  const [sort] = useExerciseSort();
  const hintId = useId();
  const titleOf = (ex: { title_en: string; title_he?: string | null }) =>
    lang === "he" ? ex.title_he ?? ex.title_en : ex.title_en;
  const count = (id: string) => liveCounts.get(id) ?? 0;

  // Two exercises with the same title are told apart by their id.
  const sameTitle = new Map<string, number>();
  for (const ex of exercises) sameTitle.set(titleOf(ex), (sameTitle.get(titleOf(ex)) ?? 0) + 1);
  const nameOf = (ex: ExerciseSummary) =>
    (sameTitle.get(titleOf(ex)) ?? 0) > 1 ? `${titleOf(ex)} (${ex.exercise_id})` : titleOf(ex);

  const live = exercises.filter((ex) => count(ex.exercise_id) > 0)
    .sort((a, b) => count(b.exercise_id) - count(a.exercise_id));
  const idle = sortExercises(exercises.filter((ex) => count(ex.exercise_id) === 0), sort, lang);
  const versions = exercise?.variants.length ?? 0;

  return (
    <header className="vc-students-head">
      <div className="vc-students-head__row">
        <h1 className="vc-students-head__label">
          <label htmlFor="live-exercise">{t("liveExercise")}</label>
        </h1>
        <Select
          id="live-exercise"
          className="vc-students-head__select"
          aria-describedby={hintId}
          value={selectedId ?? ""}
          onChange={(e) => onSelect(e.target.value)}
        >
          {selectedId === null && <option value="">{t("ehPick")}</option>}
          {live.length > 0 && (
            <optgroup label={t("liveWithStudents")}>
              {live.map((ex) => {
                const n = count(ex.exercise_id);
                return (
                  <option key={ex.exercise_id} value={ex.exercise_id}>
                    {n === 1 ? t("ehOptOneStudent", { title: nameOf(ex) }) : t("ehOptStudents", { title: nameOf(ex), n })}
                  </option>
                );
              })}
            </optgroup>
          )}
          {idle.length > 0 && (
            <optgroup label={t("liveNoStudents")}>
              {idle.map((ex) => (
                <option key={ex.exercise_id} value={ex.exercise_id}>{nameOf(ex)}</option>
              ))}
            </optgroup>
          )}
        </Select>
        {selectedId !== null && (
          <div className="vc-students-head__facts">
            <span className={studentCount > 0 ? "vc-badge vc-badge--success" : "vc-badge"}>
              <Users aria-hidden="true" />
              {studentCount === 0 ? t("noStudents")
                : studentCount === 1 ? t("ehOneStudent")
                  : t("studentsConnected", { n: studentCount })}
            </span>
            {versions > 1 && (
              <span className="vc-badge" title={t("ehVersionsTitle")}>
                <Layers aria-hidden="true" /> {t("ehVersions", { n: versions })}
              </span>
            )}
            {exercise?.pacing === "class" && (
              <span className="vc-badge vc-badge--brand" title={t("ehClassPacedTitle")}>
                <ListOrdered aria-hidden="true" /> {t("ehClassPaced")}
              </span>
            )}
          </div>
        )}
      </div>
      <p className="vc-hint" id={hintId}>{t("ehHint")}</p>
    </header>
  );
}
