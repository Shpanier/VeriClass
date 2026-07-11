import { useEffect, useRef, useState } from "react";
import { api, auth, setUnauthorizedHandler } from "./api";
import type { ActiveExercise, Student } from "./types";
import { ExerciseHeader } from "./components/ExerciseHeader";
import { StudentGrid } from "./components/StudentGrid";
import { AskThemModal } from "./components/AskThemModal";
import { ChatViewModal } from "./components/ChatViewModal";
import { ProctorBanner } from "./components/ProctorBanner";
import { ProctorLogModal } from "./components/ProctorLogModal";
import { ReviewQueue } from "./components/ReviewQueue";
import { LoginGate } from "./components/LoginGate";
import { ExercisesPanel } from "./components/ExercisesPanel";
import { alertBeep, primeAudio } from "./proctor";
import { LanguageToggle, useLang } from "./i18n";

type Tab = "monitor" | "exercises";

export function App() {
  const { t } = useLang();
  const [authed, setAuthed] = useState<boolean>(() => !!auth.get());
  const [tab, setTab] = useState<Tab>("monitor");
  const [exercise, setExercise] = useState<ActiveExercise | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [askingSessionId, setAskingSessionId] = useState<string | null>(null);
  const [viewingSessionId, setViewingSessionId] = useState<string | null>(null);
  const [proctorSessionId, setProctorSessionId] = useState<string | null>(null);

  const refreshActiveExercise = () =>
    api.activeExercise().then(setExercise).catch(console.error);

  // Any 401/403 from the API bounces us back to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
  }, []);

  useEffect(() => {
    if (!authed) return;
    refreshActiveExercise();
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    const tick = () => api.students().then(setStudents).catch(console.error);
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [authed]);

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

  if (!authed) return <LoginGate onLoggedIn={() => setAuthed(true)} />;

  const signOut = () => {
    auth.clear();
    setAuthed(false);
  };

  return (
    <div style={{ fontFamily: "system-ui", padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 16,
      }}>
        <strong style={{ fontSize: 18 }}>{t("appTitle")}</strong>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <LanguageToggle />
          <button
            onClick={signOut}
            style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid #d1d5db",
                     background: "white", cursor: "pointer", fontSize: 12 }}
          >
            {t("signOut")}
          </button>
        </div>
      </div>
      <TabBar tab={tab} onChange={setTab} t={t} />

      {tab === "monitor" && (
        <>
          {exercise && <ExerciseHeader exercise={exercise} studentCount={students.length} />}
          <ProctorBanner students={students} onInspect={setProctorSessionId} />
          <ReviewQueue />
          <StudentGrid
            students={students}
            paramLabels={exercise?.param_labels}
            onModeChange={async (id, mode) => {
              await api.setMode(id, mode);
              api.students().then(setStudents);
            }}
            onAskThem={(id) => setAskingSessionId(id)}
            onViewChat={(id) => setViewingSessionId(id)}
            onProctorLog={(id) => setProctorSessionId(id)}
          />
        </>
      )}

      {tab === "exercises" && <ExercisesPanel onActiveChanged={refreshActiveExercise} />}

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
        <ChatViewModal
          student={viewingTarget}
          paramLabels={exercise?.param_labels}
          onClose={() => setViewingSessionId(null)}
        />
      )}
      {proctorTarget && (
        <ProctorLogModal student={proctorTarget} onClose={() => setProctorSessionId(null)} />
      )}
    </div>
  );
}

function TabBar({
  tab,
  onChange,
  t,
}: {
  tab: Tab;
  onChange: (t: Tab) => void;
  t: (key: "tabMonitor" | "tabExercises") => string;
}) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "monitor", label: t("tabMonitor") },
    { key: "exercises", label: t("tabExercises") },
  ];
  return (
    <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e5e7eb", marginBottom: 20 }}>
      {tabs.map(({ key, label }) => {
        const active = tab === key;
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            style={{
              padding: "8px 16px",
              border: "none",
              borderBottom: `2px solid ${active ? "#111827" : "transparent"}`,
              background: "none",
              cursor: "pointer",
              fontSize: 14,
              fontWeight: active ? 700 : 500,
              color: active ? "#111827" : "#6b7280",
              marginBottom: -1,
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
