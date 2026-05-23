import { useEffect, useState } from "react";
import { api } from "./api";
import type { ActiveExercise, Student } from "./types";
import { ExerciseHeader } from "./components/ExerciseHeader";
import { StudentGrid } from "./components/StudentGrid";
import { AskThemModal } from "./components/AskThemModal";
import { ChatViewModal } from "./components/ChatViewModal";
import { ReviewQueue } from "./components/ReviewQueue";

export function App() {
  const [exercise, setExercise] = useState<ActiveExercise | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [askingSessionId, setAskingSessionId] = useState<string | null>(null);
  const [viewingSessionId, setViewingSessionId] = useState<string | null>(null);

  useEffect(() => {
    api.activeExercise().then(setExercise).catch(console.error);
  }, []);

  useEffect(() => {
    const tick = () => api.students().then(setStudents).catch(console.error);
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, []);

  const askingTarget = students.find((s) => s.session_id === askingSessionId) ?? null;
  const viewingTarget = students.find((s) => s.session_id === viewingSessionId) ?? null;

  return (
    <div style={{ fontFamily: "system-ui", padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      {exercise && <ExerciseHeader exercise={exercise} studentCount={students.length} />}
      <ReviewQueue />
      <StudentGrid
        students={students}
        onModeChange={async (id, mode) => {
          await api.setMode(id, mode);
          api.students().then(setStudents);
        }}
        onAskThem={(id) => setAskingSessionId(id)}
        onViewChat={(id) => setViewingSessionId(id)}
      />
      {askingTarget && (
        <AskThemModal
          student={askingTarget}
          onClose={() => setAskingSessionId(null)}
          onSent={() => {
            setAskingSessionId(null);
            api.students().then(setStudents);
          }}
        />
      )}
      {viewingTarget && (
        <ChatViewModal student={viewingTarget} onClose={() => setViewingSessionId(null)} />
      )}
    </div>
  );
}
