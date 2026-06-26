import type { ActiveExercise } from "../types";
import { useLang } from "../i18n";

export function ExerciseHeader({
  exercise,
  studentCount,
}: {
  exercise: ActiveExercise;
  studentCount: number;
}) {
  const { t, lang } = useLang();
  const title = lang === "he" ? exercise.title_he ?? exercise.title_en : exercise.title_en;
  return (
    <header style={{ marginBottom: 24 }}>
      <h1 style={{ margin: 0 }}>
        📘 {t("activeExercise")}: <code>{exercise.exercise_id}</code>
      </h1>
      <p style={{ color: "#555", marginTop: 4 }}>
        {title} · {t("variantsCount", { n: exercise.variants.length })} ·{" "}
        {studentCount === 0
          ? t("noStudents", { url: "http://lab.local:8011" })
          : t("studentsConnected", { n: studentCount })}
      </p>
    </header>
  );
}
