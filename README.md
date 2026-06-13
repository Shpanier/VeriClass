# OS Lab — Instructor-Controlled LLM for CS Education

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
in the variant-generation prompt (`backend/variants_gen.py`).

---

## Components

| # | Component        | Stack                      | Port  |
|---|------------------|----------------------------|-------|
| 1 | Local LLM        | Ollama + `qwen2.5-coder:3b`| 11434 |
| 2 | Cloud LLM        | Gemini 2.5 / OpenAI / Claude | —   |
| 3 | Backend          | FastAPI + SQLite (WAL)     | 8000  |
| 4 | Student app      | Chainlit                   | 8001  |
| 4b| Student app (alt)| CLion plugin (Kotlin)      | in-IDE|
| 5 | Instructor dash  | React + Vite + TypeScript  | 5173  |

The student has **two interchangeable clients** for the same backend: the
Chainlit web app (component 4) and a **CLion plugin** (4b) that puts the same
login → briefing → chat → probes flow inside the IDE. See
[*Alternative student client: the CLion plugin*](#alternative-student-client-the-clion-plugin)
and [`clion_plugin/README.md`](clion_plugin/README.md).

The local LLM is the only path that sees student messages. The cloud LLM is
used **only** for instructor-side probe suggestion (`/api/probe/suggest`),
and only after `backend/sanitize.py` strips names, codes, and other PII.

---

## Quick start

```bash
# 1. Install Ollama and pull the model (one time)
ollama pull qwen2.5-coder:3b

# 2. Python deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# edit .env — set GEMINI_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY)

# 4. Seed students
python scripts/add_students.py --names "Yossi Cohen,Shira Levi,Ahmed Alyan"
```

Demo students after seeding:

| Name         | Login code |
|--------------|------------|
| Yossi Cohen  | STU1-XXXX   |
| Shira Levi   | STU2-XXXX   |
| Ahmed Alyan  | STU3-XXXX   |

Students go to `http://localhost:8001`, instructor to `http://localhost:5173`.
Prefer the IDE? Skip the browser and use the CLion plugin client instead — see
[Alternative student client: the CLion plugin](#alternative-student-client-the-clion-plugin).

---

## Launching everything — `scripts/dev_up.sh`

Running three services manually across three terminals gets tedious. The
launcher does it in one command:

```bash
./scripts/dev_up.sh
```

What it does:

1. **Kills** anything bound to ports `8000`, `8001`, `5173`, plus any stray
   `uvicorn backend.main` / `chainlit run student_app` processes. Useful
   after a crash where the old process is still holding the port.
2. **Opens a new Terminal.app window with three tabs:**
   - tab 1: `uvicorn backend.main:app --reload --port 8000`
   - tab 2: `chainlit run student_app/app.py --port 8001`
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
- All transcripts and probe results are in `oslab.db`. Useful queries:

```sql
-- Per-student probe scores
SELECT u.username, COUNT(p.id) AS probes,
       AVG(COALESCE(p.override_grade, p.auto_grade)) AS avg_score
FROM users u
JOIN sessions s ON s.user_id = u.id
JOIN probes p ON p.session_id = s.id
WHERE p.status = 'answered'
GROUP BY u.username;

-- Distribution of answer levels chosen in review mode
SELECT s.user_id, answer_level, COUNT(*)
FROM messages m JOIN sessions s ON s.id = m.session_id
WHERE answer_level IS NOT NULL
GROUP BY s.user_id, answer_level;
```

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

## Alternative student client: the CLion plugin

Students in this course already write their C in CLion. The
[`clion_plugin/`](clion_plugin/) directory is a JetBrains plugin that embeds the
*entire* student client in a CLion tool window, so they never leave the IDE to
talk to the tutor. It uses the same six backend endpoints as Chainlit — the
backend is unchanged except for one tiny read-only endpoint
(`GET /api/client-config`) that exposes the behavior switch below.

It ships **two behaviors in one plugin**, and the instructor picks which one via
**a single `.env` variable on the backend** (so every student is controlled from
one place — it is *not* a per-student plugin setting):

| `.env`                       | Plugin behavior |
|------------------------------|-----------------|
| `STUDENT_CLIENT_MODE=chat`   | Faithful chat port — login, briefing, streaming chat, suggestion chips, probes. Same as Chainlit, in a tool window. |
| `STUDENT_CLIENT_MODE=ide`    | Everything in `chat`, **plus** it scaffolds the student's assigned variant as a starter `mcalc.c` in their project and shows the variant's required test inputs as a checklist. |

Build & run (full details in [`clion_plugin/README.md`](clion_plugin/README.md)):

```bash
cd clion_plugin
gradle wrapper --gradle-version 8.10.2   # one-time, generates the wrapper jar
./gradlew runIde                         # launches a sandbox CLion with the plugin
```

In the sandbox, set the backend URL under **Settings → Tools → OS Lab**, open the
**OS Lab** tool window, and log in with a course code. Chainlit and the plugin can
be used at the same time against the same backend.

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
institution, so the privacy posture is conservative by default:

- **Student chat traffic never leaves the local network.** The default
  `STUDENT_LLM=ollama` runs entirely on the instructor's laptop / lab
  server. `STUDENT_LLM=gemini` is an **opt-in dev/debug shortcut** that
  *does* route student messages to Google — use only when you mean it.
- **The cloud LLM call has one job only:** generating probe suggestions
  for the instructor. It receives a *sanitized* version of the
  transcript (`backend/sanitize.py` strips names, codes, file paths,
  IPs) and never sees student identifiers.
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
  cloud_llm.yaml             # provider: gemini | openai | anthropic
  instructors.yaml.example   # copy to instructors.yaml and edit

backend/                     # FastAPI app
  main.py                    # entrypoint, loads .env early
  db.py                      # SQLite schema + tiny migration runner
  auth.py                    # login codes, bearer tokens, rate-limit
  student_llm.py             # dispatcher: ollama vs gemini at startup
  ollama_client.py           # streaming chat + grader against local LLM
  gemini_student.py          # same, against Gemini (dev-only)
  cloud_llm.py               # instructor-side cloud call (probe suggest)
  sanitize.py                # PII scrub before any cloud call
  variants.py                # deterministic student → variant assignment
  variants_gen.py            # 3-level answer generator for review mode
  prompts.py                 # system prompts per (exercise, mode)
  exercises.py               # YAML loader and accessor
  routes/
    login.py, sessions.py, exercises.py, ask.py,
    probes.py, students.py, mode.py, review.py

student_app/
  app.py                     # Chainlit student UI (login + chat + probes)

clion_plugin/                # alternative student client: a CLion/JetBrains plugin
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
| `GEMINI_API_KEY`      | Cloud LLM key; used for probe suggestions and the dev-only `STUDENT_LLM=gemini` path. |
| `OPENAI_API_KEY`      | Alternative cloud provider. Match with `config/cloud_llm.yaml`. |
| `ANTHROPIC_API_KEY`   | Alternative cloud provider.                                   |
| `STUDENT_LLM`         | `ollama` (default, private) or `gemini` (dev only).           |
| `STUDENT_LLM_MODEL`   | Used when `STUDENT_LLM=gemini`. Default `gemini-2.5-flash-lite`. |
| `OLLAMA_HOST`         | `http://127.0.0.1:11434` by default.                          |
| `OLLAMA_MODEL`        | `qwen2.5-coder:3b` recommended for laptops; `:7b` for GPU.    |
| `DB_PATH`             | `./oslab.db` by default.                                      |
| `AUDIT_AES_KEY`       | 32-byte base64 key for encrypting raw cloud-LLM payloads.     |
| `DEV_AUTO_LOGIN_CODE` | If set, student app auto-logs in with this code (dev only).   |
| `STUDENT_CLIENT_MODE` | CLion plugin behavior: `chat` (default) or `ide`. Ignored by Chainlit. |
| `SCAFFOLD_FILENAME`   | File the plugin's `ide` mode scaffolds into the project. Default `mcalc.c`. |

`config/cloud_llm.yaml` picks the provider and model used for
instructor-side suggestions. Keep this in sync with the API key you set.

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

Built at the *Software Engineering Seminar*, JCE Lev Academic Center.
Educational and research use.
