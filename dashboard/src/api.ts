import type {
  ActiveExercise,
  AnswerLevel,
  ExerciseSummary,
  FullExercise,
  GradeRecommendation,
  Lang,
  NewExercise,
  PendingReview,
  ProbeSuggestion,
  ProctorEvent,
  SessionDetail,
  Student,
  Submission,
} from "./types";

const TOKEN_KEY = "oslab.teacher.token";

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

// Standalone (not via j): a wrong code legitimately returns 401 and must not be
// treated as a session-expiry bounce.
export async function login(code: string): Promise<LoginResult> {
  const r = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
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
  students: () => j<Student[]>("/api/students"),
  sessionDetail: (sessionId: string) =>
    j<SessionDetail>(`/api/students/${sessionId}/messages`),
  proctorEvents: (sessionId: string) =>
    j<ProctorEvent[]>(`/api/proctor/events?session_id=${encodeURIComponent(sessionId)}`),
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
  selectReview: (id: number, chosen: AnswerLevel, lang: Lang, text?: string) =>
    j<{ ok: boolean }>(`/api/reviews/${id}/select`, {
      method: "POST",
      body: JSON.stringify(text === undefined ? { chosen, lang } : { chosen, lang, text }),
    }),
};
