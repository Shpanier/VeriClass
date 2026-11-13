import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, auth, setUnauthorizedHandler, setupStatus, type Settings } from "./api";
import type { ExerciseSummary, FullExercise, PendingReview, Student } from "./types";
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
import { PacingPanel } from "./components/PacingPanel";
import { LoginGate } from "./components/LoginGate";
import { ExercisesPanel } from "./components/ExercisesPanel";
import { CoursesPanel } from "./components/CoursesPanel";
import { alertBeep, alertTotal, needsAttention, primeAudio } from "./proctor";
import { useLang } from "./i18n";
import { describeError } from "./lib/errors";
import { useToast } from "./components/ui";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { FeaturesProvider } from "./app/features";
import { FirstRun, Splash } from "./app/FirstRun";
import { markShared, Onboarding } from "./app/Onboarding";
import { SettingsModal } from "./app/SettingsModal";
import { ShareModal } from "./app/ShareModal";
import { ConnectionBanner, Topbar, type Tab } from "./app/Topbar";

// The exercise the live view follows, remembered across reloads.
const LIVE_KEY = "vericlass.liveExercise";

function savedLiveId(): string | null {
  try { return localStorage.getItem(LIVE_KEY); } catch { return null; }
}

type Boot =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; needsTeacher: boolean; local: boolean };

/** Which screen comes first: a new server asks for the first account, a
 *  signed-out browser for the sign-in, anyone else gets the dashboard. */
export function App() {
  const { t } = useLang();
  const [authed, setAuthed] = useState<boolean>(() => !!auth.get());
  const [boot, setBoot] = useState<Boot>({ state: "loading" });

  const check = useCallback(() => {
    setBoot({ state: "loading" });
    setupStatus()
      .then((s) => setBoot({ state: "ready", needsTeacher: s.needs_teacher, local: s.local }))
      .catch((e) => setBoot({ state: "error", message: describeError(e, t) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(check, [check]);

  // A sign-in the server no longer accepts sends us back to the sign-in screen.
  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
  }, []);

  if (boot.state === "loading") return <Splash />;
  if (boot.state === "error") return <Splash error={boot.message} onRetry={check} />;
  if (boot.needsTeacher) {
    return (
      <FirstRun
        local={boot.local}
        onDone={() => { setAuthed(true); setBoot({ state: "ready", needsTeacher: false, local: boot.local }); }}
      />
    );
  }
  if (!authed) return <LoginGate onLoggedIn={() => setAuthed(true)} />;
  return <Dashboard onSignOut={() => { auth.clear(); setAuthed(false); }} />;
}

function Dashboard({ onSignOut }: { onSignOut: () => void }) {
  const { t } = useLang();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("monitor");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [exerciseList, setExerciseList] = useState<ExerciseSummary[]>([]);
  const [exercisesLoaded, setExercisesLoaded] = useState(false);
  const [liveId, setLiveId] = useState<string | null>(savedLiveId);
  const [liveExercise, setLiveExercise] = useState<FullExercise | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [studentsLoaded, setStudentsLoaded] = useState(false);
  const [askingSessionId, setAskingSessionId] = useState<string | null>(null);
  const [viewingSessionId, setViewingSessionId] = useState<string | null>(null);
  const [proctorSessionId, setProctorSessionId] = useState<string | null>(null);
  const [submissionsSessionId, setSubmissionsSessionId] = useState<string | null>(null);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  const plugin = settings?.plugin_ui ?? false;
  const features = useMemo(() => ({ plugin }), [plugin]);

  // Settings carry the tutor's health too (the pill in the top bar): refresh quietly.
  useEffect(() => {
    let alive = true;
    const load = () => api.settings().then((s) => { if (alive) setSettings(s); })
      .catch(() => { /* the banner reports a lost server */ });
    load();
    const id = window.setInterval(load, 20_000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  const refreshExercises = useCallback(
    () => api.exercises().then((list) => { setExerciseList(list); setExercisesLoaded(true); })
      .catch(() => { /* the banner reports a lost server */ }),
    [],
  );
  useEffect(() => { refreshExercises(); }, [refreshExercises]);

  const refreshStudents = useCallback(
    () => api.students().then((list) => { setStudents(list); setStudentsLoaded(true); })
      .catch(() => { /* the banner reports a lost server */ }),
    [],
  );
  useEffect(() => {
    refreshStudents();
    const id = window.setInterval(refreshStudents, 3000);
    return () => window.clearInterval(id);
  }, [refreshStudents]);

  // Live sessions per exercise, for the picker.
  const liveCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of students) m.set(s.exercise, (m.get(s.exercise) ?? 0) + 1);
    return m;
  }, [students]);

  // Nothing chosen yet (or the choice was deleted): follow the exercise with the
  // most students now, else the active one, else the first. Waits for both
  // lists, so the choice doesn't depend on which request answered first.
  useEffect(() => {
    if (!exercisesLoaded || !studentsLoaded || exerciseList.length === 0) return;
    if (liveId && exerciseList.some((e) => e.exercise_id === liveId)) return;
    const busiest = [...liveCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    const pick = busiest ?? exerciseList.find((e) => e.is_active)?.exercise_id
      ?? exerciseList[0].exercise_id;
    setLiveId(pick);
  }, [exerciseList, exercisesLoaded, studentsLoaded, liveCounts, liveId]);

  useEffect(() => {
    if (!liveId) return;
    try { localStorage.setItem(LIVE_KEY, liveId); } catch { /* ignore */ }
    let stale = false;
    api.exercise(liveId)
      .then((ex) => { if (!stale) setLiveExercise(ex); })
      .catch(() => { /* a deleted exercise: the effect above picks another */ });
    return () => { stale = true; };
  }, [liveId]);

  // Only the followed exercise's students: grid, proctor banner and alerts.
  const visible = useMemo(
    () => students.filter((s) => s.exercise === liveId),
    [students, liveId],
  );

  // Browsers block audio until a user gesture; unlock the alert tone on the
  // teacher's first interaction with the page. (Exam alerts: IDE plugin only.)
  useEffect(() => {
    if (!plugin) return;
    const prime = () => primeAudio();
    window.addEventListener("pointerdown", prime, { once: true });
    window.addEventListener("keydown", prime, { once: true });
    return () => {
      window.removeEventListener("pointerdown", prime);
      window.removeEventListener("keydown", prime);
    };
  }, [plugin]);

  // Sound the alarm when any student's alert count (leaving the IDE, a refused
  // terminal command, another panel/window, a paste from outside) rises between
  // polls, or their live state turns bad (e.g. no signal, which isn't an event).
  // Seeded on the first load, and again when another exercise is followed, so
  // alerts that were already there don't beep. Only the followed exercise counts.
  const prevAlerts = useRef<{ exercise: string | null; seen: Map<string, { n: number; bad: boolean }> } | null>(null);
  useEffect(() => {
    if (!plugin) return;
    const current = new Map(
      visible.map((s) => [s.session_id, { n: alertTotal(s), bad: needsAttention(s) }]),
    );
    const prev = prevAlerts.current;
    if (prev && prev.exercise === liveId) {
      for (const [id, now] of current) {
        const before = prev.seen.get(id);
        if (now.n > (before?.n ?? 0) || (now.bad && before && !before.bad)) {
          alertBeep();
          break;
        }
      }
    }
    prevAlerts.current = { exercise: liveId, seen: current };
  }, [visible, liveId, plugin]);

  // A dialog about a student stays open when the student drops out of the live
  // list (idle for 30 minutes): the last data we had for them stands in.
  const known = useRef(new Map<string, Student>());
  for (const s of students) known.current.set(s.session_id, s);
  const find = (id: string | null) =>
    id ? students.find((s) => s.session_id === id) ?? known.current.get(id) ?? null : null;

  const askingTarget = find(askingSessionId);
  // A chat opened from the review queue: the student may never have been in
  // the live list, so the card's own data stands in.
  const [viewingFallback, setViewingFallback] = useState<Student | null>(null);
  const viewingTarget = find(viewingSessionId)
    ?? (viewingFallback?.session_id === viewingSessionId ? viewingFallback : null);
  const viewReviewChat = (r: PendingReview) => {
    setViewingFallback({
      session_id: r.session_id, username: r.username, exercise: r.exercise_id ?? "", variant: "",
      mode: "mentor", started_at: r.created_at, last_active_at: r.created_at, probe_count: 0,
      focus_alerts: 0, last_focus_kind: null, last_focus_at: null, away: false,
    });
    setViewingSessionId(r.session_id);
  };
  const proctorTarget = find(proctorSessionId);
  const submissionsTarget = find(submissionsSessionId);
  const terminalTarget = find(terminalSessionId);

  const boundary = { message: t("somethingBroke"), reloadLabel: t("reloadPage") };

  return (
    <FeaturesProvider value={features}>
      <div className="vc-app">
        <ConnectionBanner />
        <Topbar
          tab={tab} onTab={setTab} settings={settings} plugin={plugin}
          onShare={() => setShowShare(true)} onSettings={() => setShowSettings(true)}
          onVerify={() => setVerifying(true)} onSignOut={onSignOut}
        />
        <main className="vc-main">
          {/* The class page stays mounted while another tab is open, so a
              half-written answer or note isn't lost by looking something up. */}
          <div hidden={tab !== "monitor"}>
            <ErrorBoundary {...boundary}>
              {settings && (
                <Onboarding
                  llmReady={settings.llm.ready}
                  onSettings={() => setShowSettings(true)}
                  onCourses={() => setTab("courses")}
                  onShare={() => setShowShare(true)}
                />
              )}
              <ExerciseHeader
                exercises={exerciseList}
                liveCounts={liveCounts}
                selectedId={liveId}
                onSelect={(id) => { setLiveExercise(null); setLiveId(id); }}
                exercise={liveExercise}
                studentCount={visible.length}
              />
              {plugin && <ProctorBanner students={visible} onInspect={setProctorSessionId} />}
              {liveId && liveExercise?.exercise_id === liveId && liveExercise.pacing === "class"
                ? <PacingPanel exerciseId={liveId} />
                : <StepChecks exerciseId={liveId} />}
              <ReviewQueue exerciseId={liveId} onViewChat={viewReviewChat} />
              <StudentGrid
                students={visible}
                paramLabels={liveExercise?.param_labels}
                onModeChange={async (id, mode) => {
                  try {
                    await api.setMode(id, mode);
                  } catch (e) {
                    toast.error(e);
                  }
                  refreshStudents();
                }}
                onAskThem={(id) => setAskingSessionId(id)}
                onViewChat={(id) => setViewingSessionId(id)}
                onProctorLog={(id) => setProctorSessionId(id)}
                onViewSubmissions={(id) => setSubmissionsSessionId(id)}
                onTerminalLog={(id) => setTerminalSessionId(id)}
              />
            </ErrorBoundary>
          </div>

          {tab === "exercises" && (
            <ErrorBoundary {...boundary}><ExercisesPanel onActiveChanged={refreshExercises} /></ErrorBoundary>
          )}
          {tab === "courses" && <ErrorBoundary {...boundary}><CoursesPanel /></ErrorBoundary>}
        </main>

        {askingTarget && (
          <AskThemModal
            student={askingTarget}
            onClose={() => setAskingSessionId(null)}
            onSent={() => {
              setAskingSessionId(null);
              refreshStudents();
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
        {plugin && proctorTarget && (
          <ProctorLogModal student={proctorTarget} onClose={() => setProctorSessionId(null)} />
        )}
        {plugin && submissionsTarget && (
          <SubmissionsModal student={submissionsTarget} onClose={() => setSubmissionsSessionId(null)} />
        )}
        {plugin && terminalTarget && (
          <TerminalLogModal student={terminalTarget} onClose={() => setTerminalSessionId(null)} />
        )}
        {plugin && verifying && <VerifyTraceModal onClose={() => setVerifying(false)} />}
        {showSettings && settings && (
          <SettingsModal settings={settings} onChanged={setSettings} onClose={() => setShowSettings(false)} />
        )}
        {showShare && <ShareModal onClose={() => setShowShare(false)} onShared={markShared} />}
      </div>
    </FeaturesProvider>
  );
}
