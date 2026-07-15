# VeriExam — Exam / Proctor Mode (instructor guide)

Exam mode turns the CLion plugin into a lightweight proctored client: it opens
CLion in **full screen**, keeps the student inside the IDE + the VeriExam tutor
chat, and **reports to your dashboard the moment a student leaves CLion**
(minimizes, switches to another app, or exits full screen). You build a small
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
cd oslab_plugin
./packaging/make_exam_package.sh --backend-url http://<your-LAN-ip>:8000
```

Use the teacher machine's **LAN IP**, not `127.0.0.1` (that only works on your
own computer). Output:

- `dist/OsLabExam/` — the package folder
- `dist/OsLabExam.zip` — **send this to students**

The ZIP contains: the built plugin, `install-macos.command`,
`install-windows.bat` (+`.ps1`), `exam.conf` (your backend URL, pre‑stamped),
and bilingual `README-STUDENT` files. To change the backend later, edit
`dist/OsLabExam/exam.conf` and re‑zip, or re‑run with a new `--backend-url`.

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

## Event kinds (in the proctor log)

| kind | meaning |
|---|---|
| `exam_started` | exam client armed (not a violation) |
| `focus_lost` | switched to another application |
| `minimized` | minimized CLion |
| `fullscreen_exited` | left full screen |
| `focus_regained` / `window_restored` | returned to CLion |

`focus_alerts` on the dashboard counts the three leave kinds; `away` is true when
the most recent event is a leave not yet followed by a return.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Students don't appear on the dashboard | Wrong `BACKEND_URL` in `exam.conf` (used `127.0.0.1`?), or firewall blocking port 8000 on the LAN. |
| Cards never turn red | `EXAM_MODE` is off, or students aren't on the exam client (check `STUDENT_CLIENT_MODE=ide`). |
| No alarm sound | The browser needs one click on the dashboard first (audio unlock); the visual banner still works. |
| Full screen didn't engage | Some Linux WMs lack the platform full‑screen API; reporting/warnings still work. (macOS/Windows are fine.) |
| Installer can't find CLion config | The student must install **and launch CLion once** before running the installer. |
