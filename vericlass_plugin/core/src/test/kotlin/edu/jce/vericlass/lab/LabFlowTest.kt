package edu.jce.vericlass.lab

import edu.jce.vericlass.api.ClassifyResponse
import edu.jce.vericlass.api.DetectResponse
import edu.jce.vericlass.api.FinishResponse
import edu.jce.vericlass.api.OpenReview
import edu.jce.vericlass.api.OpenStep
import edu.jce.vericlass.api.Probe
import edu.jce.vericlass.api.ProbeAnswerResponse
import edu.jce.vericlass.api.ProbeClosedException
import edu.jce.vericlass.api.StepStateResponse
import edu.jce.vericlass.api.TranscriptEntry
import edu.jce.vericlass.api.TranscriptResponse
import edu.jce.vericlass.terminal.TerminalHistory
import edu.jce.vericlass.terminal.TerminalRecord
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The plugin's lab flow against a fake server, one task at a time on the test's
 * thread. The cases mirror the web chat's (student_app) behavior in class.
 */
class LabFlowTest {

    /** A class-paced lab of [steps] steps, the first [released] open; step 1 checks its output. */
    private class FakeServer(val steps: Int = 3, var released: Int = 2) : LabBackend {
        var current = 1
        var quizPending = 0
        var waitingReview = false
        var transcriptEnabled = true
        val transcriptEntries = mutableListOf<TranscriptEntry>()
        val recorded = mutableListOf<Map<String, Any?>>()
        val probes = mutableListOf<Probe>()
        var classifyAnswer: ClassifyResponse? = ClassifyResponse("none")
        var detect: DetectResponse? = DetectResponse("question")
        var outputMatches = true
        val finished = mutableListOf<Pair<Int, String>>()
        val answered = mutableListOf<Pair<Int, String>>()
        var answerFails: Exception? = null
        var openReviews = listOf<OpenReview>()

        fun label(n: Int) = "A$n"

        override fun stepState(): StepStateResponse {
            val open = current <= steps && current <= released && quizPending == 0
            return StepStateResponse(
                total = steps, current = current, current_label = if (current <= steps) label(current) else null,
                released = released, finished = current > steps, quiz_pending = quizPending,
                waiting_teacher = current <= steps && current > released && quizPending == 0,
                open = open, waiting_review = waitingReview,
                step = if (open) OpenStep(current, label(current), "Step $current", "### Step ${label(current)}",
                    needs_output = current == 1) else null,
            )
        }

        override fun finishStep(step: Int, output: String): FinishResponse {
            finished += step to output
            if (step != current) return FinishResponse("wrong_step", state = stepState())
            if (step == 1 && !outputMatches) {
                waitingReview = true
                return FinishResponse("missing", state = stepState())
            }
            current++
            return FinishResponse("done", ok = step == 1, quiz = 0, state = stepState())
        }

        override fun detectOutput(text: String) = detect
        override fun pendingProbes(): List<Probe> = probes.toList()
        override fun classify(text: String) = classifyAnswer
        override fun answerProbe(probeId: Int, answer: String): ProbeAnswerResponse {
            answerFails?.let { throw it }
            answered += probeId to answer
            probes.removeIf { it.id == probeId }
            return ProbeAnswerResponse(2, "good")
        }

        override fun transcript(after: Int, othersOnly: Boolean): TranscriptResponse? {
            if (!transcriptEnabled) return TranscriptResponse(enabled = false)
            val entries = transcriptEntries.filter { it.id > after }
            return TranscriptResponse(true, entries, false, transcriptEntries.maxOfOrNull { it.id } ?: 0)
        }

        override fun record(entries: List<Map<String, Any?>>) {
            recorded += entries
        }

        override fun openReviews() = openReviews
    }

    private class Message(val author: String, val kind: String, val text: String, val buttons: List<LabButton>) {
        var removed = false
    }

    private class FakeView : LabView {
        val messages = mutableListOf<Message>()
        var box: Triple<String, String, (String) -> Unit>? = null
        var intro: Boolean? = null

        override fun show(author: String, kind: String, markdown: String, buttons: List<LabButton>): Shown {
            val m = Message(author, kind, markdown, buttons)
            messages += m
            return Shown { m.removed = true }
        }

        override fun outputBox(title: String, prefill: String, onSend: (String) -> Unit) {
            box = Triple(title, prefill, onSend)
        }

        override fun introDone(replayed: Boolean) {
            intro = replayed
        }

        fun texts() = messages.map { it.text }
        fun last() = messages.last()
        fun click(label: String) = messages.filter { !it.removed }.flatMap { it.buttons }.last { it.label == label }.onClick()
    }

    private val en = LabTexts(false)

    private fun flow(server: FakeServer, view: FakeView, terminal: TerminalHistory? = null) =
        LabFlow(server, view, en, paced = true, terminal = terminal, executor = { it.run() })

    private fun routeOf(flow: LabFlow, text: String): Route {
        var out: Route? = null
        flow.route(text) { out = it }
        return out!!
    }

    private fun ran(line: String, output: String) =
        TerminalRecord(line, "lab", true, null, listOf(line), 0, 10, output, output = output)

    @Test
    fun `a new session shows the brief, then the open step once`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("# The brief")
        f.poll()
        f.poll()
        assertEquals(false, view.intro)
        assertEquals(listOf("brief", "step"), view.messages.map { it.kind })
        assertEquals(listOf(en.doneButton("A1")), view.last().buttons.map { it.label })
        // Both are in the transcript, for the next login.
        assertEquals(listOf("brief", "step"), server.recorded.map { it["kind"] })
    }

    @Test
    fun `Done fills the box with what the terminal ran since the step appeared`() {
        val server = FakeServer()
        val view = FakeView()
        val terminal = TerminalHistory()
        terminal.add(ran("ls", "before the step"))
        val f = flow(server, view, terminal)
        f.start("brief")
        terminal.add(ran("docker pull alpine", "ALL READY"))
        view.click(en.doneButton("A1"))

        val (title, prefill, send) = view.box!!
        assertEquals(en.outputBoxTitle("A1", prefilled = true), title)
        assertEquals("$ docker pull alpine\nALL READY", prefill)
        send(prefill)
        assertEquals(listOf(1 to prefill), server.finished)
        // The step is done: its button goes, the next step appears.
        assertTrue(view.messages.first { it.kind == "step" }.removed)
        assertTrue(view.texts().contains(en.stepDone("A1", outputOk = true, quiz = false)))
        assertEquals("### Step A2\n\n" + en.howToFinish(false), view.last().text)
        assertTrue(server.recorded.any { it["author"] == "student" && it["kind"] == "output" && it["step"] == 1 })
    }

    @Test
    fun `an output that doesn't match waits for the teacher, who lets the student on`() {
        val server = FakeServer().apply { outputMatches = false }
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        view.click(en.doneButton("A1"))
        view.box!!.third("something else")
        assertEquals(en.missing("A1"), view.last().text)
        assertEquals(listOf(en.sendAgain()), view.last().buttons.map { it.label })

        // The teacher lets them through.
        server.waitingReview = false
        server.current = 2
        f.poll()
        val texts = view.texts()
        assertTrue(texts.contains(en.approved("A1")))
        assertTrue(texts.last().startsWith("### Step A2"))
        assertTrue("the step's buttons go", view.messages.filter { it.buttons.isNotEmpty() && it.text != texts.last() }.all { it.removed })
    }

    @Test
    fun `finishing every open step waits for the teacher, then shows the step they open`() {
        val server = FakeServer(released = 1)
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        view.click(en.doneButton("A1"))
        view.box!!.third("ALL READY")
        assertEquals(en.waitingTeacher("A2"), view.last().text)
        f.poll()
        assertEquals("the note isn't repeated", 1, view.texts().count { it == en.waitingTeacher("A2") })
        server.released = 2
        f.poll()
        assertTrue(view.last().text.startsWith(en.opened("A2")))
    }

    @Test
    fun `a teacher's question is shown once and stays open while the student asks`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        server.probes += Probe(7, "What did you pull?")
        f.poll()
        f.poll()
        assertEquals(1, view.texts().count { it == en.question("What did you pull?", null) })

        // Not sure (it looks like a question): the student says.
        server.classifyAnswer = ClassifyResponse("maybe", server.probes[0])
        assertEquals(Route.AnswerOrQuestion(server.probes[0]), routeOf(f, "Which image?"))
        // After their own question was answered, a reminder; none once they answered.
        f.remindQuestion()
        assertEquals(en.remind("What did you pull?"), view.last().text)

        server.classifyAnswer = ClassifyResponse("answer", server.probes[0])
        val route = routeOf(f, "alpine")
        assertEquals(Route.Answer(server.probes[0]), route)
        f.answer((route as Route.Answer).probe, "alpine")
        assertEquals(listOf(7 to "alpine"), server.answered)
        assertEquals(en.answerSaved(2, "good"), view.texts().last { it.startsWith("✅") })
        val shown = view.messages.size
        f.remindQuestion()
        assertEquals(shown, view.messages.size)
    }

    @Test
    fun `Done and the step's output still go to the step while a question is open`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        server.probes += Probe(7, "What did you pull?")
        f.poll()
        assertEquals(Route.Finish(1), routeOf(f, "סיימתי"))
        assertEquals(Route.Finish(1), routeOf(f, " Done! "))
        server.classifyAnswer = ClassifyResponse("step", server.probes[0])
        server.detect = DetectResponse("output", 1, "A1", true)
        assertEquals(Route.Output(1, "A1", true), routeOf(f, "ALL READY"))
        server.detect = DetectResponse("maybe", 1, "A1", true)
        assertEquals(Route.OutputOrQuestion(1, "A1", true), routeOf(f, "ALL"))
        // A server without /api/probes/classify: the student says what it is.
        server.classifyAnswer = null
        server.detect = DetectResponse("question")
        assertEquals(Route.AnswerOrQuestion(server.probes[0]), routeOf(f, "alpine"))
    }

    @Test
    fun `an ordinary message goes to the tutor`() {
        val server = FakeServer()
        val f = flow(server, FakeView())
        f.start("brief")
        assertEquals(Route.Ask, routeOf(f, "How do I list images?"))
        // "Done" with no open step is just a message.
        server.released = 0
        assertEquals(Route.Ask, routeOf(f, "done"))
    }

    @Test
    fun `an output typed into the box finishes the step, or goes to the tutor if the step closed`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        var askedInstead = false
        f.output(1, "A1", "ALL READY", needsOutput = true, detected = true) { askedInstead = true }
        assertFalse(askedInstead)
        assertEquals(listOf(1 to "ALL READY"), server.finished)
        assertTrue(view.texts().contains(en.detected("A1")))
        f.output(1, "A1", "again", needsOutput = true, detected = false) { askedInstead = true }
        assertTrue(askedInstead)
    }

    @Test
    fun `a withdrawn question says so`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        server.answerFails = ProbeClosedException("cancelled")
        f.answer(Probe(3, "q"), "late")
        assertEquals(en.questionClosed(), view.last().text)
        assertFalse("not recorded", server.recorded.any { it["content"] == en.questionClosed() })
    }

    @Test
    fun `a new login replays the conversation and gives the step's button back`() {
        val server = FakeServer().apply {
            transcriptEntries += TranscriptEntry(1, "tutor", "brief", null, "brief")
            transcriptEntries += TranscriptEntry(2, "tutor", "step", 1, "### Step A1")
            transcriptEntries += TranscriptEntry(3, "student", "text", null, "what is a container?")
            openReviews = listOf(OpenReview(5, "what is a container?"))
        }
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        f.poll()
        assertEquals(true, view.intro)
        assertEquals(listOf("brief", "step", "text"), view.messages.take(3).map { it.kind })
        assertEquals("student", view.messages[2].author)
        assertTrue(view.texts().contains(en.resumed()))
        assertTrue(view.texts().any { it.startsWith("⏳") && "what is a container?" in it })
        // The step isn't shown again: only its button comes back.
        assertEquals(1, view.messages.count { it.kind == "step" })
        assertEquals(en.youAreAt("A1", true), view.last().text)
        assertEquals(listOf(en.doneButton("A1")), view.last().buttons.map { it.label })
        assertTrue("nothing replayed is recorded again", server.recorded.isEmpty())
    }

    @Test
    fun `the teacher's notes arrive while the chat is open`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        // The output was sent back with a note: send it again from here.
        server.transcriptEntries += TranscriptEntry(10, "system", "returned", 1, "↩️ not yet\n\n> run it again", "server")
        f.poll()
        assertEquals("↩️ not yet\n\n> run it again", view.last().text)
        assertEquals(listOf(en.sendAgain()), view.last().buttons.map { it.label })
        // A late answer from the teacher.
        server.transcriptEntries += TranscriptEntry(11, "tutor", "text", null, "Here is the answer", "server")
        f.poll()
        assertEquals("Here is the answer", view.last().text)
        f.poll()
        assertEquals("each note once", 1, view.texts().count { it == "Here is the answer" })
    }

    @Test
    fun `a reset shows the step again`() {
        val server = FakeServer()
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        view.click(en.doneButton("A1"))
        view.box!!.third("ALL READY")
        assertEquals(2, server.current)
        // The teacher sends the student back to A1; the server's note says so.
        server.current = 1
        server.transcriptEntries += TranscriptEntry(20, "system", "reset", 1, "↩️ back to A1", "server")
        f.poll()
        assertTrue(view.texts().contains("↩️ back to A1"))
        assertFalse("no second note", view.texts().contains(en.movedBack("A1")))
        assertEquals("### Step A1\n\n" + en.howToFinish(true), view.last().text)
    }

    @Test
    fun `without a transcript nothing is recorded and the brief is shown`() {
        val server = FakeServer().apply { transcriptEnabled = false }
        val view = FakeView()
        val f = flow(server, view)
        f.start("brief")
        assertFalse(f.history)
        assertEquals("brief", view.messages.first().text)
        assertTrue(server.recorded.isEmpty())
    }

    @Test
    fun `the lab speaks the brief's language`() {
        assertTrue(LabTexts.forBrief("### מעבדה 2: קונטיינרים").hebrew)
        assertFalse(LabTexts.forBrief("### Lab 2: containers").hebrew)
    }
}
