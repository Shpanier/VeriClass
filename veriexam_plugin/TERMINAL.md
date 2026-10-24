# VeriExam Terminal (instructor guide)

The plugin adds a **VeriExam Terminal** tool window at the bottom of the IDE,
where Terminal and Run normally sit. The tutor chat stays on the right. Students
get a normal-feeling shell: prompt, history (↑/↓), Tab completion, Ctrl-C,
pipes, redirection, `&&`/`||`/`;`, `$(…)`, variables, `cd`, and their own scripts.

Every line is **checked before it runs** and **logged for you**:

- **Allowed:** it runs. You see the command, its exit code, and its **full output**
  (errors included: stdout and stderr share the terminal), up to about 4 MB per command.
- **Refused:** it never runs. The student sees a red message, and you get a live
  alert on the dashboard (alarm sound, red banner, 🚫 on the card).

This is detect-and-report, like exam mode, not a sandbox. See [Limits](#limits).

## How a line is checked

The plugin splits the line the way a shell would and checks **every program it
would start**, not just the first word:

| Line | Result |
|---|---|
| `awk '$9==500' access.log \| sort \| uniq -c` | allowed (awk, sort, uniq) |
| `cat x \| sh` · `echo hi && powershell` | refused: starts another shell |
| `echo "$(bash)"` · `diff <(ls) <(python3 x.py)` | refused: command inside a substitution |
| `X=powersh; ${X}ell` · `/bin/ba*` | refused: program name built at run time |
| `find . -exec sh -c id \;` · `xargs python3` | refused: the wrapped program is checked |
| `awk 'BEGIN{system("sh")}'` | refused: awk starting programs |
| `git -c core.pager=sh log` · `git config alias.x '!sh'` | refused: git settings that run commands |
| `./count.sh` · `sh count.sh` | allowed if every line of the script is allowed |
| `echo 'unclosed` | syntax error: not run, logged, **not** an alert |

Always allowed: shell builtins (`cd`, `pwd`, `echo`, `export`, `test`, `read`, …).
Never allowed: shells (`sh`, `bash`, `powershell`, `cmd`, `wsl`) and `eval`/`exec`.

## Choosing what an exercise allows

Add an optional `terminal:` block to the exercise YAML (`config/exercises/*.yaml`):

```yaml
terminal:
  allow: [ls, cat, grep, awk, sort, uniq, head, tail, wc, git]  # replaces the default list
  allow_extra: [python3]   # added on top of `allow`, or of the default list
  scripts: true            # students may run their own .sh scripts (checked line by line)
```

Without the block, the default list in `backend/terminal.py` applies: files,
text processing (`grep awk sed sort uniq cut tr wc xargs …`), archives and `git`.
Interpreters, network tools, editors and `sudo` are deliberately left out.

## Windows and Linux get the same tools

The plugin ships **BusyBox**: busybox-w32 on Windows (x64 and ARM64) and the
official static build on Linux (x64). `ls`, `grep`, `awk`, `sort` and the rest
are the same code on both, so the same answers are correct everywhere. `git`
comes from the student's own Git install. `sort` order is pinned with `LC_COLLATE=C`.

Fetch BusyBox once before building (checksums are pinned in the script):

```bash
cd veriexam_plugin
./packaging/fetch_busybox.sh
./gradlew :pycharm:buildPlugin     # or packaging/make_exam_package.sh
```

Without it, the terminal falls back to Git Bash on Windows and `/bin/bash` on
Linux. macOS always uses `/bin/bash`: BusyBox has no macOS build, so Mac tools
(BSD `sed`, `date`) differ slightly. To try a specific shell, set
`VERIEXAM_TERMINAL_SHELL=/path/to/busybox` before starting the IDE.

## Same results on every OS

Students run the same exercise on Windows, macOS and Linux, and the terminal
uses different tools on each (BusyBox, or bash with the macOS tools). Three
things keep the results the same:

**1. Check every exercise before class.** `scripts/check_exercise_os.py` runs
an exercise's commands on this machine and in BusyBox (Docker), and shows every
command whose output differs:

```bash
python scripts/check_exercise_os.py ../VeriExPrivateData/exercises/lab1-linux-git
```

It runs, in order, every command in the steps' code blocks, then each step's
teacher-only `os_check:` lines. Put the reference solutions of a step's tasks
there, so the check covers them too (students never see them):

```yaml
steps:
  - title: "Searching with grep"
    text: |
      ...
    expected: |
      ...
    os_check:
      - "grep -c 'ERROR' app.log"
```

It compares three runs: `local` (on a Mac: the macOS tools), `busybox` (the
Windows and Linux tools) and `win-030` (BusyBox as plugin 0.3.0 ran it on
Windows, see below). Spaces before numbers, Git hashes, dates and temp paths are
ignored. Exit code 1 when something differs.

**2. The same rules run on every load.** `backend/portability.py` checks every
command of every exercise when it loads. "error" means the command breaks on one
OS; "note" means only the output text differs. The teacher sees them in
`GET /api/exercises/{id}` (`os_warnings`), and the Exercises tab shows a badge
with the number of errors. The rules:

| Rule | Level | What differs | Write instead |
|---|---|---|---|
| `\` in a command | error | plugin 0.3.0 on Windows turns it into `/` | `[.]` or `[0-9.]*` for `\.`; in awk `printf "%c"` with 10 (newline) or 34 (`"`) |
| `sed -i` | error | macOS needs `sed -i ''` | write a new file with `>` |
| `grep -P` | error | missing in BusyBox and macOS | `grep -E` |
| `date -d` / `date -v` | error | GNU/BusyBox vs macOS options | avoid |
| `stat -c` / `stat -f` | error | BusyBox vs macOS options | `ls -l`, `wc -c` |
| `head -n -1` | error | GNU only | combine `head` and `tail` |
| gawk functions (`strftime`, `gensub`, …) | error | missing in BusyBox and macOS awk | plain awk |
| `find -printf` | error | GNU only | avoid |
| `tac`, `md5sum`, `sha256sum` | error | may be missing on macOS | avoid |
| `ls -l` | note | owner, group and date format | check names or sizes |
| `uniq -c`, `wc` | note | spaces before the number | compare the numbers |
| `git add`, `git commit -a` | note | Git for Windows may print `LF will be replaced by CRLF` | harmless |

**3. The dashboard shows each line's OS.** From plugin 0.3.1 every terminal line
carries the student's OS and the shell that ran it (`client_os`, `shell` in
`terminal_commands`); the terminal log shows the OS next to the time, and the
shell on hover.

### Backslashes on Windows (fixed in 0.3.1)

Up to plugin 0.3.0, every `\` in a command became `/` on Windows: the line
reached BusyBox in the `VE_CMD` environment variable, and busybox-w32 converts
backslashes in it. The dashboard log showed the original line, so the change was
easy to miss. Seen in class on 2026-10-22 (lab1-linux-git, most students on
Windows):

| Command contains | macOS / Linux | Windows, plugin 0.3.0 |
|---|---|---|
| `\"` inside an awk string | works | `awk: cmd. line:1: Division by zero` (the string ends early) |
| `\n` in awk `printf` | works | runs, but prints `/n`: the whole output is one line |
| `\.` in `sed` or `grep` | works | `sed: bad option in substitution expression`, or wrong matches |

From 0.3.1 the line goes through a file (`VE_CMD_FILE`, see `ShellRunner.kt`
and `terminal-runner.sh`), so backslashes arrive unchanged. While students
may still have 0.3.0 installed, keep exercise commands free of `\`: the check
above reports it as an error.

## Exam mode

With `EXAM_MODE` on, the IDE's own **Terminal** tool window is hidden, so the
VeriExam Terminal is the only one. If a student brings it back (Alt+F12,
"Open in Terminal"), it's hidden again, they get a warning, and you get a
`stock_terminal_opened` alert saying how it was opened (the shortcut or click).
Outside exam mode the IDE's Terminal stays available next to the VeriExam one.
Pastes into the terminal are logged too (see [EXAM_MODE.md](EXAM_MODE.md#pastes)).

## Nothing is lost when the network drops

Each line is sent with its full output, split into pieces of 16,000 characters.
Everything goes through a queue in the plugin that keeps retrying while the
server can't be reached, so a dropped Wi-Fi or tunnel only delays reports. Each
report carries an id, so a retry is never stored twice, and the time it happened
on the student's machine (late arrivals show **arrived late** on the dashboard).
The plugin also keeps its own signed copy, which the student can export; see
[EXAM_MODE.md](EXAM_MODE.md#the-students-own-copy-export-my-log).

## What you see on the dashboard

- **⌨ Terminal (n)** on a student's card: their full log, newest first, with exit
  codes and output. The row shows the end of the output; **Full output** loads
  all of it. Tick "Refused only" to see just the alerts.
- **🚫 n blocked** chip and the red banner: refused commands count as alerts,
  but not as "outside the IDE".
- The **proctor log** lists each refused line (`blocked_command`) with the reason.

## Limits

- **Not a sandbox.** A program that is allowed can still start other programs
  in ways the checker can't see. Examples: `python3` (if you allow it), or a git hook
  the student writes into `.git/hooks`. Common patterns are caught, and every
  line typed is logged anyway, so attempts stay visible.
- **One fresh shell per line.** `cd` and variables carry over; shell functions,
  aliases and `set -o` options don't.
- **Typing while a command runs goes to that command** (so `read` and prompts
  work). Lines pasted together run one after another.
- **Editors and pagers are off:** `PAGER`/`GIT_PAGER` are `cat`, and
  `git commit` needs `-m "message"`. Full-screen programs like `vi`, `less` and `top`
  haven't been tested in this terminal yet.
- **Not yet tried on real Windows and Linux machines.** Tests cover the checker,
  the line editor and the IDE's terminal widget, running against macOS bash.
