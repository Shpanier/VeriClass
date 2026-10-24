import { useEffect, useMemo, useRef, useState } from "react";
import { api, auth, setUnauthorizedHandler } from "./api";
import type { ExerciseSummary, FullExercise, Student } from "./types";
import { ExerciseHeader } from "./components/ExerciseHeader";
import { StudentGrid } from "./components/StudentGrid";
import { AskThemModal } from "./components/AskThemModal";
import { ChatViewModal } from "./components/ChatViewModal";
import { ProctorBanner } from "./components/ProctorBanner";
import { ProctorLogModal } from "./components/ProctorLogModal";
import { SubmissionsModal } from "./components/SubmissionsModal";
import { TerminalLogModal } from "./components/TerminalLogModal";
import { VerifyTraceModal } from "./components/VerifyTraceModal";
import { ReviewQueue } from "./components/ReviewQueue";
import { StepChecks } from "./components/StepChecks";
import { LoginGate } from "./components/LoginGate";
import { ExercisesPanel } from "./components/ExercisesPanel";
import { CoursesPanel } from "./components/CoursesPanel";
import { alertBeep, alertTotal, needsAttention, primeAudio } from "./proctor";
import { LanguageToggle, useLang } from "./i18n";

type Tab = "monitor" | "exercises" | "courses";

// The exercise the live view follows, remembered across reloads.
const LIVE_KEY = "vericlass.liveExercise";

function savedLiveId(): string | null {
  try { return localStorage.getItem(LIVE_KEY); } catch { return null; }
}

export function App() {
  const { t } = useLang();
  const [authed, setAuthed] = useState<boolean>(() => !!auth.get());
  const [tab, setTab] = useState<Tab>("monitor");
  const [exerciseList, setExerciseList] = useState<ExerciseSummary[]>([]);
  const [liveId, setLiveId] = useState<string | null>(savedLiveId);
  const [liveExercise, setLiveExercise] = useState<FullExercise | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [askingSessionId, setAskingSessionId] = useState<string | null>(null);
  const [viewingSessionId, setViewingSessionId] = useState<string | null>(null);
  const [proctorSessionId, setProctorSessionId] = useState<string | null>(null);
  const [submissionsSessionId, setSubmissionsSessionId] = useState<string | null>(null);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  const refreshExercises = () =>
    api.exercises().then(setExerciseList).catch(console.error);

  // Any 401/403 from the API bounces us back to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
  }, []);

  useEffect(() => {
    if (!authed) return;
    refreshExercises();
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    const tick = () => api.students().then(setStudents).catch(console.error);
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [authed]);

  // Live sessions per exercise, for the picker.
  const liveCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of students) m.set(s.exercise, (m.get(s.exercise) ?? 0) + 1);
    return m;
  }, [students]);

  // Nothing chosen yet (or the choice was deleted): follow the exercise with the
  // most students now, else the active one, else the first.
  useEffect(() => {
    if (exerciseList.length === 0) return;
    if (liveId && exerciseList.some((e) => e.exercise_id === liveId)) return;
    const busiest = [...liveCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    const pick = busiest ?? exerciseList.find((e) => e.is_active)?.exercise_id
      ?? exerciseList[0].exercise_id;
    setLiveId(pick);
  }, [exerciseList, liveCounts, liveId]);

  useEffect(() => {
    if (!liveId) return;
    try { localStorage.setItem(LIVE_KEY, liveId); } catch { /* ignore */ }
    let stale = false;
    api.exercise(liveId)
      .then((ex) => { if (!stale) setLiveExercise(ex); })
      .catch(console.error);
    return () => { stale = true; };
  }, [liveId]);

  // Only the followed exercise's students: grid, proctor banner and alerts.
  const visible = useMemo(
    () => students.filter((s) => s.exercise === liveId),
    [students, liveId],
  );

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

  // Sound the alarm when any student's alert count (leaving the IDE, a refused
  // terminal command, another panel/window, a paste from outside) rises between
  // polls, or their live state turns bad (e.g. no signal, which isn't an event).
  // Seeded on the first load so pre-existing alerts don't beep on open.
  // Only the followed exercise's students count.
  const prevAlerts = useRef<Map<string, { n: number; bad: boolean }> | null>(null);
  useEffect(() => {
    const current = new Map(
      visible.map((s) => [s.session_id, { n: alertTotal(s), bad: needsAttention(s) }]),
    );
    const prev = prevAlerts.current;
    if (prev) {
      for (const [id, now] of current) {
        const before = prev.get(id);
        if (now.n > (before?.n ?? 0) || (now.bad && before && !before.bad)) {
          alertBeep();
          break;
        }
      }
    }
    prevAlerts.current = current;
  }, [visible]);

  const askingTarget = students.find((s) => s.session_id === askingSessionId) ?? null;
  const viewingTarget = students.find((s) => s.session_id === viewingSessionId) ?? null;
  const proctorTarget = students.find((s) => s.session_id === proctorSessionId) ?? null;
  const submissionsTarget = students.find((s) => s.session_id === submissionsSessionId) ?? null;
  const terminalTarget = students.find((s) => s.session_id === terminalSessionId) ?? null;

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
          <button
            onClick={() => setVerifying(true)}
            style={{ padding: "6px 12px", border: "1px solid #d1d5db", borderRadius: 6,
                     background: "white", cursor: "pointer", fontSize: 13 }}
          >
            {t("verifyLog")}
          </button>
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
          <ExerciseHeader
            exercises={exerciseList}
            liveCounts={liveCounts}
            selectedId={liveId}
            onSelect={(id) => { setLiveExercise(null); setLiveId(id); }}
            exercise={liveExercise}
            studentCount={visible.length}
          />
          <ProctorBanner students={visible} onInspect={setProctorSessionId} />
          <StepChecks exerciseId={liveId} />
          <ReviewQueue exerciseId={liveId} />
          <StudentGrid
            students={visible}
            paramLabels={liveExercise?.param_labels}
            onModeChange={async (id, mode) => {
              await api.setMode(id, mode);
              api.students().then(setStudents);
            }}
            onAskThem={(id) => setAskingSessionId(id)}
            onViewChat={(id) => setViewingSessionId(id)}
            onProctorLog={(id) => setProctorSessionId(id)}
            onViewSubmissions={(id) => setSubmissionsSessionId(id)}
            onTerminalLog={(id) => setTerminalSessionId(id)}
          />
        </>
      )}

      {tab === "exercises" && <ExercisesPanel onActiveChanged={refreshExercises} />}
      {tab === "courses" && <CoursesPanel />}

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
          paramLabels={liveExercise?.param_labels}
          onClose={() => setViewingSessionId(null)}
        />
      )}
      {proctorTarget && (
        <ProctorLogModal student={proctorTarget} onClose={() => setProctorSessionId(null)} />
      )}
      {submissionsTarget && (
        <SubmissionsModal student={submissionsTarget} onClose={() => setSubmissionsSessionId(null)} />
      )}
      {terminalTarget && (
        <TerminalLogModal student={terminalTarget} onClose={() => setTerminalSessionId(null)} />
      )}
      {verifying && <VerifyTraceModal onClose={() => setVerifying(false)} />}
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
  t: (key: "tabMonitor" | "tabExercises" | "tabCourses") => string;
}) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "monitor", label: t("tabMonitor") },
    { key: "exercises", label: t("tabExercises") },
    { key: "courses", label: t("tabCourses") },
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
