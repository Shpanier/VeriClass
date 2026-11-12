package edu.jce.vericlass.api

/**
 * Data transfer objects mirroring the VeriClass backend JSON. Field names match
 * the backend exactly (snake_case) so Gson maps them with no annotations.
 */

data class LoginResponse(
    val token: String = "",
    val user_id: Int = 0,
    val username: String = "",
    val role: String = "student",
    /** The courses this user may open (backend/courses.py). Empty: no courses set up. */
    val courses: List<CourseDto> = emptyList(),
)

/** A course the student is in, with the exercises it offers and the preselected one. */
data class CourseDto(
    val course_id: String = "",
    val name: String = "",
    val default_exercise: String = "",
    val exercises: List<CourseExerciseDto> = emptyList(),
    /** The exercise of today's meeting in this course, if there is one (backend 0.4.3+). */
    val today_exercise: String? = null,
)

data class CourseExerciseDto(
    val exercise_id: String = "",
    val title_en: String = "",
    val title_he: String? = null,
)

data class SessionResponse(
    val session_id: String = "",
    /** Null when the student is in no course (the global active exercise). */
    val course_id: String? = null,
    val exercise_id: String = "",
    val variant: String = "",
    val mode: String = "",
    /** Signs this session's local trace (the student's export). Empty from older backends. */
    val trace_key: String = "",
)

data class TestInput(
    val input: String = "",
    val expected_output: String = "",
)

data class Variant(
    val id: String = "",
    /** Arbitrary per-variant parameters (e.g. max_number, operators, allow_parens). */
    val params: Map<String, Any?> = emptyMap(),
    val test_inputs: List<TestInput> = emptyList(),
)

/** Exercise-level friendly label for a variant param key (connects it to the exercise). */
data class ParamLabel(
    val key: String = "",
    val label: String? = null,
    val note: String? = null,
)

data class Exercise(
    val exercise_id: String = "",
    val title_en: String = "",
    val title_he: String? = null,
    val default_mode: String = "mentor",
    val brief_md: String = "",
    val welcome_suggestions: List<String> = emptyList(),
    val required_error_strings: List<String> = emptyList(),
    val param_labels: List<ParamLabel> = emptyList(),
    /** Present when the active-exercise call is made with a ?variant= query. */
    val variant: Variant? = null,
    /** What the VeriClass terminal allows for this exercise. Null from a backend without terminal support. */
    val terminal: TerminalPolicyDto? = null,
    /** Step-by-step labs: how many steps, and the one this student is on (0: no steps / older backend). */
    val steps_total: Int = 0,
    val step_current: Int = 0,
    /** Run on a step submission and attached for the teacher, e.g. "python checks.py". */
    val check_command: String? = null,
    /** "class": a class-paced lab; the chat shows one step at a time from /api/steps/state. */
    val pacing: String? = null,
) {
    val isClassPaced: Boolean get() = pacing == "class"
}

/** The exercise's terminal rules: which programs may run, and whether student scripts may. */
data class TerminalPolicyDto(
    val allow: List<String> = emptyList(),
    val scripts: Boolean = true,
    /** Shown under every refused line: where to run the command instead. */
    val blocked_hint: String? = null,
)

/** A question the chat asks the student: one the teacher sent, or a class-paced lab's quiz question. */
data class Probe(
    val id: Int = 0,
    val body: String = "",
    /** "quiz" for a question after a step; otherwise how the teacher wrote it. */
    val source: String? = null,
    /** A quiz question's step, by its label (e.g. "B6"). */
    val quiz_step: String? = null,
)

data class ProbeAnswerResponse(
    /** Null when grading was unavailable (the answer was still saved). */
    val auto_grade: Int? = null,
    val why: String? = null,
    /** Graded too low to move on by itself (exercise.yaml quiz_review): the teacher decides. */
    val review: Boolean = false,
)

/**
 * POST /api/probes/classify: is a message the open question's answer? kind:
 * none (no question is open), step (the open step's output), answer, or maybe
 * (ask the student).
 */
data class ClassifyResponse(
    val kind: String = "none",
    val probe: Probe? = null,
)

// --- class-paced labs (backend/pacing.py) -----------------------------------------

/** GET /api/steps/state: where the student is in a class-paced lab. */
data class StepStateResponse(
    val total: Int = 0,
    val current: Int = 0,
    val current_label: String? = null,
    val released: Int = 0,
    val finished: Boolean = false,
    val quiz_pending: Int = 0,
    /** Finished every open step: the teacher opens the next one. */
    val waiting_teacher: Boolean = false,
    val open: Boolean = false,
    /** Their last output didn't match; it waits for the teacher. */
    val waiting_review: Boolean = false,
    /** Quiz answers of theirs graded too low: the teacher lets them continue or asks again. */
    val quiz_review: Int = 0,
    /** The open step (when [open]). */
    val step: OpenStep? = null,
)

data class OpenStep(
    val n: Int = 0,
    val label: String = "",
    val title: String = "",
    val markdown: String = "",
    /** The step checks a pasted output (else "Done" needs no text). */
    val needs_output: Boolean = false,
)

/** POST /api/steps/finish. status: done, missing, wrong_step, not_open, quiz_pending, quiz_review, finished. */
data class FinishResponse(
    val status: String = "",
    val ok: Boolean? = null,
    /** Quiz questions asked now, after the step. */
    val quiz: Int? = null,
    val state: StepStateResponse? = null,
)

/** POST /api/steps/detect: is a chat message the open step's answer? kind: output, maybe, question. */
data class DetectResponse(
    val kind: String = "question",
    val step: Int = 0,
    val label: String = "",
    val needs_output: Boolean = true,
)

// --- the session's transcript (backend/transcript.py) --------------------------------

data class TranscriptEntry(
    val id: Int = 0,
    /** student | tutor | system */
    val author: String = "tutor",
    /** text, brief, step, output, result, quiz, answer, note, reset, returned */
    val kind: String = "text",
    val step: Int? = null,
    val content: String = "",
    /** client (a student's chat wrote it) | server (the server's own note) */
    val origin: String = "client",
)

data class TranscriptResponse(
    /** False when the exercise keeps no transcript (exercise.yaml chat_history: false). */
    val enabled: Boolean = false,
    val entries: List<TranscriptEntry> = emptyList(),
    /** Older entries were left out (CHAT_HISTORY_REPLAY_MAX). */
    val truncated: Boolean = false,
    val last_id: Int = 0,
)

/** GET /api/reviews/open: a question of the student's still with the teacher. */
data class OpenReview(
    val id: Int = 0,
    val question: String = "",
)

/** Returned by POST /api/submissions when the student sends work to the teacher. */
data class SubmitResponse(
    val ok: Boolean = false,
    val id: Int = 0,
)

/** Returned by GET /api/client-config; drives chat-only vs. IDE-native behavior. */
data class ClientConfig(
    val mode: String = "chat",
    val scaffold_filename: String = "mcalc.c",
    val poll_interval_ms: Int = 2000,
    /** Exam mode: report to the backend whenever the student leaves the IDE. */
    val exam_mode: Boolean = false,
    /** Put the IDE in full screen at exam start and re-assert it on return. */
    val force_fullscreen: Boolean = false,
    /** Keep the IDE window maximized; a smaller window is reported. Null from older backends. */
    val exam_maximized: Boolean? = null,
    /** How often to send the live status (also sent on every change). */
    val heartbeat_ms: Int = 10000,
    /** Exam: panels allowed besides the VeriClass chat and terminal (tool window ids, e.g. "Run"). */
    val exam_allowed_tool_windows: List<String> = emptyList(),
    /** Dev-only: if the backend has DEV_AUTO_LOGIN_CODE set, the plugin auto-logs
     *  in with this. Empty in exam/production. Mirrors the Chainlit student app. */
    val dev_auto_login_code: String = "",
) {
    val isIdeMode: Boolean get() = mode.equals("ide", ignoreCase = true)
    val isExamMode: Boolean get() = exam_mode
    /** Older backends don't send exam_maximized: keep the window maximized whenever exam mode is on. */
    val isMaximizedMode: Boolean get() = exam_mode && (exam_maximized ?: true)
}
