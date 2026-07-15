export interface Student {
  session_id: string;
  username: string;
  exercise: string;
  variant: string;
  mode: "mentor" | "coding_partner";
  started_at: string;
  last_active_at: string;
  probe_count: number;
  // How many times the student has pressed "Send to teacher" in the plugin.
  submission_count?: number;
  // Recommended grade summary (present once a teacher has computed one).
  recommended_grade?: number | null;
  grade_band?: string | null;
  grade_override?: number | null;
  // This session's variant parameters (raw), for readable rendering.
  variant_params?: Record<string, unknown>;
  // Exam/proctor signals (present when the student runs the CLion exam client).
  focus_alerts: number;
  last_focus_kind: string | null;
  last_focus_at: string | null;
  away: boolean;
}

// Exercise-level label for a variant param key (connects it to the exercise).
export interface ParamLabel {
  key: string;
  label?: string | null;
  note?: string | null;
}

// One test case from the plugin's actual compile/run of the submission.
export interface RunCase {
  input: string;
  expected: string;
  actual: string;
  passed: boolean;
}

// One "Send to teacher" submission: a source file + captured console output,
// plus the plugin's real compile/run result when available.
export interface Submission {
  id: number;
  session_id: string;
  filename: string | null;
  source_code: string;
  console_output: string | null;
  language?: string | null;
  compile_ok?: number | null;
  compile_output?: string | null;
  run_report?: RunCase[] | null;
  created_at: string;
}

// The recommended grade for a session (GET /api/grade/{session_id} or the
// POST /api/grade/recommend result). Correctness is deterministic from the run;
// wise_use is the LLM judge; recommended = 0.3*correctness + 0.7*wise_use.
export interface GradeRecommendation {
  session_id: string;
  submission_id: number | null;
  correctness: number | null;
  wise_use: number | null;
  recommended: number | null;
  band: string | null;
  rationale: string | null;
  components: { signals?: string[]; features?: unknown } | null;
  override_grade: number | null;
  created_at: string;
  updated_at: string;
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
  required_error_strings?: string[];
  param_labels?: ParamLabel[];
  variants: Variant[];
}

export interface Variant {
  id: string;
  params: Record<string, unknown>;
  test_inputs: { input: string; expected_output: string }[];
}

// One row in the teacher's Exercises tab (GET /api/exercises).
export interface ExerciseSummary {
  exercise_id: string;
  title_en: string;
  title_he?: string | null;
  default_mode: string;
  variant_count: number;
  source: "yaml" | "console";
  edited: boolean; // a built-in (yaml) exercise that a teacher has overridden
  is_active: boolean;
}

// The full exercise (GET /api/exercises/{id}) — used to prefill edit/duplicate.
export interface FullExercise {
  exercise_id: string;
  title_en: string;
  title_he?: string | null;
  default_mode: "mentor" | "coding_partner";
  brief_md: string;
  variants: Variant[];
  welcome_suggestions: string[];
  required_error_strings: string[];
  param_labels: ParamLabel[];
  source: "yaml" | "console";
  edited: boolean;
}

// The payload the authoring form POSTs (create) or PUTs (edit).
export interface NewExercise {
  exercise_id: string;
  title_en: string;
  title_he?: string;
  default_mode: "mentor" | "coding_partner";
  brief_md: string;
  variants: Variant[];
  welcome_suggestions?: string[];
  required_error_strings?: string[];
  param_labels?: ParamLabel[];
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
