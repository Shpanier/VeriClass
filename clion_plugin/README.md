# OS Lab — CLion Student Plugin

A JetBrains/CLion plugin that is an alternative **student client** for the OS Lab
platform. It does everything the Chainlit web app does — log in, read the
exercise briefing, chat with the locally-hosted tutor, answer instructor
comprehension probes — but inside the IDE the student already uses to write C.

It talks to the **same FastAPI backend** as the Chainlit app, over the same six
endpoints. **No backend changes are required** beyond the one small endpoint that
exposes the behavior switch (`GET /api/client-config`), already included.

---

## Two behaviors, chosen by the backend

Which behavior the plugin runs is **not** a plugin setting — it's owned by the
backend's `.env` so the instructor controls every student from one place. The
plugin fetches `GET /api/client-config` at login and obeys it.

| `.env` value          | Behavior |
|-----------------------|----------|
| `STUDENT_CLIENT_MODE=chat` | **Faithful chat port.** Login → briefing bubble → streaming chat → welcome-suggestion chips → probe prompts + auto-grade. Mirrors Chainlit 1:1, just in a tool window. |
| `STUDENT_CLIENT_MODE=ide`  | **IDE-native.** Everything in `chat`, **plus** it scaffolds the student's assigned variant as a starter C file (`SCAFFOLD_FILENAME`, default `mcalc.c`) into the open project and shows the variant's required test inputs as a checklist. |

If the backend is older and lacks the endpoint, the plugin falls back to `chat`.

---

## What the student sees

```
CLion
├── Editor: mcalc.c            (ide mode only — scaffolded for their variant)
└── Tool window "OS Lab" (right)
    ├── 👤 Yossi · variant V-A3 · mode mentor · client ide
    ├── 📘 Briefing: title, brief, variant params, tests, mode   ── top pane
    ├── Tests to pass:  ☐ (10-2)*5 → 40   ☐ 501+0 → out of range  (ide only)
    ├── [suggestion chip] [suggestion chip] [suggestion chip]
    ├──────────────────────────── draggable divider ───────────
    └── Chat transcript (streaming)            ── bottom pane
        You
        How do I parse precedence?
        Tutor
        Let's think about it together…
        ____________________________________  [Send]
```

A comprehension probe pops up as a modal input the moment the instructor sends
one; the auto-grade is shown right after the student answers.

---

## Build & run

**Requirements:** JDK 21 (CLion 2024.2 runs on JBR 21) and Gradle 8.5+ (only to
bootstrap the wrapper — after that the wrapper is self-contained).

```bash
cd clion_plugin

# One-time: generate the Gradle wrapper jar (this repo ships the scripts +
# config but not the binary jar). Skip if you open the folder in IntelliJ IDEA,
# which generates it for you.
gradle wrapper --gradle-version 8.10.2

# Launch a sandbox CLion with the plugin loaded:
./gradlew runIde

# Or build an installable zip (build/distributions/oslab-clion-plugin-*.zip):
./gradlew buildPlugin
```

Install the zip into a real CLion via **Settings → Plugins → ⚙ → Install Plugin
from Disk…**

`runIde` downloads the CLion build named in `gradle.properties`
(`clionVersion`); the first run is large. Override it without editing files:

```bash
./gradlew runIde -PclionVersion=2024.3.5
```

---

## Configure the connection

**Settings → Tools → OS Lab:**

- **Backend URL** — default `http://127.0.0.1:8000`. Point it at wherever the
  FastAPI backend runs.
- **Dev auto-login code** — optional. If set, the tool window logs in
  automatically with that code (the plugin-side equivalent of the Chainlit
  `DEV_AUTO_LOGIN_CODE`). Leave blank in class.

Open the tool window from the right edge ("OS Lab") and log in with a course
code (e.g. one printed by `scripts/add_students.py`).

---

## How it maps to the backend

| Step | Backend call |
|------|--------------|
| Log in | `POST /api/login` `{code}` → `{token}` |
| Start/resume session | `POST /api/sessions` (Bearer) → `{session_id, variant, mode}` |
| Load exercise | `GET /api/exercises/active?variant=…` |
| Pick behavior | `GET /api/client-config` → `{mode, scaffold_filename, poll_interval_ms}` |
| Chat | `POST /api/ask` (Bearer, streamed `text/plain`) |
| Probes | `GET /api/probes/pending/{session}` every 2 s; `POST /api/probes/answer` |

Streaming, review mode ("your teacher is reviewing…"), persona modes, variant
assignment, and probe auto-grading all work exactly as with Chainlit — they live
in the backend, which is untouched.

---

## Source layout

```
clion_plugin/
  build.gradle.kts, settings.gradle.kts, gradle.properties
  src/main/resources/META-INF/plugin.xml
  src/main/kotlin/edu/jce/oslab/
    api/        Dtos.kt, OsLabApiClient.kt        # HTTP + streaming + JSON
    settings/   OsLabSettings.kt, OsLabSettingsConfigurable.kt
    ui/         OsLabToolWindowFactory.kt, OsLabPanel.kt, LoginPanel.kt,
                ChatPanel.kt, BriefingPanel.kt, TestChecklistPanel.kt,
                ScrollableColumn.kt
    probe/      ProbePoller.kt                     # 2 s poll + modal + grade
    ide/        ExerciseScaffolder.kt              # ide mode: write/open mcalc.c
    util/       Format.kt, MarkdownLite.kt
```
