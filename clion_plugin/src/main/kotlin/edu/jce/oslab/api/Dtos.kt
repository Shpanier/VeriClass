package edu.jce.oslab.api

/**
 * Data transfer objects mirroring the OS Lab backend JSON. Field names match
 * the backend exactly (snake_case) so Gson maps them with no annotations.
 */

data class LoginResponse(
    val token: String = "",
    val user_id: Int = 0,
    val username: String = "",
    val role: String = "student",
)

data class SessionResponse(
    val session_id: String = "",
    val exercise_id: String = "",
    val variant: String = "",
    val mode: String = "",
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
)

data class Probe(
    val id: Int = 0,
    val body: String = "",
)

data class ProbeAnswerResponse(
    val auto_grade: Int = 0,
    val why: String = "",
)

/** Returned by GET /api/client-config; drives chat-only vs. IDE-native behavior. */
data class ClientConfig(
    val mode: String = "chat",
    val scaffold_filename: String = "mcalc.c",
    val poll_interval_ms: Int = 2000,
    /** Exam mode: report to the backend whenever the student leaves the IDE. */
    val exam_mode: Boolean = false,
    /** Put CLion in full screen at exam start and re-assert it on return. */
    val force_fullscreen: Boolean = false,
    /** How often to ping the backend so a quiet exam student stays on the grid. */
    val heartbeat_ms: Int = 30000,
) {
    val isIdeMode: Boolean get() = mode.equals("ide", ignoreCase = true)
    val isExamMode: Boolean get() = exam_mode
}
