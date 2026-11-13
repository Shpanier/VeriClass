import type {
  ActiveExercise,
  AnswerLevel,
  AnswerSlot,
  Attendance,
  Meeting,
  Course,
  ExerciseSummary,
  FullExercise,
  GradeRecommendation,
  Lang,
  NewExercise,
  PackageResult,
  PacingOverview,
  PacingQuizItem,
  Paste,
  PendingReview,
  ProbeSuggestion,
  ProctorEvent,
  RegenModel,
  ReviewConfig,
  SelectResult,
  TranslateTo,
  TranscriptResponse,
  RosterResult,
  SessionDetail,
  StepChecksResponse,
  Student,
  Submission,
  TerminalCommand,
  TerminalFullOutput,
  TraceVerifyResult,
  UserAccount,
} from "./types";
import { ApiError } from "./lib/errors";
import { connection } from "./lib/connection";

const TOKEN_KEY = "vericlass.teacher.token";

export const auth = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

// Called when the backend rejects our token (expired / restarted). The App
// registers a handler that bounces the teacher back to the login screen.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const token = auth.get();
  let r: Response;
  try {
    r = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers || {}),
      },
    });
  } catch {
    // The server didn't answer at all (stopped, restarting, no network).
    connection.fail();
    throw new ApiError("The server can't be reached.", 0, true);
  }
  connection.ok();
  if (r.status === 401) {
    // The sign-in is no longer valid: back to the sign-in screen.
    auth.clear();
    onUnauthorized?.();
    throw new ApiError("Signed out.", 401);
  }
  if (!r.ok) {
    // FastAPI's `detail` (or a 422 validation summary) says why a request was
    // refused. A 403 is an answer like any other ("not allowed"), not a sign-out,
    // except the one that says this browser may not act as a lecturer at all.
    const detail = await readErrorDetail(r);
    if (r.status === 403 && /instructor/i.test(detail ?? "")) {
      auth.clear();
      onUnauthorized?.();
    }
    throw new ApiError(detail || `${r.status} ${r.statusText}`, r.status);
  }
  return r.json() as Promise<T>;
}

// FastAPI puts errors in `detail`: a string for HTTPException, or an array of
// {loc, msg} for 422 validation failures. Fold either into one readable line.
async function readErrorDetail(r: Response): Promise<string | null> {
  try {
    const body = await r.json();
    const d = body?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e: { loc?: unknown[]; msg?: string }) =>
          `${(e.loc || []).slice(1).join(".")}: ${e.msg ?? ""}`.trim()
        )
        .join("; ");
    }
  } catch {
    // Non-JSON body — fall through to the status line.
  }
  return null;
}

export interface LoginResult {
  token: string;
  role: string;
  username: string;
}

// Standalone (not via j): a wrong code or password legitimately returns 401 and
// must not be treated as a session-expiry bounce.
export async function login(code: string, password: string): Promise<LoginResult> {
  let r: Response;
  try {
    r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, password }),
    });
  } catch {
    throw new ApiError("The server can't be reached.", 0, true);
  }
  if (r.status === 401) throw new Error("bad-code");
  if (!r.ok) throw new ApiError((await readErrorDetail(r)) || `${r.status} ${r.statusText}`, r.status);
  return r.json() as Promise<LoginResult>;
}

// --- first run, settings, the students' link (backend/routes/setup.py) -------------

export interface SetupStatus { needs_teacher: boolean; local: boolean; version: string }

export interface LlmProvider { id: string; label: string; key_url: string; key_set: boolean; key_hint: string }
export interface LlmStatus {
  provider: string;
  provider_label: string;
  ready: boolean;
  key_hint: string;
  chat_model: string;
  agent_model: string;
  providers: LlmProvider[];
  /** The last tutor call: ok true/false, or null when none was made yet. */
  health: { ok: boolean | null; error: string; at: number | null };
}
export interface KeyCheck { ok: boolean; message: string; model_ok?: boolean; network?: boolean }
export type ChatLanguage = "auto" | "he" | "en";
export interface Settings {
  version: string;
  user: { name: string; via: string };
  llm: LlmStatus;
  chat_language: ChatLanguage;
  /** Show the IDE plugin's screens (exam monitoring, terminal log, submissions). */
  plugin_ui: boolean;
  paths: { env_file: string; data_dir: string; database: string };
}
export interface TunnelState {
  state: "off" | "starting" | "on" | "stopping" | "error";
  provider: "cloudflared" | "ngrok" | null;
  url: string | null;
  error: string | null;
  external?: boolean;
  slow?: boolean;
}
export interface ShareInfo {
  chat_mounted: boolean;
  local_url: string;
  lan_urls: string[];
  public_url: string | null;
  tunnel: TunnelState;
  available: { cloudflared: boolean; ngrok: boolean };
  ngrok_domain: string;
  install_hint: string;
}
export interface Overview {
  llm_ready: boolean;
  students: number;
  courses: number;
  courses_with_exercise: boolean;
  courses_with_students: boolean;
  exercises: number;
  own_exercises: number;
  sessions: number;
}

/** Public: is this a brand-new server? Never throws for "not signed in". */
export async function setupStatus(): Promise<SetupStatus> {
  let r: Response;
  try {
    r = await fetch("/api/setup/status");
  } catch {
    throw new ApiError("The server can't be reached.", 0, true);
  }
  if (!r.ok) throw new ApiError(`${r.status} ${r.statusText}`, r.status);
  return r.json() as Promise<SetupStatus>;
}

export async function createFirstTeacher(name: string, username: string, password: string): Promise<LoginResult> {
  let r: Response;
  try {
    r = await fetch("/api/setup/teacher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, username, password }),
    });
  } catch {
    throw new ApiError("The server can't be reached.", 0, true);
  }
  if (!r.ok) throw new ApiError((await readErrorDetail(r)) || `${r.status} ${r.statusText}`, r.status);
  return r.json() as Promise<LoginResult>;
}

export const api = {
  activeExercise: () => j<ActiveExercise>("/api/exercises/active"),
  exercises: () => j<ExerciseSummary[]>("/api/exercises"),
  exercise: (id: string) => j<FullExercise>(`/api/exercises/${encodeURIComponent(id)}`),
  createExercise: (payload: NewExercise) =>
    j<ExerciseSummary>("/api/exercises", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateExercise: (id: string, payload: NewExercise) =>
    j<ExerciseSummary>(`/api/exercises/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  setActiveExercise: (exerciseId: string) =>
    j<{ exercise_id: string }>("/api/exercises/active", {
      method: "POST",
      body: JSON.stringify({ exercise_id: exerciseId }),
    }),
  disableActiveExercise: () =>
    j<{ exercise_id: null }>("/api/exercises/active", { method: "DELETE" }),
  importExercise: (zipBase64: string) =>
    j<PackageResult>("/api/exercises/import", {
      method: "POST",
      body: JSON.stringify({ zip_base64: zipBase64, replace: true }),
    }),
  reloadExercises: () =>
    j<{ exercises: ExerciseSummary[]; load_errors: { folder: string; error: string }[] }>(
      "/api/exercises/reload", { method: "POST" }),
  exercisesStatus: () =>
    j<{ data_dir: string; exercises_dir: string; load_errors: { folder: string; error: string }[] }>(
      "/api/exercises-status"),
  // A zip: not JSON, so fetched directly (with the token).
  exportExercise: async (id: string): Promise<Blob> => {
    const token = auth.get();
    const r = await fetch(`/api/exercises/${encodeURIComponent(id)}/export`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.blob();
  },
  students: () => j<Student[]>("/api/students"),
  /** The chat as the student saw it (backend/transcript.py); enabled=false when the exercise keeps none. */
  transcript: (sessionId: string) =>
    j<TranscriptResponse>(`/api/transcript/${encodeURIComponent(sessionId)}`),
  sessionDetail: (sessionId: string) =>
    j<SessionDetail>(`/api/students/${sessionId}/messages`),
  proctorEvents: (sessionId: string) =>
    j<ProctorEvent[]>(`/api/proctor/events?session_id=${encodeURIComponent(sessionId)}`),
  terminalCommands: (sessionId: string) =>
    j<TerminalCommand[]>(`/api/terminal/commands?session_id=${encodeURIComponent(sessionId)}`),
  terminalOutput: (commandId: number) =>
    j<TerminalFullOutput>(`/api/terminal/commands/${commandId}/output`),
  pastes: (sessionId: string) =>
    j<Paste[]>(`/api/proctor/pastes?session_id=${encodeURIComponent(sessionId)}`),
  verifyTrace: (csv: string, importMissing: boolean) =>
    j<TraceVerifyResult>("/api/trace/verify", {
      method: "POST",
      body: JSON.stringify({ csv, import_missing: importMissing }),
    }),
  submissions: (sessionId: string) =>
    j<Submission[]>(`/api/submissions?session_id=${encodeURIComponent(sessionId)}`),
  // Recommended grade: fetch the current one, (re)compute, or override.
  gradeFor: (sessionId: string) =>
    j<GradeRecommendation | null>(`/api/grade/${encodeURIComponent(sessionId)}`),
  recommendGrade: (sessionId: string, lang: Lang = "en") =>
    j<GradeRecommendation>("/api/grade/recommend", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, lang }),
    }),
  overrideGrade: (sessionId: string, grade: number) =>
    j<{ ok: boolean }>("/api/grade/override", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, grade }),
    }),
  setMode: (sessionId: string, mode: "mentor" | "coding_partner") =>
    j<{ ok: boolean }>("/api/mode", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, mode }),
    }),
  suggestProbes: (sessionId: string, lang: Lang = "en") =>
    j<ProbeSuggestion[]>("/api/probe/suggest", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, lang }),
    }),
  sendProbes: (sessionId: string, bodies: string[], source: string) =>
    j<{ probe_ids: number[] }>("/api/probe/send", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, bodies, source }),
    }),
  getReviewMode: () => j<{ enabled: boolean }>("/api/review_mode"),
  setReviewMode: (enabled: boolean) =>
    j<{ enabled: boolean }>("/api/review_mode", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  pendingReviews: () => j<PendingReview[]>("/api/reviews/pending"),
  reviewConfig: () => j<ReviewConfig>("/api/reviews/config"),
  setReviewConfig: (change: {
    translate_to?: TranslateTo; best_answer?: boolean; best_level?: AnswerLevel; save_to_bank?: boolean;
  }) =>
    j<ReviewConfig>("/api/reviews/config", {
      method: "POST",
      body: JSON.stringify(change),
    }),
  /** Draft again: the four levels with a stronger model, or (no model) the failed answers. */
  regenerateReview: (id: number, model?: RegenModel["key"], slots?: AnswerSlot[]) =>
    j<PendingReview>(`/api/reviews/${id}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ model: model ?? null, slots: slots ?? null }),
    }),
  /** How many students a class note reaches now. */
  broadcastRecipients: (exerciseId: string, courseId?: string | null) =>
    j<{ count: number; minutes: number }>(
      `/api/broadcast/recipients?exercise_id=${encodeURIComponent(exerciseId)}`
      + (courseId ? `&course_id=${encodeURIComponent(courseId)}` : "")),
  /** A note from the teacher to every student active on the exercise. */
  broadcast: (exerciseId: string, text: string, courseId?: string | null) =>
    j<{ sent: number; skipped: number }>("/api/broadcast", {
      method: "POST",
      body: JSON.stringify({ exercise_id: exerciseId, text, course_id: courseId ?? null }),
    }),
  pendingStepChecks: () => j<StepChecksResponse>("/api/step-checks/pending"),
  pacing: (exerciseId: string) => j<PacingOverview>(`/api/pacing/${encodeURIComponent(exerciseId)}`),
  releaseSteps: (exerciseId: string, courseId: string, released: number) =>
    j<{ released: number }>(`/api/pacing/${encodeURIComponent(exerciseId)}/release`, {
      method: "POST",
      body: JSON.stringify({ course_id: courseId, released }),
    }),
  resetSession: (sessionId: string, step: number) =>
    j<{ from: number; to: number }>(`/api/sessions/${encodeURIComponent(sessionId)}/reset`, {
      method: "POST",
      body: JSON.stringify({ step }),
    }),
  /** Move one student to a step: back, forward (skipping), or the same one (start over). */
  moveSession: (sessionId: string, step: number) =>
    j<{ from: number; to: number; how: "back" | "forward" | "again" }>(`/api/sessions/${encodeURIComponent(sessionId)}/move`, {
      method: "POST",
      body: JSON.stringify({ step }),
    }),
  resetCourse: (exerciseId: string, courseId: string, step: number) =>
    j<{ sessions: number; moved: number }>(`/api/exercises/${encodeURIComponent(exerciseId)}/reset`, {
      method: "POST",
      body: JSON.stringify({ course_id: courseId, step }),
    }),
  declineOutput: (exerciseId: string, sessionId: string, step: number, note?: string) =>
    j<{ ok: boolean }>(`/api/pacing/${encodeURIComponent(exerciseId)}/decline`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, step, note: note ?? null }),
    }),
  letThrough: (exerciseId: string, sessionId: string, step: number) =>
    j<{ ok: boolean }>(`/api/pacing/${encodeURIComponent(exerciseId)}/let-through`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, step }),
    }),
  setQuiz: (exerciseId: string, key: string, approved: boolean, body?: string,
            course?: { courseId: string }, withdrawAsked = false) =>
    j<PacingQuizItem & { asked_now: number; withdrawn_now: number }>(`/api/pacing/${encodeURIComponent(exerciseId)}/quiz/${key}`, {
      method: "POST",
      body: JSON.stringify({
        approved, body: body ?? null,
        ask_finished: approved && !!course, withdraw_asked: !approved && withdrawAsked,
        course_id: course?.courseId ?? null,
      }),
    }),
  /** Decide about a quiz answer that waits for the teacher (graded too low). */
  reviewAnswer: (exerciseId: string, probeId: number, action: "approve" | "return",
                 more?: { note?: string; grade?: number }) =>
    j<{ ok: boolean }>(`/api/pacing/${encodeURIComponent(exerciseId)}/answer-review`, {
      method: "POST",
      body: JSON.stringify({ probe_id: probeId, action, note: more?.note ?? null, grade: more?.grade ?? null }),
    }),
  decideStepCheck: (id: number, action: "approve" | "return", note: string) =>
    j<{ ok: boolean }>(`/api/step-checks/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    }),
  courses: () => j<Course[]>("/api/courses"),
  createCourse: (courseId: string, name: string) =>
    j<Course>("/api/courses", {
      method: "POST",
      body: JSON.stringify({ course_id: courseId, name }),
    }),
  updateCourse: (c: Course) =>
    j<Course>(`/api/courses/${encodeURIComponent(c.course_id)}`, {
      method: "PUT",
      body: JSON.stringify({
        name: c.name,
        exercises: c.exercises,
        default_exercise: c.default_exercise,
        members: c.members,
      }),
    }),
  deleteCourse: (courseId: string) =>
    j<{ ok: boolean }>(`/api/courses/${encodeURIComponent(courseId)}`, { method: "DELETE" }),
  users: () => j<UserAccount[]>("/api/users"),
  meetings: (courseId: string) => j<Meeting[]>(`/api/courses/${encodeURIComponent(courseId)}/meetings`),
  addMeeting: (courseId: string, date: string, exerciseId: string, title: string) =>
    j<Meeting>(`/api/courses/${encodeURIComponent(courseId)}/meetings`, {
      method: "POST",
      body: JSON.stringify({ date, exercise_id: exerciseId, title: title || null }),
    }),
  deleteMeeting: (id: number) => j<{ ok: boolean }>(`/api/meetings/${id}`, { method: "DELETE" }),
  attendance: (id: number) => j<Attendance>(`/api/meetings/${id}/attendance`),
  importStudents: (contentBase64: string, courseId: string | null, dryRun: boolean) =>
    j<RosterResult>("/api/students/import", {
      method: "POST",
      body: JSON.stringify({ content_base64: contentBase64, course_id: courseId, dry_run: dryRun }),
    }),
  // password null: back to the default (the login code).
  setPassword: (userId: number, password: string | null) =>
    j<{ ok: boolean; custom_password: boolean }>(`/api/users/${userId}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  deleteReview: (id: number, notify: boolean, note?: string) =>
    j<{ ok: boolean; student_told: "now" | "later" | "silent" }>(`/api/reviews/${id}/delete`, {
      method: "POST",
      body: JSON.stringify({ notify, note: note ?? null }),
    }),
  deleteStaleReviews: (notify: boolean) =>
    j<{ deleted: number }>("/api/reviews/delete-stale", {
      method: "POST",
      body: JSON.stringify({ notify }),
    }),
  /** Send an answer: a drafted one (its slot), the bank's or the teacher's own text;
   *  optionally saved into the question bank and sent to the whole class too. */
  selectReview: (id: number, chosen: AnswerSlot | "bank" | "own", lang: Lang, text?: string,
                 options?: { save_to_bank?: boolean; send_to_class?: boolean; level?: AnswerLevel }) =>
    j<SelectResult>(`/api/reviews/${id}/select`, {
      method: "POST",
      body: JSON.stringify({ chosen, lang, ...(text === undefined ? {} : { text }), ...(options ?? {}) }),
    }),
  // first run, settings, the students' link
  settings: () => j<Settings>("/api/settings"),
  testLlm: (provider: string, api_key?: string) =>
    j<KeyCheck>("/api/settings/llm/test", { method: "POST", body: JSON.stringify({ provider, api_key }) }),
  saveLlm: (provider: string, api_key?: string) =>
    j<{ llm: LlmStatus; check: KeyCheck }>("/api/settings/llm", {
      method: "POST", body: JSON.stringify({ provider, api_key }),
    }),
  saveChatLanguage: (language: ChatLanguage) =>
    j<{ chat_language: ChatLanguage }>("/api/settings/chat-language", {
      method: "POST", body: JSON.stringify({ language }),
    }),
  share: () => j<ShareInfo>("/api/share"),
  tunnel: (action: "start" | "stop" | "download", provider?: "cloudflared" | "ngrok") =>
    j<ShareInfo>("/api/share/tunnel", { method: "POST", body: JSON.stringify({ action, provider }) }),
  overview: () => j<Overview>("/api/overview"),
};
