# Lecturer's guide

How VeriClass works in class, and the settings behind each part. To install
and start, see the [README](../README.md); to write exercises, see
[examples/README.md](../examples/README.md).

- [Why VeriClass](#why-vericlass)
- [Three ways to steer the tutor](#three-ways-to-steer-the-tutor)
- [Courses, students and meetings](#courses-students-and-meetings)
- [Class-paced labs](#class-paced-labs)
- [Sharing with students](#sharing-with-students)
- [Privacy](#privacy)

## Why VeriClass

LLM use in introductory programming courses is no longer optional: students
*are* using ChatGPT / Copilot / Gemini whether we want them to or not. The
question is not whether to allow it but **how to integrate it in a way that
preserves learning**.

A naive integration ("give every student a chat window") has two well-known
failure modes:

1. **The answer-vending machine.** The model produces a complete, polished
   solution on the first prompt. The student copy-pastes, the test passes,
   and the student has learned nothing.
2. **The invisible session.** The instructor has no view of *how* the
   student used the model: were they stuck? Did the model mislead them? Did
   they get the answer in one shot or struggle productively?

This system addresses both, and adds a third capability that conventional
LLM platforms don't offer: **per-student personalization** through variant
exercises, so two students cannot trivially share an answer.

The design rests on four ideas:

- **Instructor in the loop.** Every layer — from passive observation to
  full answer-gating — is available. The instructor chooses how much
  control to exert based on the lab's pedagogical stage.
- **Variant assignment.** Each student is deterministically assigned one
  of N parameterized variants of the exercise. Their test cases differ.
  A peer's chat transcript won't pass their tests.
- **Comprehension probes.** Mid-lab, the instructor can fire a targeted
  question at one or many students. It stays open in the chat until they
  answer. Answers are auto-graded and stored alongside the
  transcript, providing assessment signal that survives the use of any AI.
- **On the lecturer's own computer.** Accounts, courses and every
  conversation stay in a database on the lecturer's machine; the only
  outside service is the LLM provider the lecturer chose (see
  [Privacy](#privacy)).

This is a working research platform for our department's broader question:
*what does responsible LLM-mediated CS instruction look like, in practice?*

## Three ways to steer the tutor

Modes are independent — you can mix them per session, per student, or
globally during a single lab.

### 1. Tutor mode: mentor or coding partner
Set per session. Controlled from each student's card in the dashboard.

- **mentor** — Socratic. The model asks questions back, refuses to
  produce complete code, points at relevant concepts. Default for early
  exercises.
- **coding_partner** — collaborative. The model can write small code
  fragments but still avoids dumping a finished solution. Default for
  later exercises once students have demonstrated comprehension.

The persona is implemented as a system prompt switch in `backend/prompts.py`
and is the lightest-touch intervention: the model answers the student
directly, you just shape its style.

### 2. Questions to students ("Ask them")
At any time, the instructor opens *Ask Them* on a student card and either:
- Writes a question manually, or
- Clicks **Suggest** — the cloud LLM reads the student's recent transcript
  and proposes 2–3 probe questions targeted at apparent gaps.

The probe appears in the student's chat and stays open without locking it:
the student answers when ready and can still ask the tutor or the instructor
meanwhile. Their answer is auto-graded 0–2 and saved. You can later override
the auto-grade.

This is the assessment backbone: probes test whether the student
*understands* what the AI helped them produce.

### 3. Review mode: every answer goes through you
The switch at the top of the review queue on *Live class*, for all exercises. When on:

1. Student asks a question. It is in the instructor's review queue at once;
   the student sees *"Your teacher is reviewing your question…"*. The card
   says **where the student is**: the step (its label and title) and its
   status (working on it; finished it and waiting for the instructor to open
   the next one; their output didn't match; answering the step's quiz; a quiz
   answer of theirs waiting for the instructor's decision;
   waiting for approval; finished all the steps), and shows **the chat just
   before the question**: the last five entries (steps handed out, pasted
   outputs, check results, quiz questions, earlier questions and answers),
   each cut to two lines (click one to see it whole), with a *Full chat*
   button that opens the whole chat. An exercise that keeps no transcript
   shows the model turns instead (`backend/whereabouts.py`).
2. The backend drafts **five answers**, one model call each, all at the same
   time, each in English and Hebrew:
   - **Nudge** — one Socratic line, no answer
   - **Normal** — guidance plus a small pointer, no full solution
   - **Normal + more** — same, with an extra explanation or analogy
   - **Direct** — not Socratic: the plain answer to what was asked, with a
     short example (never the whole step's solution)
   - an extra answer by the **best model** (`CLAUDE_BEST_MODEL`, Opus 5.5;
     direct by default, the level is a setting of the queue, and it can be
     switched off)

   The four are written by the default model (`CLAUDE_MODEL`, Haiku). Each
   answer appears in the queue **the moment its model is done with it**, as a
   full-width row, the first that finished on top (the nudge is usually
   first), with the model's name and how long it took; a line under the rows
   says which are still being written. An answer whose draft failed says so
   with a *try again* button; **Redo with Sonnet 5.5 / Opus 5.5** drafts the
   four levels again with a stronger model (`CLAUDE_STRONG_MODEL`,
   `CLAUDE_BEST_MODEL`). When the question is close to one in the exercise's
   **question bank**, the bank's ready answer is shown first; and there is
   always a row for the instructor's **own answer**.
3. The instructor sends one row (edited or not). It is stored, then streamed
   to the student, so a dropped connection doesn't lose it. Two boxes go with
   every send:
   - **Save to the question bank** (ticked by default; the default is a
     setting of the queue): the question, its step, the level and the final
     text go into the exercise's `faq.yaml` (or its database row when it has
     no package folder), so the next student who asks something similar shows
     the instructor's own answer first. The bank's answer sent again for a
     reworded question goes back into the same entry, which learns the new
     wording as a paraphrase.
   - **Send to the asker + whole class**: for a question the whole class should hear
     (a conceptual one), the answer also goes to every student active on the
     exercise in the last 30 minutes (`BROADCAST_ACTIVE_MINUTES`; the same
     course as the student who asked, when they are in one), as a teacher's
     note in their chat, with the question quoted; it
     is in their chat at once if it is open, or after their next login, and
     the tutor remembers it as part of the conversation. The dashboard asks
     first and says how many students it reaches.
   - **Answered recently**, under the queue, lists the answers sent in the
     last 12 hours. *Send to all students* on one of them sends it to the rest
     of the class afterwards (everyone active on the exercise except the
     student who asked), edited for the class if needed (a name taken out);
     the button says how many it reaches, and the row then says how many got it.
4. The chosen level and model are logged on `messages.answer_level` and
   `messages.model` for later correlation with the student's grade.

API: `GET /api/reviews/pending` (each item carries `answers`, finished in
the order they finished, and `drafting`), `POST /api/reviews/{id}/select`
(`{"chosen": nudge|normal|more|direct|best|bank|own, "lang", "text",
"save_to_bank", "send_to_class", "level"}`), `POST /api/reviews/{id}/regenerate`
(`{"model": strong|best}` for the four levels, or `{}` / `{"slots": [...]}`
for the failed ones), `GET/POST /api/reviews/config` (`best_answer`,
`best_level`, `save_to_bank`, `translate_to`), `POST /api/broadcast`
(`{"exercise_id", "text", "course_id"}`: a free note to the class) and
`GET /api/broadcast/recipients` (`exclude_session`: not counting the asker),
`GET /api/reviews/answered` (`exercise_id`, `hours` default 12) and
`POST /api/reviews/{id}/send-to-class` (`{"text"}`, optional). Tables: `review_answers` (one row per
drafted answer), `pending_reviews.chosen_slot`, `saved_to_bank`,
`sent_to_class`.

**Keeping the queue in step with the students.** Each question shows whether
the student is **waiting now** (their request is open) or **not waiting**: they
closed the chat, their connection dropped, the 10-minute wait ran out, or the
server restarted. An answer to a question nobody waits for is not lost: it is
stored and goes into the student's chat transcript, so the student chat shows it
at once if it is open again, or after their next login (a client that can show
it says so with `X-VeriClass-Transcript: 1`; for any other, such as the IDE
plugin, a timeout still closes the question). **Delete** removes a question
sent by mistake or no longer relevant; with *tell the student* (default, off for
questions that look sent by mistake) a waiting student is told at once, and one
who left finds the note when they are back. **Delete the questions nobody is
waiting for** clears the leftovers in one click. A question the same student
asks again replaces its older copy, and a student who logs in again sees which
of their questions are still with the teacher. API: `POST /api/reviews/{id}/delete`
(`{"notify", "note"}`), `POST /api/reviews/delete-stale`, `GET /api/reviews/open/{session_id}`.

**Questions in other languages.** A question in neither Hebrew nor English (say,
Arabic or Russian) arrives with a translation under it: the model call that
drafts the nudge (the quickest) also names the question's language and
translates it, so it costs no extra call. The queue's *translate to* setting picks the language (Hebrew by
default, English, or off); it applies to questions asked from then on. *Redo
with* keeps the translation. Stored on `pending_reviews.question_lang`,
`question_translation` and `translated_to`; the setting is `review_translate_to`
(`GET/POST /api/reviews/config`, `{"translate_to": "he" | "en" | "off"}`).

Use this in high-stakes labs, during summative assessment, or when a
particular student needs heavily-scaffolded support. The model **never**
returns a full working solution at any level — that constraint is enforced
in the tutor agent (`backend/agents/tutor.py`). The drafts are grounded in the
student's actual conversation (threaded in as memory), so they answer *this*
student rather than repeating boilerplate.

## Courses, students and meetings

Everything here is in the dashboard's **Courses & students** tab.

- **Students** get accounts by importing a list: a CSV file with a name (or
  first and last name) and optionally email, student ID, course and group
  columns, in English or Hebrew. A Moodle participants export and a Hebrew CSV
  saved from Excel work as they are. Preview first, then import; the result is
  a file with every student's **username** and **password** to hand out.
  Importing the same list again creates nobody twice. Instead of a file you
  can **paste rows** (copied from Excel, Moodle or a list of names).
- **A student who joins later**: *Add a student* (at the top of the tab, or in
  a course's student list) takes a name and, optionally, an ID number, email,
  group and course. It shows the new username and password to hand out; a
  student who already has an account (same ID number or email) keeps it and is
  only added to the course. API: `POST /api/students`.
- **Passwords.** Until you set one, a student's password is their username
  (typed in any case). A password you set is stored only as a salted hash. Set
  or reset passwords in the *Passwords* table, or from a terminal:
  `uv run python scripts/set_password.py <username>` (`--reset` goes back to the
  username).
- **Courses.** A course offers some exercises (one of them the default) to some
  students. In the student chat, the menu at the top of the page lists every
  exercise the student's courses offer now (read again on every page load, so
  an exercise you add appears after a reload) and switches between them. Each
  exercise keeps its own conversation and progress, so going back to one
  continues where the student left it. The chat opens by itself the exercise
  the student worked on in the last 3 hours, else today's meeting's, else the
  course's default (`KEEP_LAST_HOURS` in `backend/courses.py`). To sign in as
  someone else: the round button at the top right, then *Sign out*. A student
  who is in no course gets the exercise marked *for students without a course*
  on the Exercises tab.
- **Finding an exercise.** The Exercises tab searches by title or id, sorts by
  date added, date changed or name, and filters by date (today, the last 7 or
  30 days, or dates you choose). The order you pick is kept in your browser and
  used by every list of exercises in the dashboard. A package's dates come from
  its folder (added) and its newest file (changed); a bundled sample has none
  unless you edited it.
- **Meetings.** A course can list its meetings (a date and an exercise): on
  that date its students open the meeting's exercise without choosing, and the
  meeting shows who came.
- **More than one lecturer** can sign in to the same VeriClass: add them with
  `uv run python scripts/add_students.py --teachers "Name"` in a terminal.
  Lecturer accounts work only in a browser on the computer that runs VeriClass
  (`TEACHER_LOCAL_ONLY` in `.env`).

## Class-paced labs

For a step-by-step lab (`pacing: class` in exercise.yaml). The chat hands out
the lab one step at a time; the lecturer keeps the whole class on the same step.
Students can work anywhere they have a terminal: their own computer, a lab
computer, or a GitHub Codespace. The sample [`examples/first-lab`](../examples/first-lab)
is a class-paced lab.

- **Steps open from the start** (`open_steps`, e.g. the setup part) go at each
  student's own pace, until the lecturer sets the course's marker in the
  dashboard (*Class pacing*: "Open step B4", or *Change the last open step* to any step, including
  one of the steps open from the start, e.g. "up to A5" to stop everyone there). A student who
  finished every open step waits in the chat, and the next step appears there by
  itself when it opens.
- **Done = the step's output.** Every step has a *Done* button (typing "סיימתי"
  or "done" works too). For a step with `expect_output` checks the student
  pastes what the terminal printed. An output that passes every check moves the
  student on by itself. One that doesn't waits for the lecturer: the dashboard
  shows it next to the step's `expected_output`, with *Let them continue* and
  *Send back to try again* (with an optional note, which the student's chat
  shows with a *paste again* button); meanwhile the student may paste again. Students never see the expected output
  or the checks. Students often type or paste into the chat instead of clicking
  *Done*, so any message while a step is open is handled first (`POST
  /api/steps/detect`): an output that passes every check finishes the step, and
  any other message makes the chat ask "a question, or your answer for step
  X?" before anything reaches the lecturer. "The answer" is checked like a
  paste after *Done*; "a question" goes to the tutor (or the review queue).
- **Questions after steps** (`quiz` in teacher.yaml) reach students only after
  the lecturer approves them in the dashboard (the wording can be edited there).
  An approved question is asked when a student finishes its step, the next step
  waits for the answer, and the answer is graded against the model answer.
  A question marked `always: true` is approved by the package's author and is
  asked without the dashboard, for example "what does the code you just pasted
  do?" after every step that pastes code. The dashboard can still switch it
  off. Questions are asked in the order they are listed. They are at the
  bottom of the *Live class* page; the badge "questions to approve" at the top
  of *Class pacing* opens them there.
- **Only a 2/2 answer moves on by itself.** An answer graded 0/2 or 1/2
  doesn't open the next step: the student's chat says the answer is with the
  lecturer, and the top of *Class pacing* shows it under *Answers waiting for
  your decision* (the browser tab's title counts them), next to the model
  answer and the grader's reason (which the student doesn't see for such an
  answer: it tends to give the right answer away). The lecturer picks what to
  tell the student (the grader's feedback, the model answer, or their own
  words), edits it if they like, and then *Let them continue* (the grade can be
  corrected there, when the grader was wrong) or *Ask to answer again* (the
  same question again; the first answer stays in the record). Until the
  decision the student can only ask questions, and the tutor neither answers
  the question nor shows the next step. `quiz_review` in exercise.yaml sets
  which grades wait (see the table below); an answer the grader couldn't grade
  never waits. The API is `POST /api/pacing/{exercise_id}/answer-review`
  (`{"probe_id": n, "action": "approve" | "return", "note": ..., "grade": 0..2}`).
- **Moving a student to another step.** In *Class pacing*, *Move to step…*
  on a student moves them back (their work from that step on, outputs and quiz
  answers, stays in the record with status `reset` but no longer counts, and
  the step's questions are asked again), forward (the steps between are marked
  `skipped`, not done, their questions aren't asked, and the steps up to the
  target are opened for that student even beyond what the class has open), or
  to the step they are on (it starts over). Their chat is interrupted: it stops
  waiting for a paste or a button answer, says "Your lecturer paused you" and why, and shows the step. *Everyone back to step…* does the same
  backwards for the whole course. The API is `POST /api/sessions/{id}/move`
  (`{"step": n}`), and `POST /api/sessions/{id}/reset` / `POST
  /api/exercises/{id}/reset` (`{"step": n, "course_id": ...}`) for going back;
  they work for any step-by-step lab.
- **Withdrawing a question during class.** *Withdraw approval* on a question
  stops asking it and, by default, takes it back from the course's students
  who were asked it: a student who hasn't answered is told the question was
  cancelled and their chat moves on; one who answered is told so with that
  question and their own answer quoted, and the answer no longer counts in the
  grade or the averages (status `withdrawn`, kept in the record). Approving it
  again can ask it again of everyone past its step.

### Chat history and resuming

The server keeps each session's chat transcript (`backend/transcript.py`):
everything the student chat showed and everything the student wrote. A student
who closes the browser or restarts the computer logs in again, gets the same
session back, sees the whole conversation replayed, and carries on from the
same step (a step already on screen only gets its *Done* button again). The
server's own notes to a student, such as a reset, reach an open chat through
the same transcript. Any client can use it: `GET /api/transcript/{session_id}`
(`?after=<id>`, `?origin=server`) and `POST` to append; teachers can read any
session's transcript.

| Setting | Where | Default |
|---|---|---|
| `chat_history: false` | exercise.yaml, or *Keep the chat history* in the exercise editor | on |
| `output_in_chat: confirm \| accept \| ask \| off` | exercise.yaml, or the exercise editor; a chat message while a step is open: `confirm` accepts a full match and asks about anything else, `accept` asks only about a partial match, `ask` asks about any match, `off` treats every message as a question | `confirm` |
| `answer_in_chat: detect \| confirm \| answer` | exercise.yaml, or the exercise editor; a chat message while a quiz or teacher's question is open (the question doesn't lock the chat, so the student can still ask): `detect` takes it as the answer unless it looks like a question (a question mark, a question word, "I don't understand"), and then asks "your answer, or a question of yours?"; `confirm` always asks; `answer` always takes it as the answer. "Done", or a message that matches the open step's output checks, still goes to the step. A question of the student's own goes to the tutor, or to the teacher in review mode; while it waits for the teacher (`X-VeriClass-Review` on the reply) the chat isn't busy, so the student can answer meanwhile | `detect` |
| `quiz_review: zero \| partial \| off` | exercise.yaml, or the exercise editor; a quiz answer in a class-paced lab that waits for the lecturer's decision before the next step: `partial` when the grader gave it 0/2 or 1/2 (only 2/2 moves on by itself), `zero` only when it gave 0/2, `off` never (the grade is only recorded) | `partial` |
| `resume_minutes: N` | exercise.yaml, or the exercise editor; how recent a session must be to be resumed, `0` = always | always for `pacing: class`, otherwise 30 |
| `CHAT_HISTORY_REPLAY_MAX` | environment | 400 (the latest entries replayed after a login) |

In `exercise.yaml`:

```yaml
pacing: class          # the lecturer opens steps for the whole class
open_steps: 8          # steps 1-8 are open from the start
workspace: codespace   # students work in a Codespace (no Windows/macOS lint)
steps:
  - label: B2          # the step's name in the chat and the dashboard
    title: Count the rows
    minutes: 4
    text: |
      ...what to do, and the commands in ```bash blocks (no expected output here:
      students would see it)...
```

In `teacher.yaml`, per step:

```yaml
    expected: The file has 3 data rows.     # the answer in words
    expected_output: |                      # what the commands print, shown to the
      rows: 3                               # lecturer next to a student's paste
    expect_output:     # checks a paste must pass; regular expressions, line by line
      - match: '^rows: \d+$'
        hint: the rows line                  # what the lecturer sees when it's missing
    quiz:
      - q: What does the script you just pasted do?
        answer: It writes the rows of the table to rows.csv, with a header line.
        always: true                         # asked without the dashboard's approval
      - q: Why does wc -l print one more than the number of rows?
        answer: It counts the header line too.
```

All of these can also be seen and changed in the dashboard's exercise editor
(per step: expected answer, expected output, output checks).

A long lab is easier to write as one Markdown file: `uv run python
scripts/steps_from_markdown.py <package>/source.md` writes exercise.yaml and
teacher.yaml from it (the format is at the top of the script).

Nothing in a browser can stop a student from opening another AI site: "only this
chat" is a class rule. Copilot can be turned off in a template repository's
`.devcontainer/devcontainer.json`.

## Sharing with students

Students open one link: the chat at `/chat/` on your VeriClass. **Share with
students** (top of the dashboard) shows it as text and as a QR code.

| How | When | What to do |
|---|---|---|
| **Quick public link** (Cloudflare) | The default: any class, any network | *Share with students → Create a public link*. The first time, the dashboard downloads `cloudflared` (or install it yourself: `brew install cloudflared`, `winget install --id Cloudflare.cloudflared`). The address is new every time, so share it at the start of each class. |
| **A fixed address** (ngrok) | The same link all semester | Install ngrok, sign in once (`ngrok config add-authtoken <token>`), claim your free static domain at <https://dashboard.ngrok.com>, and put it in `.env` as `NGROK_DOMAIN=your-name.ngrok-free.app`. *Create a public link* then uses it. The free plan has a monthly request limit that a large class can reach. |
| **Your own address** | A college server, your own domain or Cloudflare tunnel | Run VeriClass there (or point your tunnel at port 8010) and set `STUDENT_URL=https://…/chat/` in `.env`: the dashboard shows it as the students' link. On a server, also set `TEACHER_LOCAL_ONLY=false` so you can reach the dashboard. |
| **Same Wi-Fi only** | A lab room without internet access to your computer | Start with `--lan` (`./start.sh --lan`, `start.bat --lan`). *Share with students* shows the address under "Same Wi-Fi". Your firewall may ask to allow incoming connections. |

Keep the computer on, awake and online while students work: they are
connected to it. If it restarts, students sign in again and continue where
they were (their conversation is replayed).

Nothing in a browser can stop a student from opening another AI site: "only
this chat" is a class rule.

## Privacy

VeriClass is used with students, so it keeps as little as possible outside the
lecturer's computer.

- **Where data is kept.** Accounts, courses, every conversation, quiz answers
  and grades are in `vericlass.db`, and exercises in `data/`, both in the
  VeriClass folder on your computer. Nothing is sent to the VeriClass authors.
- **The LLM provider** you chose (Anthropic or Google) receives what the tutor
  needs to answer: the student's messages, the conversation so far, the lab's
  text and your tutor notes. Its own terms apply; tell your students which
  provider you use.
- **Names and identifiers are removed** before a conversation is given to the
  agents that draft answers for you, suggest questions and grade:
  `backend/sanitize.py` replaces students' names, ID numbers, emails and phone
  numbers. The tutor's direct answers get the student's messages as typed.
- **No outside accounts.** Usernames are made by VeriClass; there is no single
  sign-on, and an email address is kept only if your CSV has one.
- **The API key** is in `.env` on your computer, readable only by your user
  account. The dashboard never shows it again after it is saved.
- **Teacher-only content** (expected answers, output checks, model answers to
  quiz questions, in `teacher.yaml`) is never sent to students or to the tutor.

