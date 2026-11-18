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
  // VeriClass terminal: refused commands + attempts to open the IDE's own
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

// One line from a student's VeriClass terminal (GET /api/terminal/commands).
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
  // package: a folder in the private data folder (backend/packages.py).
  source: "yaml" | "console" | "package";
  edited: boolean; // a built-in (yaml) exercise that a teacher has overridden
  is_active: boolean;
  // Terminal commands that break on Windows or macOS (backend/portability.py).
  os_errors?: number;
  steps?: number;
  bank_questions?: number;
  folder?: string | null;
  /** When it came to this server and when it last changed (UTC, ISO 8601). */
  added_at?: string | null;
  changed_at?: string | null;
}

/** A check a pasted output must pass: a regular expression, searched line by line. */
export interface OutputCheck {
  match: string;
  hint?: string | null;
}

// One step of a step-by-step lab, as the teacher edits it (all but title/text/minutes are teacher-only).
export interface StepDraft {
  title: string;
  text: string;
  minutes?: number | null;
  expected?: string | null;
  questions?: number | null;
  /** What the step's commands print; the teacher compares pasted outputs with it. */
  expected_output?: string | null;
  /** Checks a pasted output must pass to move the student on (class-paced labs). */
  expect_output?: OutputCheck[] | null;
}

// POST /api/exercises/import or /install: a package checked (and installed if ok).
export interface PackageResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  summary: { exercise_id?: string; title_en?: string; title_he?: string | null; steps?: number;
             bank_questions?: number; folder?: string };
  installed_to?: string;
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
  source: "yaml" | "console" | "package";
  edited: boolean;
  scaffold_filename?: string | null;
  terminal?: Record<string, unknown> | null;
  tutor_notes?: string | null;
  language?: string | null;
  course_name?: string | null;
  check_command?: string | null;
  /** Keep the chat's transcript and replay it after a new login (default true). */
  chat_history?: boolean;
  /** How recent a session must be to be resumed; 0 = always (the effective value). */
  resume_minutes?: number;
  /** resume_minutes is set in the exercise (not the default). */
  resume_minutes_set?: boolean;
  /** A step's output pasted as a chat message: accept it, ask the student, or ignore. */
  output_in_chat?: "confirm" | "accept" | "ask" | "off";
  /** A chat message while a quiz/teacher's question is open: its answer, or ask the student. */
  answer_in_chat?: AnswerInChat;
  /** Which quiz grades wait for the teacher before the next step. */
  quiz_review?: QuizReview;
  steps?: StepDraft[];
  /** No variants: every student gets the same exercise. */
  implicit_variant?: boolean;
  bank_questions?: number;
  download_name?: string | null;
  folder?: string | null;
  /** "class": the teacher opens steps for the whole class (backend/pacing.py). */
  pacing?: "class" | "pair" | null;
  open_steps?: number | null;
  workspace?: "codespace" | "ide" | null;
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
  terminal?: Record<string, unknown> | null;
  tutor_notes?: string;
  language?: string;
  course_name?: string;
  check_command?: string;
  chat_history?: boolean;
  resume_minutes?: number;
  output_in_chat?: "confirm" | "accept" | "ask" | "off";
  answer_in_chat?: AnswerInChat;
  quiz_review?: QuizReview;
  steps?: StepDraft[];
}

/** backend/open_questions.py: detect (default) | confirm | answer. */
export type AnswerInChat = "detect" | "confirm" | "answer";

/** backend/pacing.py: a quiz answer graded 0/2 or 1/2 (partial, the default:
 *  only 2/2 moves on by itself), 0/2 (zero), or never (off) waits for the
 *  teacher before the next step. */
export type QuizReview = "zero" | "partial" | "off";

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

/** Which answer: the four levels by the default model, or the best model's. */
export type AnswerSlot = AnswerLevel | "best";

/** One drafted answer of a question (one model call each, GET /api/reviews/pending). */
export interface ReviewAnswer {
  id: number | null; // null: a question from before answers had rows of their own
  slot: AnswerSlot;
  level: AnswerLevel;
  model: string | null;
  /** The model's short name ("Opus 5.5"). */
  label: string | null;
  status: "drafting" | "ready" | "failed";
  text_en: string | null;
  text_he: string | null;
  error: string | null;
  /** How long the draft took. */
  seconds: number | null;
  ready_at: string | null;
}

export interface PendingReview {
  id: number;
  session_id: string;
  username: string;
  exercise_id?: string;
  course_id: string | null;
  question: string;
  created_at: string;
  /** The default drafting model; regenerated_at is set after "redo with". */
  model: string | null;
  regenerated_at: string | null;
  /** The finished answers (ready or failed), in the order they finished. */
  answers: ReviewAnswer[];
  /** The answers still being written. */
  drafting: ReviewAnswer[];
  /** The language the student wrote in: the card opens on it. */
  suggested_lang: Lang;
  bank_match: BankMatch | null;
  /** The student's request is still open for it; otherwise an answer reaches them later. */
  waiting: boolean;
  /** Most likely sent by mistake (empty, a few characters, no letters). */
  looks_like_noise: boolean;
  /** The language the question is written in (ISO 639-1), when the drafting model named it. */
  question_lang: string | null;
  /** The question translated into `translated_to`, when it is in neither Hebrew nor English. */
  question_translation: string | null;
  translated_to: Lang | null;
  /** The step the student is on (null for a lab without steps). */
  step: ReviewStep | null;
  /** The chat just before the question. */
  before: ReviewBefore;
}

export type ReviewStepStatus =
  | "open" | "waiting_teacher" | "waiting_review" | "quiz" | "quiz_review" | "waiting_check" | "not_started"
  | "finished";

/** Where a student is in a step-by-step lab (backend/whereabouts.py). */
export interface ReviewStep {
  n: number;
  total: number;
  /** The step's name in messages: its label (e.g. "B3") or its number. */
  label: string;
  title: string;
  status: ReviewStepStatus;
}

/** One chat entry before the question: the transcript's author and kind, or a model turn. */
export interface ReviewChatEntry {
  author: "student" | "tutor" | "system";
  kind: string;
  step: number | null;
  content: string;
  created_at: string;
}

export interface ReviewBefore {
  /** transcript = the chat as the student saw it; messages = the model turns (no transcript kept). */
  source: "transcript" | "messages";
  entries: ReviewChatEntry[];
}

/** The language questions in other languages are translated into for the queue. */
export type TranslateTo = Lang | "off";

export interface ReviewConfig {
  regen_models: RegenModel[];
  translate_to: TranslateTo;
  /** The extra answer by the best model (CLAUDE_BEST_MODEL). */
  best_answer: {
    available: boolean;
    enabled: boolean;
    model: string | null;
    label: string | null;
    level: AnswerLevel;
  };
  /** The default of the "save to the question bank" box. */
  save_to_bank: boolean;
  /** "All students" = those active on the exercise in the last this many minutes. */
  class_minutes: number;
}

/** What a send did (POST /api/reviews/{id}/select). */
export interface SelectResult {
  ok: boolean;
  delivered?: "now" | "later";
  saved_to_bank: boolean;
  sent_to_class: number;
  class_skipped?: number;
  bank_error?: string;
  class_error?: string;
}

// Class-paced labs (GET /api/pacing/{exercise_id}).
export interface PacingStep {
  n: number;
  label: string;
  title: string;
  minutes?: number | null;
  /** The step checks the pasted output. */
  checked: boolean;
  /** teacher.yaml: the answer in words, what the commands print, and what each check looks for. */
  expected: string;
  expected_output: string;
  hints: string[];
  quiz: number;
  quiz_approved: number;
}

export interface PacingQuizItem {
  key: string;
  step: number;
  label: string;
  /** The package's wording. */
  q: string;
  /** The teacher's wording (the package's until edited). */
  body: string;
  answer: string;
  approved: boolean;
}

/** One quiz question a student was asked, with their answer (once given). */
export interface PacingAnswer {
  id: number;
  key: string;
  step: number;
  body: string;
  answer: string | null;
  status: string;
  grade: number | null;
  /** waiting: graded too low, the teacher decides · approved · returned (asked again) · reset ·
   *  skipped (moved past it) · withdrawn (the question was withdrawn). */
  review: "waiting" | "approved" | "returned" | "reset" | "skipped" | "withdrawn" | null;
  /** The grader's one-line reason. */
  why: string | null;
  answered_at: string | null;
}

export interface PacingStudent {
  session_id: string;
  username: string;
  current: number;
  current_label: string | null;
  last_active_at: string;
  quiz_pending: number;
  /** Opened for this student beyond the course (the teacher moved them forward). */
  released_to: number | null;
  /** Labels of the steps the teacher moved them past without doing them. */
  skipped: string[];
  /** Quiz answers of theirs graded too low: they wait for the teacher's decision. */
  quiz_review: number;
  /** Their output for the current step didn't match: it waits for the teacher. */
  waiting: { step: number; label: string; missing: string[]; output: string; created_at: string }[];
  /** Steps the teacher let them past although the output didn't match. */
  flags: { step: number; label: string; missing: string[]; output: string }[];
  quiz: PacingAnswer[];
}

export interface PacingCourse {
  course_id: string;
  name: string;
  released: number;
  members: number | null;
  students: PacingStudent[];
  done: Record<string, number>;
  here: Record<string, number>;
  /** Per question key: students past its step who were never asked it. */
  quiz_missed: Record<string, number>;
}

export interface PacingOverview {
  exercise_id: string;
  total: number;
  open_steps: number;
  steps: PacingStep[];
  quiz: PacingQuizItem[];
  courses: PacingCourse[];
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

// A course meeting (GET /api/courses/{id}/meetings): on its date the course's
// students open its exercise without choosing.
export interface Meeting {
  id: number;
  course_id: string;
  meeting_date: string; // YYYY-MM-DD
  exercise_id: string;
  exercise_title: string | null;
  title: string | null;
  members: number;
  attended: number;
}

export interface AttendanceRow {
  user_id: number;
  username: string;
  email: string | null;
  group: string | null;
  attended: boolean;
  first_seen: string | null;
  last_seen: string | null;
  messages: number;
  steps_approved: number;
  step_submissions: number;
}

export interface Attendance {
  meeting: Meeting;
  rows: AttendanceRow[];
  counts: { members: number; attended: number };
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

/** One entry of a session's chat transcript (GET /api/transcript/{session_id}). */
export interface TranscriptEntry {
  id: number;
  author: "student" | "tutor" | "system";
  kind: string;
  step: number | null;
  content: string;
  origin: "client" | "server";
  created_at: string;
}

export interface TranscriptResponse {
  enabled: boolean;
  entries: TranscriptEntry[];
  truncated: boolean;
  last_id: number;
}
