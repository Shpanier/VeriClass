package edu.jce.veriexam.api

import com.google.gson.Gson
import com.intellij.openapi.diagnostic.thisLogger
import edu.jce.veriexam.settings.VeriExamSettings
import java.io.InputStreamReader
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.atomic.AtomicBoolean

/** Raised for any non-2xx backend response, carrying a student-friendly message. */
class VeriExamApiException(message: String) : RuntimeException(message)

// Sent on every request so ngrok-free serves the API directly instead of its
// HTML "you are about to visit" interstitial (which would break JSON parsing).
// Harmless when the backend is reached directly (localhost / LAN / Cloudflare).
private const val NGROK_HEADER = "ngrok-skip-browser-warning"

/**
 * Thin client over the six student-facing VeriExam endpoints. All calls are
 * blocking and MUST be invoked off the EDT (use a pooled thread). The base URL
 * is read fresh from settings on every call so changing it takes effect without
 * a restart.
 */
class VeriExamApiClient {

    private val gson = Gson()
    private val http: HttpClient = HttpClient.newBuilder()
        // Pin HTTP/1.1. The default (HTTP/2) attempts an h2c upgrade on cleartext
        // http:// and drops the POST body against an HTTP/1.1 server (uvicorn),
        // so every POST arrives empty and the backend returns 422 "Field
        // required". uvicorn speaks HTTP/1.1 anyway, and 1.1 chunked transfer is
        // exactly what the streamed /api/ask reader expects.
        .version(HttpClient.Version.HTTP_1_1)
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    private val baseUrl: String get() = VeriExamSettings.instance.backendUrl

    // --- auth & setup -----------------------------------------------------

    fun login(code: String): LoginResponse {
        val resp = sendJson(
            "POST", "/api/login",
            body = mapOf("code" to code.trim().uppercase()),
            token = null,
        )
        if (resp.statusCode() == 401) {
            throw VeriExamApiException("Code not found. Ask the instructor for your code.")
        }
        requireOk(resp, "Login failed")
        return gson.fromJson(resp.body(), LoginResponse::class.java)
    }

    fun startSession(token: String): SessionResponse {
        val resp = sendJson("POST", "/api/sessions", body = emptyMap<String, Any>(), token = token)
        requireOk(resp, "Could not start a session")
        return gson.fromJson(resp.body(), SessionResponse::class.java)
    }

    fun activeExercise(variant: String, token: String): Exercise {
        // Authenticated now: the backend only hands a student their own variant,
        // never the full set (which would leak every variant's expected outputs).
        val resp = sendJson(
            "GET",
            "/api/exercises/active?variant=" + encode(variant),
            body = null,
            token = token,
        )
        requireOk(resp, "Could not load the exercise")
        return gson.fromJson(resp.body(), Exercise::class.java)
    }

    /** Tolerant: any failure falls back to plain chat mode so the client still works. */
    fun clientConfig(): ClientConfig {
        return try {
            val resp = sendJson("GET", "/api/client-config", body = null, token = null)
            if (resp.statusCode() != 200) ClientConfig()
            else gson.fromJson(resp.body(), ClientConfig::class.java) ?: ClientConfig()
        } catch (e: Exception) {
            ClientConfig()
        }
    }

    // --- chat (streaming) -------------------------------------------------

    /**
     * POST /api/ask and stream the plain-text response. [onToken] is called on
     * the calling thread for each decoded chunk; callers marshal to the EDT.
     * Reading stops early if [cancelled] flips to true. Long timeout: review
     * mode holds the response until the teacher picks a variant.
     */
    fun ask(
        token: String,
        sessionId: String,
        message: String,
        cancelled: AtomicBoolean,
        onToken: (String) -> Unit,
    ) {
        val request = HttpRequest.newBuilder(URI.create(baseUrl + "/api/ask"))
            .header("Authorization", "Bearer $token")
            .header("Content-Type", "application/json")
            .header(NGROK_HEADER, "true")
            // This client renders Markdown (chat bubbles); older ones got plain text.
            .header("X-VeriExam-Render", "markdown")
            .timeout(Duration.ofMinutes(10))
            .POST(
                HttpRequest.BodyPublishers.ofString(
                    gson.toJson(mapOf("session_id" to sessionId, "message" to message)),
                    StandardCharsets.UTF_8,
                ),
            )
            .build()

        val resp = http.send(request, HttpResponse.BodyHandlers.ofInputStream())
        if (resp.statusCode() != 200) {
            val detail = resp.body().use { it.readBytes().toString(StandardCharsets.UTF_8) }
            throw VeriExamApiException(friendlyError(resp.statusCode(), detail))
        }
        // InputStreamReader buffers and decodes UTF-8 correctly across chunk
        // boundaries (important for Hebrew briefings / multibyte tokens).
        resp.body().use { stream ->
            val reader = InputStreamReader(stream, StandardCharsets.UTF_8)
            val buf = CharArray(1024)
            while (!cancelled.get()) {
                val n = reader.read(buf)
                if (n == -1) break
                if (n > 0) onToken(String(buf, 0, n))
            }
        }
    }

    // --- probes -----------------------------------------------------------

    fun pendingProbes(sessionId: String, token: String): List<Probe> {
        val resp = sendJson(
            "GET", "/api/probes/pending/" + encode(sessionId), body = null, token = token,
        )
        if (resp.statusCode() != 200) return emptyList()
        val arr = gson.fromJson(resp.body(), Array<Probe>::class.java) ?: return emptyList()
        return arr.toList()
    }

    fun answerProbe(probeId: Int, answer: String, token: String): ProbeAnswerResponse {
        val resp = sendJson(
            "POST", "/api/probes/answer",
            body = mapOf("probe_id" to probeId, "answer" to answer),
            token = token,
        )
        requireOk(resp, "Could not submit your answer")
        return gson.fromJson(resp.body(), ProbeAnswerResponse::class.java)
    }

    // --- submit work to teacher ------------------------------------------

    /**
     * POST the student's current source file + captured console output to the
     * teacher's dashboard, plus the real compile/run result when available (so
     * the recommended-grade correctness score is grounded in actual execution).
     * Blocking; call off the EDT.
     */
    fun submitWork(
        token: String,
        sessionId: String,
        filename: String?,
        source: String,
        console: String?,
        run: edu.jce.veriexam.ide.RunResult? = null,
    ): SubmitResponse {
        val body = mutableMapOf<String, Any>("session_id" to sessionId, "source_code" to source)
        if (!filename.isNullOrBlank()) body["filename"] = filename
        if (!console.isNullOrBlank()) body["console_output"] = console
        if (run != null && run.language != "other") {
            body["language"] = run.language
            if (run.compileOk != null) body["compile_ok"] = run.compileOk
            if (run.compileOutput.isNotBlank()) body["compile_output"] = run.compileOutput
            if (run.cases.isNotEmpty()) {
                body["run_report"] = run.cases.map {
                    mapOf(
                        "input" to it.input,
                        "expected" to it.expected,
                        "actual" to it.actual,
                        "passed" to it.passed,
                    )
                }
            }
        }
        val resp = sendJson("POST", "/api/submissions", body = body, token = token)
        requireOk(resp, "Could not send your submission")
        return gson.fromJson(resp.body(), SubmitResponse::class.java)
    }

    // --- exam / proctor ---------------------------------------------------

    /**
     * Fire-and-forget report that the student left (or returned to) the IDE.
     * Deliberately swallows every error: exam telemetry must never break the
     * student's session or surface a dialog. Call off the EDT.
     */
    fun reportProctorEvent(
        sessionId: String,
        kind: String,
        token: String,
        detail: String? = null,
        awayMs: Long? = null,
    ) {
        try {
            val body = mutableMapOf<String, Any>("session_id" to sessionId, "kind" to kind)
            if (!detail.isNullOrBlank()) body["detail"] = detail
            if (awayMs != null) body["away_ms"] = awayMs
            sendJson("POST", "/api/proctor/event", body = body, token = token)
        } catch (e: Exception) {
            thisLogger().debug("proctor event report failed", e)
        }
    }

    /** Cheap keep-alive so a quiet exam student stays on the live grid. */
    fun proctorHeartbeat(sessionId: String, token: String) {
        try {
            sendJson("POST", "/api/proctor/heartbeat", body = mapOf("session_id" to sessionId), token = token)
        } catch (e: Exception) {
            thisLogger().debug("proctor heartbeat failed", e)
        }
    }

    // --- helpers ----------------------------------------------------------

    private fun sendJson(
        method: String,
        path: String,
        body: Any?,
        token: String?,
    ): HttpResponse<String> {
        val builder = HttpRequest.newBuilder(URI.create(baseUrl + path))
            .header("Content-Type", "application/json")
            .header(NGROK_HEADER, "true")
            .timeout(Duration.ofSeconds(30))
        if (token != null) builder.header("Authorization", "Bearer $token")

        val publisher = if (body == null) {
            HttpRequest.BodyPublishers.noBody()
        } else {
            HttpRequest.BodyPublishers.ofString(gson.toJson(body), StandardCharsets.UTF_8)
        }
        when (method) {
            "GET" -> builder.GET()
            "POST" -> builder.POST(publisher)
            else -> builder.method(method, publisher)
        }
        return http.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8))
    }

    private fun requireOk(resp: HttpResponse<String>, context: String) {
        if (resp.statusCode() !in 200..299) {
            throw VeriExamApiException(friendlyError(resp.statusCode(), resp.body(), context))
        }
    }

    private fun friendlyError(status: Int, body: String?, context: String = "Request failed"): String {
        val detail = try {
            val obj = gson.fromJson(body, Map::class.java)
            (obj?.get("detail") ?: obj?.get("error"))?.toString()
        } catch (e: Exception) {
            null
        } ?: body?.take(200)
        return "$context (HTTP $status)${if (!detail.isNullOrBlank()) ": $detail" else ""}"
    }

    private fun encode(s: String): String =
        java.net.URLEncoder.encode(s, StandardCharsets.UTF_8).replace("+", "%20")
}
