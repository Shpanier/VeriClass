# OS Lab — Instructor-Controlled LLM for CS Education
### Conference Presentation · Detailed Table of Contents & Speaker Guide
**Format:** 12-minute talk (≈ 11 min speaking + 1 min buffer) · 13 slides · ~55 sec/slide average
**Audience:** CS educators, ed-tech researchers, curriculum designers
**One-line pitch:** *Not "should students use AI?" but "how do we integrate it so learning survives?" — an instructor-in-the-loop LLM lab with live oversight, per-student variants, and comprehension probes.*

---

## Timing map (12 minutes)

| Block | Slides | Time | Cumulative |
|-------|--------|------|-----------|
| A. Hook & problem | 1–3 | 2:30 | 2:30 |
| B. Core idea & architecture | 4–5 | 2:00 | 4:30 |
| C. The three teaching modes (heart of talk) | 6–8 | 3:30 | 8:00 |
| D. Anti-cheating + assessment that survives AI | 9–10 | 2:00 | 10:00 |
| E. Privacy, agents & grading | 11 | 1:00 | 11:00 |
| F. Results, roadmap, close | 12–13 | 1:00 | 12:00 |

> **Pacing rule:** if you're behind at Slide 8, cut the live demo detail on Slide 10, not the mode explanation. The three modes are the contribution.

---

## Slide-by-slide

### Slide 1 — Title (0:00–0:20)
**On slide:** Title, your name/affiliation (JCE — Azrieli College of Engineering Jerusalem), one screenshot of the instructor dashboard grid.
**Say:** *"Intro to Operating Systems, first-year students. Every one of them is already using ChatGPT. The question for us as instructors isn't whether to allow it — that ship sailed — it's how to keep them learning while they do."*
**Note:** Open on the tension, not the tech. 20 seconds, then move.

---

### Slide 2 — The two failure modes of naive LLM integration (0:20–1:20)
**On slide:** Two icons/panels side by side.
1. **The answer-vending machine** — first prompt → polished full solution → copy-paste → test passes → *nothing learned*.
   2. **The invisible session** — instructor has zero view of *how* the model was used. Stuck? Misled? One-shot answer or productive struggle?

**Say:** *"Give every student a raw chat window and you get one of these two. Both are pedagogical dead ends. The first destroys the exercise; the second destroys your ability to assess it."*
**Example to voice:** *"A student pastes 'write me a mini-calculator in C', gets 40 lines back, submits it, passes. You, the instructor, see a green checkmark and learn nothing about that student."*

---

### Slide 3 — Our design thesis: four ideas (1:20–2:30)
**On slide:** Four labeled pillars.
- **Instructor in the loop** — every layer from passive watching to full answer-gating is available; *you* choose how much control.
  - **Variant assignment** — each student deterministically gets 1 of N parameterized exercise variants; a peer's transcript won't pass *their* tests.
  - **Comprehension probes** — mid-lab targeted questions, auto-graded, stored beside the transcript — assessment that survives any AI use.
  - **Local-first privacy** — student traffic stays local; the only cloud call is PII-sanitized and audit-logged.

**Say:** *"These four ideas are the whole talk. Everything else is how we make them real."*
**Note:** This is your roadmap slide — audience should be able to predict the structure from here.

---

### Slide 4 — System architecture at a glance (2:30–3:30)
**On slide:** Simple 5-box diagram with ports.

| Component | Stack | Port |
|-----------|-------|------|
| Instructor dashboard | React + Vite + TS | 5173 |
| Backend | FastAPI + SQLite (WAL) | 8010 |
| Student chat | Gemini (streaming) | — |
| Student client A | Chainlit web app | 8011 |
| Student client B | **CLion plugin (Kotlin)** | in-IDE |
| Agent layer | CrewAI on Gemini | — |

**Say:** *"One backend, two interchangeable student clients. Students in this course already write C in CLion — so we embedded the entire tutor flow inside the IDE as a plugin. Same login → briefing → chat → probes, without leaving their editor."*
**Note:** The dual-client (browser *or* IDE plugin, same backend) is a memorable differentiator — spend a sentence on it.

---

### Slide 5 — What the student sees (3:30–4:30)
**On slide:** Student flow, 5 steps, with a Chainlit + a CLion screenshot.
1. Enter login code → assigned a variant.
   2. Briefing bubble: title, *their* parameters, *their* test inputs, current mode.
   3. Clickable welcome-suggestion chips.
   4. Chat with the model.
   5. A probe can interrupt at any moment — must answer before chat continues; auto-grade shown instantly.

**Say:** *"Students can't see each other's work, can't swap variants, can't skip probes. In IDE mode the plugin even drops a starter `mcalc.c` into their project and shows their test inputs as a checklist."*

---

### Slide 6 — Mode 1: Persona (4:30–5:30)
**On slide:** Two personas contrasted.
- **`mentor`** — Socratic. Asks questions back, refuses full code, points at concepts. Default early.
  - **`coding_partner`** — collaborative. Writes small fragments, still no finished solution. Default once comprehension is shown.

**Say:** *"The lightest touch. A system-prompt switch, set per student from their dashboard card. Same student, same question — but in mentor mode the model answers with a question, in coding-partner mode with a fragment."*
**Example to voice:** *Student: "How do I parse the operator?"* — mentor: *"What does each character in your input string represent — how could you tell an operator from a digit?"* vs. coding_partner: *"You can switch on the char: `case '+': ...`. Try filling in the branches."*

---

### Slide 7 — Mode 2: Comprehension probes (5:30–6:45)
**On slide:** The "Ask Them" flow.
- Instructor opens *Ask Them* on a student card → types a question, **or** clicks **Suggest**.
  - **Suggest** = the cloud LLM reads the student's recent transcript and proposes 2–3 probes targeted at apparent gaps.
  - Student's chat interrupts with the probe → answer auto-graded **0–2** → stored. Instructor can override the grade later.

**Say:** *"This is the assessment backbone. It doesn't test whether the code works — it tests whether the student understands what the AI helped them produce. And crucially, it survives the AI: a probe answer is the student's own words, in the moment."*
**Example to voice:** *"Student's transcript shows they got a working modulo operator from the model. The Suggest button proposes: 'Your code uses `%` — what would it print for `-7 % 3`, and why?' If they can't answer, the green checkmark was a lie."*

---

### Slide 8 — Mode 3: Teacher-review / full gating (6:45–8:00)
**On slide:** The review-queue pipeline.
1. Student asks a question.
   2. Backend generates **three answer variants in one LLM call**:
      - **Nudge** — one Socratic line, no answer
      - **Normal** — guidance + small pointer, no full solution
      - **Normal + more** — same, plus an extra explanation/analogy
   3. All three land in the instructor's review queue; student sees *"Your teacher is reviewing your question…"*.
   4. Instructor picks one → it streams to the student.
   5. Chosen level logged on `messages.answer_level` for later grade correlation.

**Say:** *"The strictest mode, for high-stakes or summative labs. The model NEVER returns a full working solution at any level — that's enforced in the tutor agent, not left to prompt luck. And the drafts are grounded in this student's actual conversation, so they scaffold this student, not a generic one."*
**Note:** Emphasize the *spectrum*: persona (shape style) → probe (check understanding) → review (gate every answer). Mix per student, per session, mid-lab.

---

### Slide 9 — Why variants defeat answer-sharing (8:00–9:00)
**On slide:** Two students, same exercise, different params/test inputs.
- Variant assigned by hashing user id → same student always gets the same variant.
  - Variant A: `{N: 5, operator: "+"}`, test `1+1 → 2`. Variant B: different params, different expected outputs.
  - **Design goal:** same conceptual difficulty, different enough that a peer's transcript won't pass your tests.

**Say:** *"Personalization as an anti-cheating mechanism. Two students can share a chat transcript all they want — it won't pass the other's test cases. Cheating now costs as much cognitive effort as just learning it."*

---

### Slide 10 — Assessment that survives AI: the instructor workflow (9:00–10:00)
**On slide:** A 90-min lab, three phases + the mode-profile presets.
- **Open practice:** `coding_partner`, review off, occasional probes.
  - **Guided lab:** `mentor`, review off, frequent probes.
  - **Assessment lab:** `mentor`, **review on**, probes on every student.
  - Live grid: name, variant, mode, last activity, probe count. Click to watch any transcript live.

**Say:** *"You pick a mode profile per lab based on where students are pedagogically. Everything — transcripts, probe scores, chosen answer-levels — lands in one SQLite DB you can query after class."*
**(If behind schedule, compress this to 30 sec — read the three presets and move on.)**

---

### Slide 11 — Under the hood: privacy, agents & auto-grading (10:00–11:00)
**On slide:** Three compact panels.
- **Agents (CrewAI on Gemini):** structured-output agents for review drafts, probe suggestions, and grading — Pydantic-validated, no brittle regex scraping.
  - **Auto-grade = deterministic + judgment:** correctness measured deterministically from the *real* run; a **reviewer agent** scores `wise_use` 0–100 — did they use the LLM to *learn* or as a plug-and-play machine? Final grade blends the two.
  - **Privacy:** single provider (Gemini); `sanitize.py` strips names/IDs/emails/paths before anything leaves; every cloud call audit-logged with tokens, latency, and an AES-encrypted raw copy.

**Say:** *"The grade isn't 'did it compile'. A reviewer agent reads the whole session — question quality, hint reliance, probe performance — and scores whether the student genuinely learned. Failed probes on a correct submission is the classic plug-and-play tell, and it shows up in the grade."*

---

### Slide 12 — Where this sits & what's next (11:00–11:40)
**On slide:** Status + roadmap.
- **Status:** working research platform, in use for Intro-to-OS at JCE; ships with a ready demo exercise (`ex3-mcalc`, 8 variants) — zero-config to run.
  - **Roadmap:** adaptive scaffolding (auto-pick answer-level from probe history) · multi-exercise sessions · cross-session per-student memory · Docker one-stack packaging for other departments.

**Say:** *"This is a research platform, not a product — it's how our department is exploring one question: what does responsible LLM-mediated CS instruction actually look like in practice?"*

---

### Slide 13 — Close (11:40–12:00)
**On slide:** The four pillars restated + repo/contact.
**Say:** *"Instructor in the loop. Variants that make sharing pointless. Probes that assess understanding, not output. Privacy by default. That's how we let students use AI without letting AI do the learning for them. Happy to take questions."*

---

## Delivery notes & contingencies

- **Cut list (if running long, in order):** Slide 10 detail → Slide 5 IDE-plugin aside → Slide 11 audit-log detail. Never cut Slides 6–8.
  - **If you have a live demo (add ~90s, drop 2 slides):** best moment is after Slide 8 — flip review mode on live, ask a question as a student, pick a nudge from the queue, show it streaming back. High-impact, low-risk.
  - **Anticipated Q&A:**
    - *"Doesn't the local model just leak answers anyway?"* → tutor agent hard-blocks full solutions at every level; variants make a leaked answer non-transferable.
    - *"Privacy with a cloud LLM?"* → PII sanitizer + audit log + single-provider consent posture; student chat stays scoped, agent input is scrubbed.
    - *"Grading fairness?"* → correctness is deterministic; the LLM only scores *process*, and the instructor can override every auto-grade.
    - *"Scalability to other courses?"* → exercises are just YAML; roadmap includes Docker packaging.
  - **The one sentence to land:** *"Let students use AI without letting AI do the learning for them."*

## Suggested visuals to capture before the talk
1. Instructor dashboard student grid (Slide 1 & 10).
   2. Chainlit briefing bubble + a CLion plugin tool window side by side (Slide 5).
   3. The review queue with three answer variants (Slide 8).
   4. Two variant YAML snippets side by side (Slide 9).
   5. An audit-log row / grade breakdown (Slide 11).
