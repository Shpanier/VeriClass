import type {
  ActiveExercise,
  AnswerLevel,
  Course,
  ExerciseSummary,
  FullExercise,
  GradeRecommendation,
  Lang,
  NewExercise,
  PackageResult,
  Paste,
  PendingReview,
  ProbeSuggestion,
  ProctorEvent,
  RegenModel,
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

const TOKEN_KEY = "veriexam.teacher.token";

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
  const r = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (r.status === 401 || r.status === 403) {
    auth.clear();
    onUnauthorized?.();
    throw new Error(`${r.status} unauthorized`);
  }
  if (!r.ok) {
    // Surface FastAPI's `detail` (or a 422 validation summary) so callers like
    // the exercise-authoring form can show why a request was rejected.
    const detail = await readErrorDetail(r);
    throw new Error(detail || `${r.status} ${r.statusText}`);
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
  const r = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, password }),
  });
  if (r.status === 401) throw new Error("bad-code");
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
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
  reviewConfig: () => j<{ regen_models: RegenModel[] }>("/api/reviews/config"),
  regenerateReview: (id: number, model: RegenModel["key"]) =>
    j<PendingReview>(`/api/reviews/${id}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  pendingStepChecks: () => j<StepChecksResponse>("/api/step-checks/pending"),
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
  selectReview: (id: number, chosen: AnswerLevel | "bank", lang: Lang, text?: string) =>
    j<{ ok: boolean }>(`/api/reviews/${id}/select`, {
      method: "POST",
      body: JSON.stringify(text === undefined ? { chosen, lang } : { chosen, lang, text }),
    }),
};
