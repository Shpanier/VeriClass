# VeriExam — Instructor-Controlled LLM for CS Education

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

The student's chat is interrupted with the probe. Their answer is
auto-graded 0–2 and saved. You can later override the auto-grade.

This is the assessment backbone: probes test whether the student
*understands* what the AI helped them produce.

### 3. Teacher-review mode — full gating
Global toggle in the dashboard header. When on:

1. Student asks a question.
2. The backend generates **three answer variants** in one LLM call:
   - **Nudge** — one Socratic line, no answer
   - **Normal** — guidance plus a small pointer, no full solution
   - **Normal + more** — same, with an extra explanation or analogy
3. The question and all three variants appear in the instructor's review
   queue. The student sees *"Your teacher is reviewing your question…"*.
4. The instructor picks one. That text streams to the student.
5. The chosen level is logged on `messages.answer_level` for later
   correlation with the student's grade.

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
and [`oslab_plugin/README.md`](oslab_plugin/README.md).

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
sqlite3 oslab.db \
  "INSERT INTO users(username, login_code, role) VALUES('Dr. Cohen','TEACH-01','teacher');"
```

List the instructor codes already in your database at any time:

```bash
sqlite3 oslab.db "SELECT username, login_code FROM users WHERE role='teacher';"
```

Only a `role=teacher` account can open the **Exercises** tab and author new
exercises, switch a student's persona, or toggle review mode.

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
- All transcripts and probe results are in `oslab.db`.

---

## Student experience

What the student sees:

1. Enter login code → assigned a variant of the active exercise.
2. Receive a briefing bubble: exercise title, their personalized
   parameters, their test inputs, current mode.
3. Welcome suggestions appear as clickable chips (configurable per
   exercise YAML).
4. They chat with the model until they're satisfied with their solution.
5. At any moment, a probe may appear: *"Your instructor is asking you…"*.
   They must type an answer before the chat continues; the auto-grade
   appears immediately.

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
[`oslab_plugin/`](oslab_plugin/) directory is a JetBrains plugin that embeds the
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

Build & run (full details in [`oslab_plugin/README.md`](oslab_plugin/README.md)):

```bash
cd oslab_plugin
gradle wrapper --gradle-version 8.10.2   # one-time, generates the wrapper jar
./gradlew :clion:runIde                  # sandbox CLion with the plugin
./gradlew :pycharm:runIde                # sandbox PyCharm with the plugin
```

In the sandbox, set the backend URL under **Settings → Tools → VeriExam**, open the
**VeriExam** tool window, and log in with a course code. Chainlit and the plugin can
be used at the same time against the same backend.

**Shipping updates to students without passing files around.** When the backend
is exposed over a tunnel (see [`deploy/README-NGROK.md`](deploy/README-NGROK.md)),
it also distributes the plugin. Build + upload once on the JDK-21 machine
(`cd oslab_plugin && ./publish.sh` — add `--product pycharm` for the PyCharm
build), then each student runs a single command:

```bash
curl -fsSL https://<your-domain>.ngrok-free.dev/api/plugin/install.sh | bash
```

That installs the latest build into their matching IDE, CLion or PyCharm (they
just restart). Full
details in [`oslab_plugin/README.md`](oslab_plugin/README.md) →
*Distributing updates over the tunnel*.

---

## Designing new exercises

Exercises are YAML files in `config/exercises/`. Minimum shape:

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
  routes/
    login.py, sessions.py, exercises.py, ask.py,
    probes.py, students.py, mode.py, review.py

student_app/
  app.py                     # Chainlit student UI (login + chat + probes)

oslab_plugin/                # alternative student client: a CLion/JetBrains plugin
  build.gradle.kts           # IntelliJ Platform Gradle build (targets CLion)
  src/main/kotlin/edu/jce/oslab/
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
| `DB_PATH`             | `./oslab.db` by default.                                      |
| `AUDIT_AES_KEY`       | 32-byte base64 key for encrypting raw cloud-LLM payloads.     |
| `DEV_AUTO_LOGIN_CODE` | If set, student app auto-logs in with this code (dev only).   |
| `STUDENT_CLIENT_MODE` | CLion plugin behavior: `chat` (default) or `ide`. Ignored by Chainlit. |
| `SCAFFOLD_FILENAME`   | File the plugin's `ide` mode scaffolds into the project. Default `mcalc.c`. |

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
