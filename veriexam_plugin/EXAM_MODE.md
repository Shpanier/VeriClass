# VeriExam — Exam / Proctor Mode (instructor guide)

Exam mode turns the CLion / PyCharm plugin into a lightweight proctored client:
it opens the IDE in **full screen**, allows only **the editor, the VeriExam chat
and the VeriExam Terminal**, and **reports to your dashboard the moment a student
does anything else**: leaves the IDE (minimizes, switches app, exits full
screen), opens another panel or window, or pastes text from outside. Each report
has the student's name, the time, and how it happened (the shortcut or click). You build a small
package once and hand the **same ZIP** to every student; each logs in with their
own code.

> **What it is / isn't.** This is *detect‑and‑report* proctoring, not an OS‑level
> kiosk lock. A determined student can still alt‑tab — but every time they do, it
> is recorded, they get a red warning, and you see it live. No admin rights or
> native code are involved, so it works the same on macOS and Windows.

---

## How it works

```
Student's CLion (exam client)                 Your machine
┌───────────────────────────┐                 ┌────────────────────────────┐
│ Plugin: full screen +      │  POST           │ FastAPI backend            │
│ window focus/minimize      │ ───────────────▶│  /api/proctor/event        │
│ listeners (ExamGuard)      │  /heartbeat     │  → proctor_events table    │
│ • warns the student        │                 │  → /api/students (away,    │
│ • re-asserts full screen   │                 │     focus_alerts)          │
└───────────────────────────┘                 └─────────────┬──────────────┘
                                                            │ polled every 3s
                                                            ▼
                                              ┌────────────────────────────┐
                                              │ React dashboard            │
                                              │ • red banner + alarm sound │
                                              │ • "OUTSIDE IDE" cards      │
                                              │ • per-student proctor log  │
                                              └────────────────────────────┘
```

Only `oppositeWindow == null` window events count as "left the IDE", so the
plugin's *own* dialogs (probes, settings, completion popups) never raise false
alarms.

---

## 1. Build the student package (once)

On a machine with **JDK 21**:

```bash
cd veriexam_plugin
./packaging/make_exam_package.sh --backend-url http://<your-LAN-ip>:8000
```

Use the teacher machine's **LAN IP**, not `127.0.0.1` (that only works on your
own computer). Output:

- `dist/VeriExamInstaller/` — the package folder
- `dist/VeriExamInstaller.zip` — **send this to students**

The ZIP contains: the built plugin, `install-macos.command`,
`install-windows.bat` (+`.ps1`), `exam.conf` (your backend URL, pre‑stamped),
and bilingual `README-STUDENT` files. To change the backend later, edit
`dist/VeriExamInstaller/exam.conf` and re‑zip, or re‑run with a new `--backend-url`.

First build downloads the CLion SDK and is large; later builds are cached.

## 2. Turn exam mode on (backend `.env`)

```ini
STUDENT_CLIENT_MODE=ide
EXAM_MODE=true        # optional — defaults ON whenever mode is "ide"
FULLSCREEN=true       # optional — defaults to whatever EXAM_MODE is
```

Restart the backend. `GET /api/client-config` now returns `exam_mode: true`, and
every exam client picks it up at login. To end the exam for everyone, set
`EXAM_MODE=false` (or `STUDENT_CLIENT_MODE=chat`) and restart.

## 3. Run the exam

1. Start the backend + dashboard (`scripts/dev_up.sh`).
2. Students unzip the package and double‑click the installer for their OS, then
   log in with their personal code (from `scripts/add_students.py`).
3. Watch the dashboard:
   - A **red banner** with an **alarm sound** appears when anyone leaves CLion.
   - That student's card turns red and pulses with a **🔴 OUTSIDE IDE** badge;
     after they return it shows **⚠ left N×**.
   - Click **🎥 Alerts / Proctor log** on a card for that student's full trail
     (every leave/return with timestamps and how long they were away).

---

## What the student experiences

- CLion opens in full screen with the **VeriExam** panel already in front.
- They log in and work: write C, ask the tutor, answer your comprehension probes.
- If they minimize / switch app / leave full screen: a **sticky red warning**
  appears ("Exam mode — stay in CLion … reported to your instructor"), CLion is
  brought back and re‑maximized when they return, and the leave is logged.

## Only the editor, the chat and the terminal

During the exam every other panel (tool window) is hidden and its side-bar
button removed: Project, Git, Python Console, Run, Problems, the IDE's own
Terminal, other plugins' panels. If one is opened anyway (a shortcut, the View
menu, or the IDE itself, e.g. when running code) it is closed again at once,
the student is warned, and you get `tool_window_opened` with how:
`Project — “Project”, keyboard ⌘1`. To allow a panel, list its id in `.env`:

```ini
EXAM_ALLOWED_TOOL_WINDOWS=Run      # comma-separated tool window ids
```

Other windows are reported too (`other_window_opened`, and
`other_window_closed` when it's closed): dialogs such as Settings, another
project window, and the search popups (Search Everywhere, Go to File, Find in
Files, Recent Files, Switcher). Dialogs can't be closed by the plugin, so the
student's card stays orange until they close it. The plugin's own dialogs
(probes, export) don't count.

Every editor tab opened is logged as `file_opened` (information, not an alert),
marked "outside the project" when it is.

## Live status on the dashboard

The plugin sends a snapshot every 10 seconds (`HEARTBEAT_MS` in `.env`) and on
every change: is the IDE focused, is it full screen, which panels, windows and
editor tabs are open, and how many reports it hasn't managed to send. Each
card shows one state:

| badge | meaning |
|---|---|
| 🟢 In the IDE · full screen | all fine |
| 🔴 OUTSIDE THE IDE | another app is in front, or the IDE is minimized |
| 🟠 OTHER WINDOW OPEN | a dialog, another project, or a panel that isn't allowed (named under the badge) |
| 🟡 NOT FULL SCREEN | in the IDE but out of full screen |
| ⚫ NO SIGNAL | no status for 45 s: IDE closed or crashed, laptop asleep, or no network |

Under the badge: the open tabs (the active one in bold), the last alert with how
and when, and ⏳ when reports are waiting on the student's side. Any card that
isn't green also shows in the red banner, and the alarm sounds when a state
turns bad or a new alert arrives.

## Pastes

Every paste into the editor, the VeriExam Terminal or the chat box is logged
with its full text (`pastes` table; the **Pastes** section of the proctor log)
and where the text came from:

| source | meaning | alert? |
|---|---|---|
| from outside the IDE | the clipboard changed while the student was in another app, was already on it when the exam started, or came from something the IDE didn't see | yes (`paste_external`) |
| copied inside the IDE | copied or cut in the IDE during the exam | no (`paste_internal`) |
| copied from the tutor | a code block's **Copy** button in the VeriExam chat | no (`paste_internal`) |

Text is matched with whitespace ignored, because the editor re-indents pastes.
This is a strong hint, not proof: you always see the text itself. Not caught:
text dragged and dropped into the editor, and text typed in by another program.

## The student's own copy ("Export my log")

The plugin writes everything it reports, plus the chat, to a journal on the
student's computer (`~/.veriexam/trace/<session>.jsonl`). The **💾 Export my
log** button in the VeriExam panel saves it as a CSV (opens in Excel; Hebrew
works): time, kind, where, the command or text, full output, exit code, and
whether it reached the server. When the server can't be reached, the panel
shows **⏳ n not sent yet**; if that doesn't clear, the student exports the log
and hands in the file.

Each row is signed with a key the server gives that session (HMAC-SHA256,
chained row to row), so you can check the file wasn't edited:

1. On the dashboard, click **🔏 Verify a student's log** and choose the CSV
   exactly as the student sent it (opening and saving it in Excel changes it).
2. You see whether it is **untouched**. If not, you see the first row that was
   changed, removed or reordered, or that the file was cut short.
3. Rows that never reached the server are listed; **Import** adds them. They're
   marked **from the student's export** wherever they show.

This makes edits evident, not impossible: the key is in the student's IDE
while the session runs.

## Event kinds (in the proctor log)

| kind | meaning |
|---|---|
| `exam_started` | exam client armed (not a violation) |
| `focus_lost` | switched to another application |
| `minimized` | minimized CLion |
| `fullscreen_exited` | left full screen |
| `focus_regained` / `window_restored` | returned to CLion |
| `blocked_command` | entered a command the exercise doesn't allow in the VeriExam Terminal (it didn't run) |
| `fullscreen_restored` | back in full screen |
| `stock_terminal_opened` | tried to open the IDE's own Terminal (hidden during the exam) |
| `tool_window_opened` | opened another panel; it was closed again. Detail: which, and how |
| `other_window_opened` / `other_window_closed` | a dialog, another project window, or a search popup |
| `file_opened` | opened an editor tab (not an alert) |
| `paste_external` / `paste_internal` | pasted text from outside / from inside the IDE or the tutor |

`focus_alerts` on the dashboard counts the three leave kinds. The two terminal
kinds are counted as `terminal_alerts` (see [TERMINAL.md](TERMINAL.md));
`tool_window_opened`, `other_window_opened` and `paste_external` as `ide_alerts`.
Times are when it happened on the student's machine; a report that waited in
the plugin's queue shows **arrived late**.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Students don't appear on the dashboard | Wrong `BACKEND_URL` in `exam.conf` (used `127.0.0.1`?), or firewall blocking port 8000 on the LAN. |
| Cards never turn red | `EXAM_MODE` is off, or students aren't on the exam client (check `STUDENT_CLIENT_MODE=ide`). |
| A card says NO SIGNAL | The student's IDE stopped reporting: closed, asleep, or offline. Reports made meanwhile arrive when it reconnects, or are in their export. |
| Students need a panel (e.g. Run) | Add it to `EXAM_ALLOWED_TOOL_WINDOWS` and restart the backend; students log in again. |
| No alarm sound | The browser needs one click on the dashboard first (audio unlock); the visual banner still works. |
| Full screen didn't engage | Some Linux WMs lack the platform full‑screen API; reporting/warnings still work. (macOS/Windows are fine.) |
| Installer can't find CLion config | The student must install **and launch CLion once** before running the installer. |
