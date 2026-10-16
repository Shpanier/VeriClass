# VeriExam — CLion & PyCharm Student Plugin

A JetBrains plugin that is an alternative **student client** for the VeriExam
platform. It does everything the Chainlit web app does — log in, read the
exercise briefing, chat with the locally-hosted tutor, answer instructor
comprehension probes — but inside the IDE the student already uses to write code
(C in **CLion**, Python in **PyCharm**).

Both IDE plugins are built from **one shared source tree** (`core/`) by two thin
modules (`:clion`, `:pycharm`). The plugin uses only IntelliJ **platform + VFS**
APIs — no C/C++ or Python SDK APIs — so the same code runs in either IDE; the
product name shown to the student and the scaffolded starter language are chosen
at runtime.

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
| `STUDENT_CLIENT_MODE=ide`  | **IDE-native.** Everything in `chat`, **plus** it scaffolds the student's assigned variant as a starter file (`SCAFFOLD_FILENAME`, default `mcalc.c`) into the open project and shows the variant's required test inputs as a checklist. |

The starter language follows the `SCAFFOLD_FILENAME` extension — `.py` yields a
Python starter, `.c`/`.cpp` a C one — falling back to the running IDE (PyCharm ⇒
Python, CLion ⇒ C) when the name is ambiguous. So a Python cohort just sets
`SCAFFOLD_FILENAME=mcalc.py`.

If the backend is older and lacks the endpoint, the plugin falls back to `chat`.

---

## Build & run

**Requirements:** JDK 21 (both IDEs' 2024.2 run on JBR 21) and Gradle 8.5+ (only to
bootstrap the wrapper — after that the wrapper is self-contained).

The build is a Gradle **multi-project**: pick the module with a `:clion` or
`:pycharm` task prefix.

```bash
cd veriexam_plugin

# One-time: generate the Gradle wrapper jar (this repo ships the scripts +
# config but not the binary jar). Skip if you open the folder in IntelliJ IDEA,
# which generates it for you.
gradle wrapper --gradle-version 8.10.2

# Launch a sandbox IDE with the plugin loaded:
./gradlew :clion:runIde          # sandbox CLion
./gradlew :pycharm:runIde        # sandbox PyCharm

# Or build an installable zip:
./gradlew :clion:buildPlugin     # → clion/build/distributions/veriexam-clion-plugin-*.zip
./gradlew :pycharm:buildPlugin   # → pycharm/build/distributions/veriexam-pycharm-plugin-*.zip
```

Install the zip into a real IDE via **Settings → Plugins → ⚙ → Install Plugin
from Disk…**

The plugin id changed to `edu.jce.veriexam.<product>` in 0.2.0, so the IDE treats
it as a new plugin. Anyone with a 0.1.x build installed must uninstall it first
(Settings → Plugins → Installed → Uninstall → Restart), otherwise both register
the same tool window.

`runIde` downloads the IDE build named in `gradle.properties` (`clionVersion` /
`pycharmVersion`); the first run is large. Override it without editing files:

```bash
./gradlew :clion:runIde   -PclionVersion=2024.3.5
./gradlew :pycharm:runIde -PpycharmVersion=2024.3.5
```

---

## Configure the connection

**Settings → Tools → VeriExam:**

- **Backend URL** — default `http://127.0.0.1:8000`. Point it at wherever the
  FastAPI backend runs.
- **Dev auto-login code** — optional per-machine override. If set, the tool
  window logs in automatically with that code. **If left blank, the plugin falls
  back to the backend's `DEV_AUTO_LOGIN_CODE`** (fetched from `/api/client-config`),
  so a whole dev/test class auto-logs in with zero per-machine setup. Both are
  empty in a real exam (clear `DEV_AUTO_LOGIN_CODE` in `.env`), so students log in
  with their own codes.

Open the tool window from the right edge ("VeriExam") and log in with a course
code (e.g. one printed by `scripts/add_students.py`).

---

## Updating an installed plugin

The version is bumped on every build (and is shared by both plugins), so the IDE
treats a reinstall as a real upgrade (one restart, **no uninstall**). On the
**JDK-21 build machine**:

```bash
cd veriexam_plugin
./reinstall.sh                     # CLion: bump version → build → reveal the zip
./reinstall.sh --product pycharm   # PyCharm instead
# then: Settings → Plugins → ⚙ → Install Plugin from Disk… → pick the zip → Restart
```

Just iterating on the code? Skip installing entirely — `./gradlew :clion:runIde`
(or `:pycharm:runIde`) opens a sandbox IDE with the plugin loaded; rebuild = rerun.

---

## Distributing updates over the tunnel (no file passing)

The plugin only builds on a JDK-21 machine, which usually isn't the machine
running the backend. The backend — already exposed via ngrok (see
`deploy/README-NGROK.md`) — doubles as the distribution point: the build machine
**publishes** a zip to it; any machine **pulls + installs** over the same tunnel.

The backend stores a **single** latest zip, so one product is "live" at a time —
publish whichever IDE your current cohort uses.

**1. Build machine — publish:**
```bash
cd veriexam_plugin
./publish.sh                       # CLion: bump → build → upload over the tunnel
./publish.sh --product pycharm     # PyCharm instead
./publish.sh --no-build            # just upload the existing zip for that product
```
Reads the server URL from `deploy/tunnel.conf` (`NGROK_DOMAIN`), logs in with
your teacher code (prompted, or `VERIEXAM_TEACHER_CODE` env), and uploads.

**Teacher login code.** Publishing is teacher-authenticated: `publish.sh` signs in
with a **teacher** login code — a `users` row whose `role='teacher'` (the same code
that signs into the dashboard). It is **not** the `.env` `DEV_AUTO_LOGIN_CODE`,
which is a *student* dev code. Find an existing one, or create a teacher:

```bash
# list existing teacher codes:
sqlite3 veriexam.db "SELECT username, login_code FROM users WHERE role='teacher';"
# or seed a new teacher (prints the code as a table):
python scripts/add_students.py --teachers "Your Name"
```

Then paste it at the `Teacher login code:` prompt, or skip the prompt entirely:

```bash
export VERIEXAM_TEACHER_CODE=XXX-XXXX     # a teacher code from the query above
./publish.sh --product pycharm
```

Treat teacher codes like passwords — anyone with one can publish plugins and act
on any student session. Don't commit real codes to the repo.

**2. Any machine — install / update:**
```bash
scripts/update_plugin.sh                    # newest of any product → matching IDE
scripts/update_clion_plugin.sh              # only the CLion plugin → CLion
scripts/update_pycharm_plugin.sh            # only the PyCharm plugin → PyCharm
```
`update_plugin.sh` reads the product from the published zip and installs into the
matching IDE; the two wrappers pin a product (they just call it with `--product`).

**Student one-liners — the simplest path. Send them the one for their IDE:**
```bash
# newest of any product (installs into whichever IDE they have):
curl -fsSL https://<your-domain>.ngrok-free.dev/api/plugin/install.sh          | bash
# CLion only:
curl -fsSL https://<your-domain>.ngrok-free.dev/api/plugin/install-clion.sh    | bash
# PyCharm only:
curl -fsSL https://<your-domain>.ngrok-free.dev/api/plugin/install-pycharm.sh  | bash
```
Each downloads the installer, pulls the extension from `/api/plugin/latest`, and
drops it into the right IDE. The student just **restarts the IDE**. The installer's
server URL is auto-rewritten to whatever host served it, so the same link keeps
working even if the ngrok domain changes. Because each product is stored
separately, CLion and PyCharm builds can be published and live at the same time.

Backend endpoints behind all this:

| Endpoint | Who | Purpose |
|---|---|---|
| `POST /api/plugin/publish?version=&product=` | teacher | upload a built zip (raw body) |
| `GET /api/plugin/version[?product=]` | public | JSON: what's currently published |
| `GET /api/plugin/latest[?product=]` | public | download the newest zip |
| `GET /api/plugin/install.sh` | public | installer (newest, auto-IDE) |
| `GET /api/plugin/install-clion.sh` | public | installer pinned to CLion |
| `GET /api/plugin/install-pycharm.sh` | public | installer pinned to PyCharm |

Downloads are public so the one-liner needs no token — the tunnel URL is the
only gate. Published zips are stored under `PLUGIN_DIST_DIR` (default
`./plugin_dist`, gitignored).

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
veriexam_plugin/
  settings.gradle.kts        # includes :clion and :pycharm
  gradle.properties          # shared: pluginVersion, clionVersion, pycharmVersion
  core/                      # ONE shared source tree, compiled by both modules
    src/main/kotlin/edu/jce/veriexam/
      api/        Dtos.kt, VeriExamApiClient.kt        # HTTP + streaming + JSON
      settings/   VeriExamSettings.kt, VeriExamSettingsConfigurable.kt
      ui/         VeriExamToolWindowFactory.kt, VeriExamPanel.kt, LoginPanel.kt,
                  ChatPanel.kt, BriefingPanel.kt, TestChecklistPanel.kt,
                  ScrollableColumn.kt
      probe/      ProbePoller.kt                     # 2 s poll + modal + grade
      exam/       ExamGuard.kt, ExamFullScreen.kt, …  # proctor (product-neutral)
      ide/        ExerciseScaffolder.kt, RunReporter.kt, SubmissionCollector.kt
      util/       Format.kt, MarkdownLite.kt
  clion/
    build.gradle.kts                                 # targets CLion
    src/main/resources/META-INF/plugin.xml           # id edu.jce.veriexam.clion
  pycharm/
    build.gradle.kts                                 # targets PyCharm Community
    src/main/resources/META-INF/plugin.xml           # id edu.jce.veriexam.pycharm
  packaging/ publish.sh reinstall.sh                 # all take --product clion|pycharm
```
