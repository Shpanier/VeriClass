# VeriClass

> English · [עברית](README.he.md)

**An AI tutor for programming labs that the lecturer controls.** Students work
through a lab in a web chat with an AI tutor that guides rather than hands out
answers. The lecturer watches every conversation live, can hold questions and
choose or rewrite each answer before it reaches the student, keeps the class on
the same step, and asks students short questions to check they understand.

It runs on the lecturer's own computer (Mac, Windows or Linux). Students need
only a browser and a link.

| The lecturer | The students |
|---|---|
| A dashboard in the browser: who is connected, every chat, a queue of questions with ready-made answers to choose from, class pacing, courses and students, exercises | A chat in the browser: sign in, the lab one step at a time, an AI tutor, questions from the lecturer. Hebrew or English |

---

## Install

You need about 1.5 GB of disk space and an internet connection. Nothing else:
the first start installs Python and everything VeriClass needs into its own
folder.

**macOS or Linux.** In the Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/Shpanier/VeriClass/main/install.sh | bash
```

**Windows.** In PowerShell:

```powershell
irm https://raw.githubusercontent.com/Shpanier/VeriClass/main/install.ps1 | iex
```

This puts VeriClass in a `VeriClass` folder in your home folder and starts it.
The first start downloads about 350 MB and takes a few minutes; later starts
take seconds. The dashboard opens in your browser.

> Prefer to download it yourself? Download the ZIP from GitHub (*Code → Download
> ZIP*), unzip it anywhere, and start it as below.

## Start

| | |
|---|---|
| **macOS** | Double-click `start.command` in the VeriClass folder. (The first time: right-click it → *Open* → *Open*.) |
| **Windows** | Double-click `start.bat`. |
| **Linux** (or any terminal) | `./start.sh` |

A window opens and stays open while VeriClass runs: **keep it open during the
class**, and close it (or press Ctrl+C) to stop. On macOS and Windows the
computer won't go to sleep while it runs. The dashboard is at
**http://localhost:8010**.

## First run: two steps in the browser

1. **Create your account**: your name, a username and a password. (This can
   only be done on the computer that runs VeriClass.)
2. **Connect the AI tutor**: choose a provider and paste an API key from your
   account there.

   - **Anthropic** (recommended: one key covers every feature):
     <https://console.anthropic.com/settings/keys>
   - **Google Gemini**: <https://aistudio.google.com/apikey>

   The key is checked with the provider before it is saved, and it is stored
   only on your computer, in the file `.env` in the VeriClass folder. You pay the
   provider for what your class uses. You can change it any time in
   **Settings** (the status button at the top of the dashboard).

The dashboard then shows a short checklist for your first class.

## Your first class

1. **Add your students.** *Courses & students → Import students*: a CSV file
   (a Moodle participants export or a list saved from Excel, in English or
   Hebrew), or rows pasted from Excel. You get back a file with each student's
   **username** and **password** to hand out. Until you set one, a student's
   password is their username. A student who joins later: *Add a student*.
2. **Create a course** and tick the exercises its students may open (three
   sample exercises are included).
3. **Share with students** (the button at the top): one click creates a public
   link and a QR code. Students open it in any browser and sign in. The link
   uses Cloudflare's free tunnel; the first time, the dashboard downloads it
   for you (about 40 MB, no account needed). The address changes each time you
   create it, so share it at the start of each class.
4. **Watch the class** on *Live class*: each student's card, their chat, and,
   with **review mode** on, every question waiting for your answer.

Want a link that never changes? See [Sharing with students](docs/GUIDE.md#sharing-with-students).

## Add an exercise

An exercise is a **package**: a folder with a few text files.

```
my-lab/
  exercise.yaml   what students and the tutor see: the brief, the steps
  teacher.yaml    only for you: expected answers and output checks, quiz questions
  faq.yaml        optional: common questions with ready answers
  files/          optional: what students download
```

Zip the folder and drop it on the **Exercises** tab. The upload is checked
first and tells you what to fix. Then offer it in a course (*Courses &
students*). To start, copy the sample lab in [`examples/first-lab`](examples/first-lab)
and read [examples/README.md](examples/README.md). Simple exercises can also be
written directly in the dashboard (*Exercises → New exercise*).

## Update, back up, move

- **Update**: run the install line again (or download the new ZIP over the old
  folder). Your settings, database and exercises are kept.
- **Back up or move to another computer**: copy three things from the
  VeriClass folder: `.env` (settings and API key), `vericlass.db` (accounts,
  courses and every conversation) and `data/` (your exercises). *Settings*
  shows where they are.

## Trouble?

| What you see | What to do |
|---|---|
| "Port 8010 is used by another program" | Start on another port: `./start.sh --port 8020` (Windows: `start.bat --port 8020`). |
| Students can't open the link | Check that the window running VeriClass is still open and the computer is awake, then *Share with students* again. |
| "The tutor can't answer right now" in the chat | The dashboard's status button says why (no key, a refused key, a spending limit). |
| Students on the same Wi-Fi only, no internet link | Start with `--lan` and give them the address *Share with students* shows under "Same Wi-Fi". |
| Forgot your password | In a terminal in the VeriClass folder: `uv run python scripts/set_password.py <username>` |

## More

- [Lecturer's guide](docs/GUIDE.md): review mode, class pacing, questions to
  students, the question bank, courses and meetings, privacy.
- [Writing exercises](examples/README.md): the package format.
- [Development](docs/DEVELOPMENT.md): running from source, tests, the
  dashboard's design system, the MCP tools for writing exercises with a coding
  agent.
- **IDE plugin.** A PyCharm plugin with the same chat inside the IDE, an exam
  mode and a monitored terminal lives on the
  [`pycharm-plugin`](https://github.com/Shpanier/VeriClass/tree/pycharm-plugin) branch.

## License and contact

Code: [MIT](LICENSE). Educational materials (exercises, briefs, documentation):
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). If you use VeriClass
in teaching or research, please cite it ([CITATION.cff](CITATION.cff)) and let
me know how it went.

Built at the Software Engineering Seminar, Azrieli College of Engineering
Jerusalem (JCE). Questions, ideas, collaboration: **shpanier@gmail.com**
