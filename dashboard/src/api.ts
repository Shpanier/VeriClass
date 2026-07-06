import type {
  ActiveExercise,
  AnswerLevel,
  Lang,
  PendingReview,
  ProbeSuggestion,
  ProctorEvent,
  SessionDetail,
  Student,
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
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
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
  students: () => j<Student[]>("/api/students"),
  sessionDetail: (sessionId: string) =>
    j<SessionDetail>(`/api/students/${sessionId}/messages`),
  proctorEvents: (sessionId: string) =>
    j<ProctorEvent[]>(`/api/proctor/events?session_id=${encodeURIComponent(sessionId)}`),
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
