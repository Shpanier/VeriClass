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
  // VeriExam terminal: refused commands + attempts to open the IDE's own
  // Terminal, and how many lines the student entered in total.
  terminal_alerts?: number;
  terminal_count?: number;
  // Inside-the-IDE alerts: panels/windows that aren't allowed + pastes from outside.
  ide_alerts?: number;
  paste_count?: number;
  // Live state from the exam client's status snapshot (see backend students.exam_state).
  exam_state?: ExamState | null;
  exam_state_detail?: string | null;
  live?: LiveStatus | null;
  live_age_s?: number | null;
  last_alert_kind?: string | null;
  last_alert_detail?: string | null;
  last_alert_at?: string | null;
}

export type ExamState = "ok" | "away" | "other_window" | "not_fullscreen" | "not_maximized" | "ide_closed" | "no_signal";

// What the exam client sends with every heartbeat and on every change.
export interface LiveStatus {
  focused?: boolean;
  fullscreen?: boolean;
  fullscreen_supported?: boolean;
  tool_windows?: string[];
  forbidden_tool_windows?: string[];
  other_windows?: string[];
  open_files?: string[];
  active_file?: string | null;
  violations?: number;
  unsent_reports?: number;
}

// One paste the exam client saw (GET /api/proctor/pastes).
export interface Paste {
  id: number;
  target: "editor" | "terminal" | "chat" | "other";
  source: "outside" | "ide" | "tutor";
  chars: number;
  lines: number;
  text: string;
  file: string | null;
  client_at: string | null;
  via: "live" | "export";
  created_at: string;
}

// POST /api/trace/verify: a student's exported log, checked.
export interface TraceVerifyRow {
  seq: number | null;
  kind: string;
  client_id: string;
  at_utc: string;
  valid: boolean;
  on_server: boolean | null;
  imported: boolean;
  summary: string;
}

export interface TraceVerifyResult {
  ok: boolean;
  error: string | null;
  session_id?: string;
  student?: string | null;
  complete?: boolean;
  valid_rows?: number;
  first_bad_seq?: number | null;
  missing_on_server?: number;
  imported?: number;
  rows: TraceVerifyRow[];
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
  // When it happened on the student's machine (a report can arrive late).
  client_at?: string | null;
  via?: "live" | "export";
  created_at: string;
}

// One line from a student's VeriExam terminal (GET /api/terminal/commands).
export interface TerminalCommand {
  id: number;
  session_id: string;
  line: string;
  cwd: string | null;
  // false = the plugin refused it; it never ran.
  allowed: boolean;
  reason: string | null;
  commands: string[];
  // Refused only because it didn't parse (unclosed quote) — not a violation.
  syntax_error: boolean;
  exit_code: number | null;
  duration_ms: number | null;
  output_tail: string | null;
  // Full output, sent in pieces (GET /api/terminal/commands/{id}/output).
  output_chars?: number | null;
  output_chunks?: number | null;
  client_at?: string | null;
  via?: "live" | "export";
  created_at: string;
  // Plugin 0.3.1+: which OS and shell ran the line (it can behave differently on each).
  client_os?: string | null;
  shell?: string | null;
}

export interface TerminalFullOutput {
  output: string;
  complete: boolean;
  chunks: number;
  expected_chunks: number;
  chars: number | null;
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
  // Terminal commands that break on Windows or macOS (backend/portability.py).
  os_errors?: number;
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
  /** The LLM that wrote this reply (null: teacher, lab steps, older rows). */
  model?: string | null;
  /** 1: served from the answer cache, no LLM call. */
  cached?: number;
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

// Three Socratic levels and a direct (non-Socratic) answer.
export type AnswerLevel = "nudge" | "normal" | "more" | "direct";
export type Lang = "en" | "he";

// The closest question-bank entry to a student's question (backend/bank.py).
export interface BankMatch {
  id: string;
  step: number | null;
  question: string;
  score: number; // 0..1
  answers: Partial<Record<AnswerLevel, { en: string; he: string }>>;
}

// A model the teacher can have the four answers drafted again with.
export interface RegenModel {
  key: "strong" | "best";
  model: string;
  label: string;
}

export interface PendingReview {
  id: number;
  session_id: string;
  username: string;
  exercise_id?: string;
  question: string;
  // English variants.
  variant_nudge: string;
  variant_normal: string;
  variant_more: string;
  variant_direct: string | null; // null on rows from before the direct answer existed
  // Hebrew variants (may be null on rows created before the bilingual feature).
  variant_nudge_he: string | null;
  variant_normal_he: string | null;
  variant_more_he: string | null;
  variant_direct_he: string | null;
  created_at: string;
  /** The model that drafted the answers; regenerated_at is set after "redo with". */
  model: string | null;
  regenerated_at: string | null;
  /** The language the student wrote in: the card opens on it. */
  suggested_lang: Lang;
  bank_match: BankMatch | null;
}

export interface StepCheck {
  id: number;
  session_id: string;
  username: string;
  exercise_id?: string;
  step: number;
  total: number;
  title: string;
  answer: string;
  expected: string;
  created_at: string;
  /** How many questions the step asks, and roughly how many this answer covers. */
  questions: number | null;
  answered: number | null;
  evidence: StepEvidence;
  /** What the plugin attached (0.4.3+): the open file, Run console, check output. */
  code: { filename: string | null; source: string | null; console: string | null; check_output: string | null } | null;
}

export interface StepEvidence {
  // The step's evidence rules (teacher file): the last matching command, and whether its output fits.
  rules: { label: string; found: boolean; line: string | null; output: string | null; ok: boolean | null }[];
  // The session's last terminal lines since its previous decided step.
  recent: { line: string; allowed: boolean; exit_code: number | null; output: string; at: string }[];
}

export interface StepChecksResponse {
  has_steps: boolean;
  items: StepCheck[];
}

// A course (GET /api/courses): who is in it, which exercises it offers, and the
// one preselected for students after login (backend/courses.py).
export interface Course {
  course_id: string;
  name: string;
  default_exercise: string | null;
  exercises: string[];
  members: number[]; // user ids
}

// POST /api/students/import: one CSV row and what happens to it (backend/roster.py).
export interface RosterRow {
  line: number;
  name: string;
  username?: string; // when two different people share a name
  email?: string;
  student_id?: string;
  course?: string | null;
  group?: string;
  status?: "new" | "existing";
  error?: string;
  code?: string;
  user_id?: number;
}

export interface RosterResult {
  rows: RosterRow[];
  counts: { new: number; existing: number; errors: number };
  columns: string[];
  codes_csv?: string; // after an import (not a preview)
}

// One account (GET /api/users). custom_password is false while the password is
// still the login code.
export interface UserAccount {
  id: number;
  username: string;
  login_code: string;
  role: "student" | "teacher";
  custom_password: boolean;
  courses: string[];
}
