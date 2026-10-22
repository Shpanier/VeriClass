package edu.jce.veriexam.api

/**
 * Data transfer objects mirroring the VeriExam backend JSON. Field names match
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
    /** What the VeriExam terminal allows for this exercise. Null from a backend without terminal support. */
    val terminal: TerminalPolicyDto? = null,
)

/** The exercise's terminal rules: which programs may run, and whether student scripts may. */
data class TerminalPolicyDto(
    val allow: List<String> = emptyList(),
    val scripts: Boolean = true,
)

data class Probe(
    val id: Int = 0,
    val body: String = "",
)

data class ProbeAnswerResponse(
    val auto_grade: Int = 0,
    val why: String = "",
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
    /** Exam: panels allowed besides the VeriExam chat and terminal (tool window ids, e.g. "Run"). */
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
