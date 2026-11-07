# VeriClass — Instructor-Controlled LLM for CS Education

> English version · [גרסה עברית](README.he.md)

A locally-hosted LLM lab platform built for the *Intro to Operating Systems*
course at JCE. Students chat with a small local language model while working on
a programming exercise; the instructor watches every session in real time and
can intervene — by pushing targeted comprehension questions, switching the
model's persona, or (in the strictest mode) reviewing and rewriting every
answer before it reaches the student.

The repo ships with a working demo exercise (`ex3-mcalc`, 8 variants) so the
whole stack is usable the moment it's installed — zero configuration.

Students reach the tutor through either of two interchangeable clients against
the same backend: a **Chainlit web app** (a browser tab) or a **CLion plugin**
that embeds the same login → briefing → chat → probes flow in a tool window next
to their code. See [Alternative student client: the CLion plugin](#alternative-student-client-the-clion-plugin).

---

## Why this exists — the educational problem

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
  question at one or many students. The student must answer before the
  chat continues. Answers are auto-graded and stored alongside the
  transcript, providing assessment signal that survives the use of any AI.
- **Local-first privacy.** Student traffic stays on the local machine.
  The only external call is the instructor's own cloud-LLM use for
  generating probe suggestions, and even that goes through a PII
  sanitizer and is logged with token counts.

This is a working research platform for our department's broader question:
*what does responsible LLM-mediated CS instruction look like, in practice?*

---

## The three teaching modes

Modes are independent — you can mix them per session, per student, or
globally during a single lab.

### 1. Persona mode — `mentor` vs `coding_partner`
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

### 2. Probe mode — instructor-initiated comprehension checks
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

### 3. Teacher-review mode — full gating
Global toggle in the dashboard header. When on:

1. Student asks a question. It is in the instructor's review queue at once;
   the student sees *"Your teacher is reviewing your question…"*.
2. The backend drafts **five answers**, one model call each, all at the same
   time, each in English and Hebrew:
   - **Nudge** — one Socratic line, no answer
   - **Normal** — guidance plus a small pointer, no full solution
   - **Normal + more** — same, with an extra explanation or analogy
   - **Direct** — not Socratic: the plain answer to what was asked, with a
     short example (never the whole step's solution)
   - ✨ an extra answer by the **best model** (`CLAUDE_BEST_MODEL`, Opus 5.5;
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
   - 📚 **save to the question bank** (ticked by default; the default is a
     setting of the queue): the question, its step, the level and the final
     text go into the exercise's `faq.yaml` (or its database row when it has
     no package folder), so the next student who asks something similar shows
     the instructor's own answer first. The bank's answer sent again for a
     reworded question goes back into the same entry, which learns the new
     wording as a paraphrase.
   - 📣 **Send to all students**: for a question the whole class should hear
     (a conceptual one), the answer also goes to every student active on the
     exercise in the last 30 minutes (`BROADCAST_ACTIVE_MINUTES`; the same
     course as the student who asked, when they are in one), as a teacher's
     note in their chat, web and PyCharm alike, with the question quoted; it
     is in their chat at once if it is open, or after their next login, and
     the tutor remembers it as part of the conversation. The dashboard asks
     first and says how many students it reaches.
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
`GET /api/broadcast/recipients`. Tables: `review_answers` (one row per
drafted answer), `pending_reviews.chosen_slot`, `saved_to_bank`,
`sent_to_class`.

**Keeping the queue in step with the students.** Each question shows whether
the student is **waiting now** (their request is open) or **not waiting**: they
closed the chat, their connection dropped, the 10-minute wait ran out, or the
server restarted. An answer to a question nobody waits for is not lost: it is
stored and goes into the student's chat transcript, so the student chat shows it
at once if it is open again, or after their next login (a client that can show
it says so with `X-VeriClass-Transcript: 1`; for any other, such as the IDE
plugin, a timeout still closes the question). **🗑️ Delete** removes a question
sent by mistake or no longer relevant; with *tell the student* (default, off for
questions that look sent by mistake) a waiting student is told at once, and one
who left finds the note when they are back. **🧹 Delete the questions nobody is
waiting for** clears the leftovers in one click. A question the same student
asks again replaces its older copy, and a student who logs in again sees which
of their questions are still with the teacher. API: `POST /api/reviews/{id}/delete`
(`{"notify", "note"}`), `POST /api/reviews/delete-stale`, `GET /api/reviews/open/{session_id}`.

**Questions in other languages.** A question in neither Hebrew nor English (say,
Arabic or Russian) arrives with a translation under it: the model call that
drafts the nudge (the quickest) also names the question's language and
translates it, so it costs no extra call. The queue's 🌐 setting picks the language (Hebrew by
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

---

## Components

| # | Component        | Stack                      | Port  |
|---|------------------|----------------------------|-------|
| 1 | Agents           | CrewAI on Gemini (review drafts, probes, grading) | — |
| 2 | Student chat     | Gemini (streaming)         | —     |
| 3 | Backend          | FastAPI + SQLite (WAL)     | 8010  |
| 4 | Student app      | Chainlit                   | 8011  |
| 4b| Student app (alt)| CLion plugin (Kotlin)      | in-IDE|
| 5 | Instructor dash  | React + Vite + TypeScript  | 5173  |

The student has **two interchangeable clients** for the same backend: the
Chainlit web app (component 4) and a **CLion plugin** (4b) that puts the same
login → briefing → chat → probes flow inside the IDE. See
[*Alternative student client: the CLion plugin*](#alternative-student-client-the-clion-plugin)
and [`vericlass_plugin/README.md`](vericlass_plugin/README.md).

All LLM calls — the student chat and the CrewAI agents (review drafts, probe
suggestions, grading) — run on Gemini. Anything sent to the agents is first
passed through `backend/sanitize.py`, which strips names, codes, and other PII.

---

## Quick start

```bash
# 1. Python deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# edit .env — set GEMINI_API_KEY (the only LLM key needed)

# 4. Seed students — and at least one instructor (see "Instructor login" below)
python scripts/add_students.py \
  --names "Yossi Cohen,Shira Levi,Ahmed Alyan" \
  --teachers "Dr. Cohen"
```

Demo accounts after seeding:

| Name         | Login code | Role       |
|--------------|------------|------------|
| Instructor   | TEACH-XXXX   | teacher    |
| Yossi Cohen  | STU1-XXXX   | student    |
| Shira Levi   | STU2-XXXX   | student    |
| Ahmed Alyan  | STU3-XXXX   | student    |

> Sign into the dashboard (`http://localhost:5173`) with the **instructor**
> code **`TEACH-XXXX`**. Your own codes will differ — the seeding script
> generates them randomly; run the `sqlite3` query below to list yours.

Students go to `http://localhost:8011`, instructor to `http://localhost:5173`.
Prefer the IDE? Skip the browser and use the CLion plugin client instead — see
[Alternative student client: the CLion plugin](#alternative-student-client-the-clion-plugin).

### Instructor login

The dashboard (`http://localhost:5173`) is gated by an instructor login — its
sign-in screen reads **"כניסת מרצה — enter your instructor code"**. A teacher
signs in with a **login code**, exactly like a student, except their account
carries `role=teacher`. A student code is rejected here (*"That code isn't an
instructor account."*).

Create instructor codes with the same seeding script, using `--teachers`:

```bash
python scripts/add_students.py --teachers "Dr. Cohen,TA Levi"
```

It prints a `name → code` table (a separate **"teachers (dashboard login)"**
section). Distribute that code to the instructor; they type it into the login
screen (codes are case-insensitive). To add a teacher to an existing database
directly:

```bash
sqlite3 vericlass.db \
  "INSERT INTO users(username, login_code, role) VALUES('Dr. Cohen','TEACH-01','teacher');"
```

List the instructor codes already in your database at any time:

```bash
sqlite3 vericlass.db "SELECT username, login_code FROM users WHERE role='teacher';"
```

Only a `role=teacher` account can open the **Exercises** tab and author new
exercises, switch a student's persona, or toggle review mode.

### Passwords

Everyone logs in with a **username** (the login code) and a **password**. Until
you set one, the password is the username itself, in any case: nothing has to be
handed out. A password you set is stored only as a salted PBKDF2 hash and is
case-sensitive. Set or reset passwords in the dashboard (**Courses** tab,
*Passwords*), or from the command line:

```bash
python scripts/set_password.py yossico            # asks for the new password
python scripts/set_password.py yossico --reset    # back to the username
```

The password is required: plugins before 0.4.0 can't send one, so their users are
told to update the plugin.

### Courses

A student can be in several courses, and a course can offer several exercises.
In the dashboard's **Courses** tab, create a course, tick the exercises students
may open, pick the **default** (preselected) one, and tick its students.
`add_students.py --course devops-2026` adds new students straight to a course.

**Students from a CSV file.** In the Courses tab, *Import students (CSV)* reads a
list by column names, in English or Hebrew: name (or first + last name), and
optionally email, student id, course and group. A Moodle participants export
and a Hebrew CSV saved from Excel work as they are. Preview first, then
import; the new login codes download as a CSV. The same from the command line:
`python scripts/add_students.py --csv class.csv --course dl-2026 --codes-out codes.csv`,
or the MCP tool `import_students`. Students already in the system are matched
by email or ID, so importing a list again creates nobody twice.

**Meetings.** Each course can list its meetings (a date and an exercise). On
that date its students open the meeting's exercise without choosing, and the
course card shows the attendance of every meeting.

After logging in, a student picks a course, then one of its exercises. With one
course offering one exercise there is nothing to pick, and the exercise opens
directly. A student who is in no course gets the active exercise from the
**Exercises** tab, as before courses existed.

The web app (Chainlit) asks for the username and password in the chat. Set
`CHAINLIT_AUTH_SECRET` (from `chainlit create-secret`) to get Chainlit's own login
page instead, with a hidden password field.

---

## Launching everything — `scripts/dev_up.sh`

Running three services manually across three terminals gets tedious. The
launcher does it in one command:

```bash
./scripts/dev_up.sh
```

What it does:

1. **Kills** anything bound to ports `8010`, `8011`, `5173` (and the legacy
   `8000`/`8001`), plus any stray `uvicorn backend.main` / `chainlit run
   student_app` processes. Useful after a crash where the old process is still
   holding the port.
2. **Opens a new Terminal.app window with three tabs:**
   - tab 1: `uvicorn backend.main:app --reload --port 8010`
   - tab 2: `chainlit run student_app/app.py --port 8011`
   - tab 3: `cd dashboard && npm run dev`
3. The two Python tabs auto-`source .venv/bin/activate` before starting.

**First-run permission prompt.** macOS will ask Terminal to control
*System Events* (needed for the ⌘T keystroke that creates tabs). Grant it
once in *System Settings → Privacy & Security → Accessibility*.

**Dev-time auto-login.** Set `DEV_AUTO_LOGIN_CODE` in `.env` to a student
code (e.g. `STU1-XXXX`). The student app then skips the login prompt and
auto-logs in as that student — handy when you reload the page constantly
during development. Leave the variable empty in production.

---

## Suggested instructor workflow

A 90-minute lab session, end to end:

**Before class (5 min)**
- `./scripts/dev_up.sh` — verify the three tabs come up green.
- Open the dashboard. Confirm the active exercise is correct
  (`config/exercises/*.yaml`).
- Decide your mode profile for this lab. Common choices:
  - *Open practice:* persona=`coding_partner`, review mode off, occasional
    probes.
  - *Guided lab:* persona=`mentor`, review mode off, frequent probes.
  - *Assessment lab:* persona=`mentor`, **review mode on**, probes on every
    student.

**During class**
- Students log in with their codes (printed/projected). Each gets a
  deterministically-assigned variant.
- Watch the *Students* grid. Each card shows: name, variant, mode,
  last activity, probe count.
- Click *View chat* on any card to see the transcript live.
- Click *Ask them* to open the probe modal:
  - Type a question, or
  - *Suggest* — the cloud LLM proposes targeted questions based on this
    student's recent activity.
- If a student is racing ahead too fast / clearly leaning on the model
  too much, flip review mode on. Their next question will arrive in
  your queue.

**After class**
- All transcripts and probe results are in `vericlass.db`.

---

## Student experience

What the student sees:

1. Enter username and password → pick a course and exercise (skipped when
   there is only one) → assigned a variant of that exercise.
2. Receive a briefing bubble: exercise title, their personalized
   parameters, their test inputs, current mode.
3. Welcome suggestions appear as clickable chips (configurable per
   exercise YAML).
4. They chat with the model until they're satisfied with their solution.
5. At any moment, a probe may appear: *"Your instructor is asking you…"*.
   It stays open in the chat until they answer (they may ask something about
   it first); the auto-grade appears immediately.

Students cannot see other students' work, swap variants, or bypass probes.
The chat is rate-limited via prompt-injection denylist phrases in
`backend/routes/ask.py`.

This experience is identical whether the student uses the Chainlit web app or
the CLion plugin. In the plugin's `ide` mode (see below), steps 1–5 are the same,
and the plugin additionally drops a starter `mcalc.c` into their project and
shows their test inputs as a checklist.

---

## Alternative student client: the CLion & PyCharm plugin

Students already work in a JetBrains IDE — CLion for C, PyCharm for Python. The
[`vericlass_plugin/`](vericlass_plugin/) directory is a JetBrains plugin that embeds the
*entire* student client in an IDE tool window, so they never leave the IDE to
talk to the tutor. One shared source tree builds both the CLion and PyCharm
plugins (`:clion` / `:pycharm` Gradle modules). It uses the same six backend
endpoints as Chainlit — the
backend is unchanged except for one tiny read-only endpoint
(`GET /api/client-config`) that exposes the behavior switch below.

It ships **two behaviors in one plugin**, and the instructor picks which one via
**a single `.env` variable on the backend** (so every student is controlled from
one place — it is *not* a per-student plugin setting):

| `.env`                       | Plugin behavior |
|------------------------------|-----------------|
| `STUDENT_CLIENT_MODE=chat`   | Faithful chat port — login, briefing, streaming chat, suggestion chips, probes. Same as Chainlit, in a tool window. |
| `STUDENT_CLIENT_MODE=ide`    | Everything in `chat`, **plus** it scaffolds the student's assigned variant as a starter `mcalc.c` in their project and shows the variant's required test inputs as a checklist. |

Build & run (full details in [`vericlass_plugin/README.md`](vericlass_plugin/README.md)):

```bash
cd vericlass_plugin
gradle wrapper --gradle-version 8.10.2   # one-time, generates the wrapper jar
./gradlew :clion:runIde                  # sandbox CLion with the plugin
./gradlew :pycharm:runIde                # sandbox PyCharm with the plugin
```

In the sandbox, set the backend URL under **Settings → Tools → VeriClass**, open the
**VeriClass** tool window, and log in with a course code. Chainlit and the plugin can
be used at the same time against the same backend.

**Shipping updates to students without passing files around.** When the backend
is exposed over a tunnel (see [`deploy/README-NGROK.md`](deploy/README-NGROK.md)),
it also distributes the plugin. Build + upload once on the JDK-21 machine
(`cd vericlass_plugin && ./publish.sh` — add `--product pycharm` for the PyCharm
build), then each student runs a single command:

```bash
curl -fsSL https://<your-domain>.ngrok-free.dev/api/plugin/install.sh | bash
```

That installs the latest build into their matching IDE, CLion or PyCharm (they
just restart). Full
details in [`vericlass_plugin/README.md`](vericlass_plugin/README.md) →
*Distributing updates over the tunnel*.

---

## Chat-only labs in a GitHub Codespace (class pacing)

For a long step-by-step lab that students do in a **GitHub Codespace**, with the
student chat (the Chainlit app) as the only chat they may use. The chat hands out
the lab one step at a time; the lecturer keeps the whole class on the same step.
The PyCharm plugin (0.5.0+) runs the same labs in its tool window, with the same
rules: there *Done* opens a box already filled with what the VeriClass Terminal
ran since the step appeared, which the student checks (or replaces) and sends.

- **Steps open from the start** (`open_steps`, e.g. the setup part) go at each
  student's own pace, until the lecturer sets the course's marker in the
  dashboard (*Class pacing*: "▶ Open B4", or "Open up to…" any step, including
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
- **Back to an earlier step.** In *Class pacing*, "↺ Back to step…" on a
  student (or "↺ Everyone back to step…" for the course) sends them back, to
  the beginning if need be. Their work from that step on stays in the record
  (status `reset`) but no longer counts, questions still waiting about those
  steps are withdrawn, and their chat says so and shows the step again. The
  API is `POST /api/sessions/{id}/reset` and `POST /api/exercises/{id}/reset`
  (`{"step": n, "course_id": ...}`); it works for any step-by-step lab.

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
      - q: Why does wc -l print one more than the number of rows?
        answer: It counts the header line too.
```

All of these can also be seen and changed in the dashboard's exercise editor
(per step: expected answer, expected output, output checks).

A long lab is easier to write as one Markdown file: `python
scripts/steps_from_markdown.py <package>/source.md` writes exercise.yaml and
teacher.yaml from it (the format is at the top of the script).

**Serving the chat.** `bash deploy/tunnel.sh --with-chat` starts the backend
with the chat inside it (`STUDENT_CHAT_PATH=/chat`), so students open
`https://<your-domain>/chat/` and the one tunnel serves everything. Set
`CHAINLIT_AUTH_SECRET` (`chainlit create-secret`) for a login page with a hidden
password field. The chat lays Hebrew out right to left and code left to right
(`public/vericlass-chat.css`, `public/vericlass-chat.js`).

Nothing in a browser can stop a student from opening another AI site: "only this
chat" is a class rule. Copilot can be turned off in a template repository's
`.devcontainer/devcontainer.json`.

## Writing exercises

Each lecturer runs their own VeriClass server. Exercises are **packages**:
folders in a private data folder next to the code (`VERICLASS_DATA_DIR`, default
`../VeriClassPrivateData`), which never goes into git:

```
VeriClassPrivateData/exercises/<exercise_id>/
  exercise.yaml   what students and the tutor see (brief, steps, tutor notes, terminal rules)
  teacher.yaml    teacher-only: each step's expected answer, reference commands, evidence rules
  faq.yaml        the question bank: likely questions per step with four ready answers
  files/          what students download (served at /api/files/<name>)
  solution/       the lecturer's solution; never served
```

The folder is the source of truth: the server loads it, and the dashboard's
edits are written back into it. Three ways to add or change an exercise:

1. **In your own Claude Code session** (no server tokens). The MCP server in
   `vericlass_mcp/` gives Claude tools for your server: start an exercise in
   `drafts/`, check it (`validate_exercise`), install it (`push_exercise`,
   optionally into a course or as a dated meeting), import students, read an
   anonymized class report. Register it once with `scripts/install_mcp.sh`.
   The exercise-writing **skill** that turns slides, a Word file of an earlier
   exercise or an idea into a finished package (with a question bank of about
   50 questions, made by simulating students) is not part of this repository.
   **Lecturers who want it: email me at shpanier@gmail.com.**
2. **Upload a zipped package** in the dashboard's Exercises tab.
3. **Edit in the dashboard**: texts, steps, expected answers, tutor notes, the
   terminal hint and the check command (no model involved). *Export* gives any
   exercise as a package zip.

`scripts/to_package.py` turns a one-file exercise into a package. Simple
coding exercises with per-student **variants** can still be YAML files in
`config/exercises/` (the demos ex3–ex5) or made with *New exercise*:

```yaml
exercise_id: ex4-myexercise
title_en: My Exercise
default_mode: mentor       # mentor | coding_partner
brief_md: |
  Markdown shown to the student in the briefing bubble.
welcome_suggestions:
  - "How should I start?"
  - "What does the test input look like?"
variants:
  - id: A
    params: { N: 5, operator: "+" }
    test_inputs:
      - { input: "1+1", expected_output: "2" }
  - id: B
    ...
```

The system picks the *active* exercise (first one alphabetically in
the directory by default). Variants are assigned to students by hashing
their user id — so the same student always gets the same variant across
sessions.

Design goals for a good variant set:
- Same conceptual difficulty across variants.
- Different enough that a peer's chat transcript won't pass your tests.
- Test inputs that exercise edge cases tied to the variant params.

---

## Privacy & data sovereignty

This is a teaching tool used with under-18 and adult students at a public
institution, so the privacy posture stays conservative:

- **Gemini is the single LLM provider.** Student chat and the CrewAI agents
  all run on Google's Gemini — there is no local Ollama path and no
  multi-provider fallback. Student messages are processed by Google; size
  your consent/notice accordingly.
- **Everything sent to the agents is sanitized first.** `backend/sanitize.py`
  strips names, ID numbers, emails, phone numbers, and home paths from the
  transcript before it is threaded into a probe/answer agent.
- **Audit log.** Every cloud call is written to `api_audit_log` with
  provider, model, token counts, latency, the sanitized input, and an
  AES-encrypted copy of the raw payload. Set `AUDIT_AES_KEY` in `.env`.
- **No student account leaves the database.** Login codes are
  generated locally by `scripts/add_students.py`; there is no SSO,
  no email collection, no third-party auth.

---

## Repository layout

```
config/
  exercises/ex3-mcalc.yaml   # the demo exercise + 8 variants
  cloud_llm.yaml             # Gemini model + timeout for the agent layer
  instructors.yaml.example   # copy to instructors.yaml and edit

backend/                     # FastAPI app
  main.py                    # entrypoint, loads .env early
  db.py                      # SQLite schema + tiny migration runner
  auth.py                    # login codes, bearer tokens, rate-limit
  student_llm.py             # Gemini-only streaming for the direct student chat
  gemini_student.py          # httpx streaming + grader against Gemini
  agents/                    # CrewAI agent layer (Gemini only)
    llm.py                   #   single Gemini LLM factory
    memory.py                #   conversation memory (transcript + prior probes)
    schemas.py               #   structured-output models
    tutor.py                 #   review-mode answer drafts (replaces variants_gen)
    probe.py                 #   "Ask Them" probe suggestions (replaces cloud_llm)
    grader.py                #   probe answer grading
  sanitize.py                # PII scrub before anything leaves for Gemini
  variants.py                # deterministic student → variant assignment
  prompts.py                 # system prompts per (exercise, mode)
  exercises.py               # YAML loader and accessor
  pacing.py                  # class-paced labs: open steps, output checks, quiz
  transcript.py              # each session's chat transcript, replayed after a new login
  routes/
    login.py, sessions.py, exercises.py, ask.py,
    probes.py, students.py, mode.py, review.py, pacing.py, transcript.py

student_app/
  app.py                     # Chainlit student UI (login + chat + probes + paced steps)
public/
  vericlass-chat.css, .js    # the chat: Hebrew right to left, code left to right

vericlass_plugin/                # alternative student client: a CLion/JetBrains plugin
  build.gradle.kts           # IntelliJ Platform Gradle build (targets CLion)
  src/main/kotlin/edu/jce/vericlass/
    api/                     # DTOs + HTTP/streaming client over the 6 endpoints
    ui/                      # tool window, login, briefing, chat, checklist
    probe/                   # 2s probe poller + answer dialog
    ide/                     # `ide` mode: scaffold mcalc.c into the project
    settings/, util/

dashboard/
  src/App.tsx                # student grid + modals + review queue
  src/components/            # StudentGrid, ChatViewModal, AskThemModal,
                             #   ReviewQueue, ExerciseHeader

scripts/
  add_students.py            # seed users + login codes
  dev_up.sh                  # kill old + launch all three services
```

---

## Configuration reference

`.env` (copy from `.env.example`):

| Variable              | Purpose                                                       |
|-----------------------|---------------------------------------------------------------|
| `GEMINI_API_KEY`      | The only LLM key. Powers the CrewAI agents and the student chat. |
| `AGENT_MODEL`         | Gemini model for the agents (review drafts, probes, grading). Default `gemini-2.5-pro`. |
| `STUDENT_CHAT_MODEL`  | Gemini model for the direct student chat. Default `gemini-2.5-flash-lite`. |
| `DB_PATH`             | `./vericlass.db` by default.                                      |
| `AUDIT_AES_KEY`       | 32-byte base64 key for encrypting raw cloud-LLM payloads.     |
| `DEV_AUTO_LOGIN_CODE` | If set, student app auto-logs in with this code (dev only; ignored when `STUDENT_CHAT_PATH` is set). |
| `STUDENT_CLIENT_MODE` | CLion plugin behavior: `chat` (default) or `ide`. Ignored by Chainlit. |
| `SCAFFOLD_FILENAME`   | File the plugin's `ide` mode scaffolds into the project. Default `mcalc.c`. |
| `VERICLASS_DATA_DIR`   | The private data folder (exercise packages, login codes, reports). Default `../VeriClassPrivateData`. |
| `CHAT_HISTORY_REPLAY_MAX` | How many of a session's latest chat-transcript entries a new login replays (default 400). |
| `STUDENT_CHAT_PATH`   | Serve the student chat inside the backend at this path (e.g. `/chat`); `deploy/tunnel.sh --with-chat` sets it. Off by default. |
| `BACKEND_URL`         | Where the student chat calls the backend's API. Default `http://127.0.0.1:8010`. |
| `CLAUDE_STRONG_MODEL`, `CLAUDE_BEST_MODEL` | The review queue's *Redo with* models (Sonnet 5.5, Opus 5.5); the best model also writes the queue's extra answer for every question. |
| `BROADCAST_ACTIVE_MINUTES` | "All students" (an answer sent to the class, `POST /api/broadcast`) = those active on the exercise in the last this many minutes (default 30). |
| `TUTOR_TIMEOUT_SEC`, `TUTOR_MAX_TOKENS` | One review draft's model call: timeout (120) and output size (4096). |
| `BANK_MATCH_THRESHOLD`, `BANK_AUTO_ANSWER`, `BANK_AUTO_THRESHOLD` | When the question bank's answer is shown, or (review mode off) sent directly. |

`config/cloud_llm.yaml` sets the Gemini model and timeout the agent layer
uses. Everything runs on the single `GEMINI_API_KEY`.

---

## Research & roadmap

This is a research platform, not a finished product. Open directions
we're exploring:

- **Adaptive scaffolding.** Auto-select the answer-level (nudge / normal /
  more) based on the student's probe history rather than instructor click.
- **Multi-exercise sessions.** Currently one active exercise at a time.
  We want concurrent active exercises with per-section assignment.
- **Cross-session memory for the instructor.** A long-term per-student
  view that aggregates probes, mode usage, and chosen answer levels.
- **Replicability.** Packaged as a single Docker stack for departments
  that don't want to run Python and Node themselves.

Contributions and bug reports welcome — file an issue or PR.

---

## License & attribution

- **Code** — [MIT License](LICENSE).
- **Educational materials** (exercises, briefings, slides, and documentation) —
  [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
  You are free to share and adapt them, as long as you give appropriate credit.

**If you use this project or its exercises in teaching or research, please cite
it and let me know — I'd love to hear how it's used.**

Built at the *Software Engineering Seminar*, Azrieli College of Engineering
Jerusalem (JCE).

## Contact

Please contact me if you want any help, have questions, ideas, or would like to
collaborate: **shpanier@gmail.com**
