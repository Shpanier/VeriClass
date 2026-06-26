export interface Student {
  session_id: string;
  username: string;
  exercise: string;
  variant: string;
  mode: "mentor" | "coding_partner";
  started_at: string;
  last_active_at: string;
  probe_count: number;
  // Exam/proctor signals (present when the student runs the CLion exam client).
  focus_alerts: number;
  last_focus_kind: string | null;
  last_focus_at: string | null;
  away: boolean;
}

export interface ProctorEvent {
  id: number;
  session_id: string;
  kind: string;
  detail: string | null;
  away_ms: number | null;
  created_at: string;
}

export interface ActiveExercise {
  exercise_id: string;
  title_en: string;
  title_he?: string;
  default_mode: string;
  brief_md: string;
  welcome_suggestions: string[];
  variants: Variant[];
}

export interface Variant {
  id: string;
  params: Record<string, unknown>;
  test_inputs: { input: string; expected_output: string }[];
}

export interface ProbeSuggestion {
  kind: string;
  body: string;
  rationale: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  body: string;
  mode_at_time: string;
  created_at: string;
}

export interface Probe {
  id: number;
  body: string;
  status: "pending" | "answered";
  answer: string | null;
  auto_grade: number | null;
  override_grade: number | null;
  source: string;
  sent_at: string;
  answered_at: string | null;
}

export interface SessionDetail {
  session: Student;
  messages: Message[];
  probes: Probe[];
}

export type AnswerLevel = "nudge" | "normal" | "more";
export type Lang = "en" | "he";

export interface PendingReview {
  id: number;
  session_id: string;
  username: string;
  question: string;
  // English variants.
  variant_nudge: string;
  variant_normal: string;
  variant_more: string;
  // Hebrew variants (may be null on rows created before the bilingual feature).
  variant_nudge_he: string | null;
  variant_normal_he: string | null;
  variant_more_he: string | null;
  created_at: string;
}
