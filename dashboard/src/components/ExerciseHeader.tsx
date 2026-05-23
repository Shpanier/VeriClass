import type { ActiveExercise } from "../types";

export function ExerciseHeader({
  exercise,
  studentCount,
}: {
  exercise: ActiveExercise;
  studentCount: number;
}) {
  return (
    <header style={{ marginBottom: 24 }}>
      <h1 style={{ margin: 0 }}>
        📘 Active exercise: <code>{exercise.exercise_id}</code>
      </h1>
      <p style={{ color: "#555", marginTop: 4 }}>
        {exercise.title_en} · {exercise.variants.length} variants ·{" "}
        {studentCount === 0
          ? "No active students yet. Share http://lab.local:8001 with students to begin."
          : `${studentCount} student${studentCount === 1 ? "" : "s"} connected`}
      </p>
    </header>
  );
}
