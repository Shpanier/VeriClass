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

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
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
  suggestProbes: (sessionId: string) =>
    j<ProbeSuggestion[]>("/api/probe/suggest", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
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
