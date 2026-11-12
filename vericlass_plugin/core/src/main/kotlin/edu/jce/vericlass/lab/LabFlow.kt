package edu.jce.vericlass.lab

import com.intellij.openapi.diagnostic.Logger
import edu.jce.vericlass.api.FinishResponse
import edu.jce.vericlass.api.OpenStep
import edu.jce.vericlass.api.Probe
import edu.jce.vericlass.api.ProbeClosedException
import edu.jce.vericlass.api.StepStateResponse
import edu.jce.vericlass.api.TranscriptEntry
import edu.jce.vericlass.api.TranscriptResponse
import edu.jce.vericlass.terminal.TerminalHistory
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean

/** A button under a message. */
class LabButton(val label: String, val onClick: () -> Unit)

/** A message on screen whose buttons can be taken away (a finished step's "Done"). */
fun interface Shown {
    fun removeButtons()
}

/**
 * Where the flow shows things (the chat panel). Called on the flow's thread;
 * implementations switch to the EDT themselves.
 */
interface LabView {
    /**
     * A message from [author] (student, tutor, system) of a transcript [kind]
     * (brief, step, note, result, quiz, returned, output, text, …), with [buttons] under it.
     */
    fun show(author: String, kind: String, markdown: String, buttons: List<LabButton> = emptyList()): Shown

    /**
     * The "Done" box of a step that checks its output: [prefill] for the student
     * to check and send to [onSend]. [onClose]: the box went away without sending
     * (the student cancelled it or wrote something else instead).
     */
    fun outputBox(title: String, prefill: String, onSend: (String) -> Unit, onClose: () -> Unit = {})

    /**
     * Take away what the chat waits for above the message box because the
     * teacher's change made it void: the "Done" box and "is this the step's
     * answer?" ([Interrupt.STEP]), "your answer, or a question?" ([Interrupt.PROBE]).
     */
    fun interrupt(what: Set<Interrupt>)

    /** The brief, or the replayed conversation, is on screen. */
    fun introDone(replayed: Boolean)
}

/** What a teacher's change can stop the chat from waiting for ([LabView.interrupt]). */
enum class Interrupt {
    /** The open step's "Done" box, and "a question, or the step's answer?". */
    STEP,

    /** "Your answer to the question, or a question of yours?". */
    PROBE,
}

/** What to do with a message the student sends ([LabFlow.route]). */
sealed class Route {
    /** An ordinary message: to the tutor, or to the teacher in review mode. */
    object Ask : Route()

    /** "Done" typed instead of clicked: the open step's "Done". */
    data class Finish(val step: Int) : Route()

    /** The answer to the question the chat asked. */
    data class Answer(val probe: Probe) : Route()

    /** Maybe the answer: the student says whether it is, or a question of their own. */
    data class AnswerOrQuestion(val probe: Probe) : Route()

    /** The open step's output: it finishes the step. */
    data class Output(val step: Int, val label: String, val needsOutput: Boolean) : Route()

    /** Maybe the step's answer: the student says whether it is, or a question. */
    data class OutputOrQuestion(val step: Int, val label: String, val needsOutput: Boolean) : Route()
}

/**
 * The chat's side of a lab, the same rules as the web chat (student_app/app.py):
 *
 * - **Questions the chat asks** (a teacher's question, a quiz question after a
 *   step) are shown once and stay open without locking the chat. A message is
 *   their answer or a question of the student's own; the server decides
 *   (POST /api/probes/classify), and when it isn't sure the student says.
 * - **Class-paced labs** (`pacing: class`): one step at a time from
 *   /api/steps/state, with a "Done" button. A step that checks its output opens
 *   a box filled with what the VeriClass terminal ran since the step appeared.
 *   An output that doesn't match waits for the teacher, who lets the student
 *   on or sends it back; later steps appear when the teacher opens them.
 * - **The transcript** (backend/transcript.py): everything shown is recorded,
 *   a new login replays it and carries on from the same place, and notes the
 *   chat didn't write itself (the teacher's late answer, a move to another step,
 *   a withdrawn question, an output sent back, a note to the whole class,
 *   another window's messages) appear while it is open.
 * - **The teacher interrupts**: moving the student (back, forward, the same
 *   step over) or withdrawing a question takes away what the chat waits for
 *   (the "Done" box, "your answer, or a question?"), and so does a question
 *   added while the "Done" box is open; a note says why.
 * - **Quiz answers graded too low** wait for the teacher (exercise.yaml
 *   quiz_review), who lets the student continue or asks the question again.
 *
 * Every server call runs on [executor], which must run one task at a time:
 * that keeps the flow's state consistent, as the web chat's lock does. Only
 * [route] runs on [io], so a message isn't held up while an answer is graded.
 */
class LabFlow(
    private val backend: LabBackend,
    private val view: LabView,
    private val texts: LabTexts,
    private val paced: Boolean,
    private val terminal: TerminalHistory?,
    private val executor: Executor,
    private val io: Executor = executor,
) {
    /** The exercise keeps a transcript (exercise.yaml chat_history); read on any thread. */
    @Volatile var history = false
        private set

    // Below: only on the executor's thread.
    private var seen = 0
    private var shownStep: Int? = null
    private var waitingFor: Int? = null
    private var inReview: Int? = null
    private var lastCurrent: Int? = null
    private var finishedNote = false
    private var resetShown = false
    private var resumeButton = false
    /** The step whose "Done" box is open, waiting for its output. */
    private var awaitingOutput: Int? = null
    /** A quiz answer of the student's waits for the teacher. */
    private var quizHeld = false
    @Volatile private var probeShown: Int? = null
    // Written by [route] too.
    private val labels = java.util.concurrent.ConcurrentHashMap<Int, String>()
    /** The terminal's mark when a step appeared, and when its output was last sent. */
    private val stepMarks = HashMap<Int, Long>()
    private val sentMarks = HashMap<Int, Long>()
    private val doneButtons = HashMap<Int, MutableList<Shown>>()

    private val pollQueued = AtomicBoolean(false)
    @Volatile private var disposed = false

    // --- entry points (any thread) ---------------------------------------------------

    /**
     * After login: replay the conversation (or show [brief] the first time), the
     * questions still with the teacher, and where the student is in the lab.
     * [reshowBrief]: after a replay, show the brief again (a step-by-step lab's
     * brief ends with the step the student is on now).
     */
    fun start(brief: String, reshowBrief: Boolean = false) = later {
        val replayed = replay(backend.transcript(after = 0, othersOnly = false))
        if (replayed.isEmpty()) say(brief, kind = "brief")
        else if (reshowBrief) view.show("tutor", "brief", brief)
        view.introDone(replayed.isNotEmpty())
        if (replayed.isNotEmpty()) stillWithTeacher()
        if (paced) {
            val st = state()
            if (st != null && replayed.isNotEmpty()) resumeMarks(replayed, st)
            lastCurrent = st?.current
            val step = st?.step
            if (resumeButton && st?.open == true && step != null) {
                resumeButton = false
                finishButtonAgain(step)
            }
            showState()
        }
    }

    /** Every few seconds: notes from elsewhere, a new question, a step the teacher opened. */
    fun poll() {
        if (pollQueued.compareAndSet(false, true)) later {
            pollQueued.set(false)
            syncOthers()
            if (inReview != null) showState() // "the teacher approved" comes before that step's quiz
            askPendingQuestion()
            if (paced) showState()
        }
    }

    /** What to do with [text], which the student is sending; [then] gets it on the flow's thread. */
    fun route(text: String, then: (Route) -> Unit) = io.execute {
        if (disposed) return@execute
        val route = try {
            routeNow(text.trim())
        } catch (e: Exception) {
            LOG.warn("routing a message", e)
            Route.Ask
        }
        then(route)
    }

    /** The student clicked "Done" for step [n] (or typed it). */
    fun finish(n: Int) = later { finishNow(n) }

    /** [text] is the answer to [probe]. */
    fun answer(probe: Probe, text: String) = later {
        try {
            val r = backend.answerProbe(probe.id, text)
            if (r.review) quizHeld = true
            say(texts.answerSaved(r.auto_grade, r.why, r.review), kind = "result")
        } catch (e: ProbeClosedException) {
            say(texts.questionClosed(), record = false)
        } catch (e: Exception) {
            LOG.warn("answering a question failed", e)
            say(texts.answerNotSent(), record = false)
        }
        askPendingQuestion()
        if (paced) showState()
    }

    /**
     * [text] is step [step]'s answer: finish the step with it. [detected]: the
     * server recognized the output (not the student's choice). When the step
     * isn't open any more, [orElse] (the chat asks the tutor instead).
     */
    fun output(step: Int, label: String, text: String, needsOutput: Boolean, detected: Boolean, orElse: () -> Unit) = later {
        val st = state()
        if (st == null || !st.open || st.step?.n != step) {
            orElse()
            return@later
        }
        if (detected) say(texts.detected(label), kind = "result", step = step)
        sentMarks[step] = terminal?.mark ?: 0
        afterFinish(backend.finishStep(step, if (needsOutput) text else ""), step)
    }

    /** After the student's own question was answered: the chat's question is still open. */
    fun remindQuestion() = later {
        val open = backend.pendingProbes().firstOrNull() ?: return@later
        if (open.id == probeShown) say(texts.remind(open.body))
    }

    /** Record what the student sent (the chat already shows it). */
    fun recordStudent(text: String, kind: String = "text", step: Int? = null) = later { record("student", kind, step, text) }

    /** Record a reply the chat streamed from the tutor (or the teacher). */
    fun recordTutor(text: String) = later { record("tutor", "text", null, text) }

    fun dispose() {
        disposed = true
    }

    // --- routing a message ----------------------------------------------------------------

    private fun routeNow(text: String): Route {
        if (paced && DONE_TEXT.matches(text)) {
            val st = state()
            val step = st?.step
            if (st != null && st.open && step != null) return Route.Finish(step.n)
        }
        if (probeShown != null) {
            val d = backend.classify(text)
            when (d?.kind) {
                "answer" -> d.probe?.let { return Route.Answer(it) }
                "maybe" -> d.probe?.let { return Route.AnswerOrQuestion(it) }
                // A server without classify (or out of reach): let the student say.
                null -> backend.pendingProbes().firstOrNull()?.let { return Route.AnswerOrQuestion(it) }
            }
        }
        if (paced) {
            val d = backend.detectOutput(text)
            if (d != null && d.step > 0) {
                labels[d.step] = d.label
                when (d.kind) {
                    "output" -> return Route.Output(d.step, d.label, d.needs_output)
                    "maybe" -> return Route.OutputOrQuestion(d.step, d.label, d.needs_output)
                }
            }
        }
        return Route.Ask
    }

    // --- coming back after a login ----------------------------------------------------------

    /** Show the session's conversation so far; returns its entries (empty: a new session). */
    private fun replay(t: TranscriptResponse?): List<TranscriptEntry> {
        history = t?.enabled == true
        if (t == null || !t.enabled) return emptyList()
        seen = t.last_id
        if (t.entries.isEmpty()) return emptyList()
        if (t.truncated) view.show("system", "note", texts.olderHidden())
        for (e in t.entries) view.show(e.author, e.kind, e.content)
        view.show("system", "note", texts.resumed())
        return t.entries
    }

    private fun stillWithTeacher() {
        val open = backend.openReviews()
        if (open.isEmpty()) return
        val lines = open.joinToString("\n") { "- «" + it.question.split(Regex("\\s+")).joinToString(" ").take(120) + "»" }
        say(texts.stillWithTeacher(lines), record = false)
    }

    /**
     * What the replayed conversation already shows since the last reset (the
     * current step, the note that the student waits for the teacher, the end of
     * the lab), so a new login doesn't repeat it.
     */
    private fun resumeMarks(entries: List<TranscriptEntry>, st: StepStateResponse) {
        val since = entries.subList(entries.indexOfLast { it.kind == "reset" } + 1, entries.size)
        val cur = st.current
        if (st.open && since.any { it.kind == "step" && it.step == cur }) {
            shownStep = cur
            resumeButton = true
        }
        if (st.waiting_teacher && since.any { it.kind == "note" && it.step == cur }) waitingFor = cur
        if (st.finished && since.any { it.kind == "note" && it.step == st.total + 1 }) finishedNote = true
        if (st.waiting_review) inReview = cur
        if (st.quiz_review > 0) quizHeld = true
    }

    /** After a new login the step's text is in the replayed conversation; only its button comes back. */
    private fun finishButtonAgain(step: OpenStep) {
        // The step appeared before this login: its output is anything this login's terminal ran.
        stepMarks.putIfAbsent(step.n, 0)
        stepButtons(step.n, say(texts.youAreAt(step.label, step.needs_output), kind = "note", record = false,
            buttons = listOf(doneButton(step))))
    }

    // --- notes the chat didn't write itself -------------------------------------------------

    private fun syncOthers() {
        if (!history) return
        val t = backend.transcript(after = seen, othersOnly = true) ?: return
        for (e in t.entries) {
            seen = e.id
            val step = e.step
            if (e.author != "student" && e.kind == "returned" && step != null) {
                // The teacher sent the step's output back: send it again from here.
                inReview = null
                stepButtons(step, view.show(e.author, e.kind, e.content, listOf(sendAgainButton(step))))
            } else {
                if (e.author != "student") interruptedBy(e.kind)
                view.show(e.author, e.kind, e.content)
            }
            if (e.kind == "reset") {
                forgetShown()
                resetShown = true
            }
        }
    }

    /**
     * The server's note of a [kind] the teacher's change writes: stop what the
     * chat waits for that the change made void (the note itself says why).
     */
    private fun interruptedBy(kind: String) {
        when (kind) {
            "reset" -> {
                // Moved to another step (or the same one over): every open box is void,
                // and so is every "Done" button above, the step is shown again.
                awaitingOutput = null
                view.interrupt(setOf(Interrupt.STEP, Interrupt.PROBE))
                doneButtons.values.forEach { list -> list.forEach { it.removeButtons() } }
                doneButtons.clear()
            }
            "cancelled" -> {
                // A question was withdrawn: "your answer, or a question?" about it is void,
                // and the next open question (if any) is shown.
                view.interrupt(setOf(Interrupt.PROBE))
                probeShown = null
            }
        }
    }

    // --- the steps of a class-paced lab --------------------------------------------------------

    private fun state(): StepStateResponse? {
        val st = backend.stepState()
        st?.step?.let { labels[it.n] = it.label }
        return st
    }

    /** Show what changed since the last look: a step that opened, a wait for the teacher, the end. */
    private fun showState() {
        val st = state() ?: return
        val last = lastCurrent
        lastCurrent = st.current
        val awaiting = awaitingOutput
        if (awaiting != null && !(st.open && st.step?.n == awaiting)) {
            // The "Done" box waits for a step that isn't open any more (a question was
            // added, the teacher moved the student): close it, and say why.
            awaitingOutput = null
            view.interrupt(setOf(Interrupt.STEP))
            say(texts.boxStopped(labels[awaiting] ?: "$awaiting", st.quiz_pending > 0), kind = "note", step = awaiting)
        }
        if (last != null && st.current < last) {
            // The teacher sent the student back. The server's note normally came
            // through the transcript already; without a transcript, say it here.
            if (!resetShown && !history) say(texts.movedBack(st.current_label ?: "${st.current}"), kind = "note")
            forgetShown()
        }
        resetShown = false
        // Steps behind the student (the teacher let them past one, another window finished it): no buttons.
        doneButtons.keys.filter { it < st.current }.forEach { n -> doneButtons.remove(n)?.forEach { it.removeButtons() } }
        val review = inReview
        if (review != null && st.current == review && st.open && !st.waiting_review && !history) {
            // Sent back by the teacher; without a transcript its note can't arrive, so say it here.
            inReview = null
            stepButtons(review, say(texts.returned(st.current_label ?: "$review"), kind = "returned", step = review,
                buttons = listOf(sendAgainButton(review))))
        }
        if (review != null && st.current > review) {
            // The teacher let them past the step whose output didn't match.
            inReview = null
            say(texts.approved(labels[review] ?: "$review"), kind = "result", step = review)
        }
        if (quizHeld && st.quiz_review == 0) {
            // The teacher decided about the quiz answer that waited. The server's note
            // says what (the transcript); without a transcript, say it here.
            quizHeld = false
            if (!history) say(texts.answerRead(), kind = "note")
        }
        val step = st.step
        if (st.open && step != null) {
            if (shownStep != step.n) {
                val unlocked = waitingFor == step.n
                shownStep = step.n
                waitingFor = null
                showStep(step, unlocked)
            }
        } else if (st.waiting_teacher) {
            if (waitingFor != st.current) {
                waitingFor = st.current
                val text = if (st.current == 1) texts.firstNotOpen()
                else texts.waitingTeacher(st.current_label ?: "${st.current}")
                say(text, kind = "note", step = st.current)
            }
        } else if (st.finished && !finishedNote) {
            finishedNote = true
            say(texts.allDone(), kind = "note", step = st.total + 1)
        }
    }

    private fun showStep(step: OpenStep, unlocked: Boolean) {
        stepMarks.putIfAbsent(step.n, terminal?.mark ?: 0)
        val head = if (unlocked) texts.opened(step.label) else ""
        stepButtons(step.n, say("$head${step.markdown}\n\n${texts.howToFinish(step.needs_output)}", kind = "step",
            step = step.n, buttons = listOf(doneButton(step))))
    }

    /** Buttons that finish step [n] ("Done", "send again"): they go once it is done. */
    private fun stepButtons(n: Int, shown: Shown) {
        doneButtons.getOrPut(n) { mutableListOf() }.add(shown)
    }

    private fun doneButton(step: OpenStep) = LabButton(texts.doneButton(step.label)) { finish(step.n) }

    private fun sendAgainButton(n: Int) = LabButton(texts.sendAgain()) { finish(n) }

    /** After a reset: show the step the student is on again, as if new. */
    private fun forgetShown() {
        shownStep = null
        waitingFor = null
        inReview = null
        finishedNote = false
        awaitingOutput = null
        quizHeld = false
    }

    private fun finishNow(n: Int) {
        val st = state()
        if (st == null) {
            say(texts.noConnection(), record = false)
            return
        }
        val step = st.step
        if (!st.open || step == null || step.n != n) return notThisStep(st, n)
        if (!step.needs_output) return afterFinish(backend.finishStep(n, ""), n)
        val prefill = prefill(n)
        awaitingOutput = n
        view.outputBox(texts.outputBoxTitle(step.label, prefill.isNotEmpty()), prefill,
            onSend = { output ->
                later {
                    if (awaitingOutput == n) awaitingOutput = null
                    record("student", "output", n, output)
                    sentMarks[n] = terminal?.mark ?: 0
                    // The server decides: a step closed meanwhile is answered with where the student is.
                    afterFinish(backend.finishStep(n, output), n)
                }
            },
            onClose = { later { if (awaitingOutput == n) awaitingOutput = null } })
    }

    /**
     * What the terminal ran for step [n]: since its output was last sent (the
     * student ran it again), else since the step appeared.
     */
    private fun prefill(n: Int): String {
        val t = terminal ?: return ""
        sentMarks[n]?.let { mark -> t.since(mark).takeIf { it.isNotEmpty() }?.let { return it } }
        return t.since(stepMarks[n] ?: 0)
    }

    /** How finishing step [n] went; on success, its quiz question and the next step. */
    private fun afterFinish(r: FinishResponse?, n: Int) {
        val label = labels[n] ?: "$n"
        if (r == null) {
            say(texts.saveFailed(), record = false)
            return
        }
        if (r.status == "missing") {
            // The checks' hints would give the expected output away; the teacher sees them.
            inReview = n
            stepButtons(n, say(texts.missing(label), kind = "result", step = n, buttons = listOf(sendAgainButton(n))))
            return
        }
        if (r.status != "done") {
            r.state?.let { notThisStep(it, n) }
            showState() // e.g. moved meanwhile: show the step they are on
            return
        }
        doneButtons.remove(n)?.forEach { it.removeButtons() }
        inReview = null
        say(texts.stepDone(label, r.ok == true, (r.quiz ?: 0) > 0), kind = "result", step = n)
        askPendingQuestion()
        showState()
    }

    private fun notThisStep(st: StepStateResponse, n: Int) {
        val current = st.current_label ?: "${st.current}"
        say(when {
            st.finished -> texts.alreadyFinishedAll()
            st.quiz_pending > 0 -> texts.answerQuizFirst()
            st.quiz_review > 0 -> texts.answerWithTeacher()
            st.waiting_teacher -> texts.notOpenYet(current)
            else -> texts.alreadyDone(labels[n] ?: "$n", current)
        })
    }

    // --- questions the chat asks ---------------------------------------------------------------

    /** Show the oldest question waiting for the student's answer, once. */
    private fun askPendingQuestion() {
        val q = backend.pendingProbes().firstOrNull() ?: return
        if (probeShown == q.id) return
        probeShown = q.id
        say(texts.question(q.body, q.quiz_step?.takeIf { q.source == "quiz" }), kind = "quiz")
    }

    // --- helpers ------------------------------------------------------------------------------

    /** Show (and record) a message of the chat's own. */
    private fun say(
        text: String,
        kind: String = "text",
        step: Int? = null,
        buttons: List<LabButton> = emptyList(),
        record: Boolean = true,
    ): Shown {
        val shown = view.show("tutor", kind, text, buttons)
        if (record) record("tutor", kind, step, text)
        return shown
    }

    private fun record(author: String, kind: String, step: Int?, content: String) {
        if (history && content.isNotBlank()) {
            backend.record(listOf(mapOf("author" to author, "kind" to kind, "step" to step, "content" to content)))
        }
    }

    private fun later(task: () -> Unit) = executor.execute {
        if (disposed) return@execute
        try {
            task()
        } catch (e: Exception) {
            LOG.warn("lab flow", e)
        }
    }

    companion object {
        private val LOG = Logger.getInstance(LabFlow::class.java)

        /** A short message that means "I finished this step": the typed form of the "Done" button. */
        val DONE_TEXT = Regex("""^\s*(סיימתי|סיימנו|גמרתי|גמרנו|הבא|השלב הבא|done|next)\s*[.!]*\s*$""", RegexOption.IGNORE_CASE)
    }
}
