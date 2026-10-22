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
