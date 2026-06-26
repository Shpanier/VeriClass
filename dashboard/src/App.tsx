import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ActiveExercise, Student } from "./types";
import { ExerciseHeader } from "./components/ExerciseHeader";
import { StudentGrid } from "./components/StudentGrid";
import { AskThemModal } from "./components/AskThemModal";
import { ChatViewModal } from "./components/ChatViewModal";
import { ProctorBanner } from "./components/ProctorBanner";
import { ProctorLogModal } from "./components/ProctorLogModal";
import { ReviewQueue } from "./components/ReviewQueue";
import { alertBeep, primeAudio } from "./proctor";
import { LanguageToggle, useLang } from "./i18n";

export function App() {
  const { t } = useLang();
  const [exercise, setExercise] = useState<ActiveExercise | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [askingSessionId, setAskingSessionId] = useState<string | null>(null);
  const [viewingSessionId, setViewingSessionId] = useState<string | null>(null);
  const [proctorSessionId, setProctorSessionId] = useState<string | null>(null);

  useEffect(() => {
    api.activeExercise().then(setExercise).catch(console.error);
  }, []);

  useEffect(() => {
    const tick = () => api.students().then(setStudents).catch(console.error);
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, []);

  // Browsers block audio until a user gesture; unlock the alert tone on the
  // teacher's first interaction with the page.
  useEffect(() => {
    const prime = () => primeAudio();
    window.addEventListener("pointerdown", prime, { once: true });
    window.addEventListener("keydown", prime, { once: true });
    return () => {
      window.removeEventListener("pointerdown", prime);
      window.removeEventListener("keydown", prime);
    };
  }, []);

  // Sound the alarm when any student's leave-count rises between polls. Seeded
  // on the first load so pre-existing alerts don't beep on open.
  const prevAlerts = useRef<Map<string, number> | null>(null);
  useEffect(() => {
    const current = new Map(students.map((s) => [s.session_id, s.focus_alerts]));
    const prev = prevAlerts.current;
    if (prev) {
      for (const [id, n] of current) {
        if (n > (prev.get(id) ?? 0)) {
          alertBeep();
          break;
        }
      }
    }
    prevAlerts.current = current;
  }, [students]);

  const askingTarget = students.find((s) => s.session_id === askingSessionId) ?? null;
  const viewingTarget = students.find((s) => s.session_id === viewingSessionId) ?? null;
  const proctorTarget = students.find((s) => s.session_id === proctorSessionId) ?? null;

  return (
    <div style={{ fontFamily: "system-ui", padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 16,
      }}>
        <strong style={{ fontSize: 18 }}>{t("appTitle")}</strong>
        <LanguageToggle />
      </div>
      {exercise && <ExerciseHeader exercise={exercise} studentCount={students.length} />}
      <ProctorBanner students={students} onInspect={setProctorSessionId} />
      <ReviewQueue />
      <StudentGrid
        students={students}
        onModeChange={async (id, mode) => {
          await api.setMode(id, mode);
          api.students().then(setStudents);
        }}
        onAskThem={(id) => setAskingSessionId(id)}
        onViewChat={(id) => setViewingSessionId(id)}
        onProctorLog={(id) => setProctorSessionId(id)}
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
      {proctorTarget && (
        <ProctorLogModal student={proctorTarget} onClose={() => setProctorSessionId(null)} />
      )}
    </div>
  );
}
