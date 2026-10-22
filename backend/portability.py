"""Same terminal commands, every OS: find exercise commands that behave
differently on Windows and macOS.

The VeriExam terminal runs BusyBox on Windows and Linux, and /bin/bash with the
BSD tools on macOS (veriexam_plugin/TERMINAL.md). A command that works on the
teacher's Mac can fail, or print something else, on a student's Windows laptop.

Two levels:
  - lint_exercise(): static rules, run on every load (warnings, never blocking)
    and shown to the teacher. Cheap, no shell needed.
  - scripts/check_exercise_os.py: runs the commands on macOS and in BusyBox and
    compares the output. Uses commands_of() from here.

An exercise may add, per step, an `os_check:` list of extra commands (usually
the reference solutions of the step's tasks) so the check covers them too.
Those lines are teacher-only: students never see them.
"""
import re
from dataclasses import dataclass
from typing import Any

# Shell builtins: always allowed by the plugin (CommandChecker.SAFE_BUILTINS).
BUILTINS = {
    "cd", "pwd", "echo", "printf", "export", "unset", "true", "false", "test", "[",
    "read", "set", "shift", "type", "alias", "unalias", "wait", "umask", "exit",
}

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_FIRST_WORD = re.compile(r"^\s*([A-Za-z0-9_.\-\[]+)")


@dataclass(frozen=True)
class Rule:
    code: str
    level: str          # "error": breaks on one OS. "note": output text differs.
    pattern: re.Pattern
    message: str


# Each rule: what differs, and what to write instead.
RULES = [
    Rule("backslash", "error", re.compile(r"\\"),
         "contains \\ — plugin 0.3.0 on Windows turns every \\ into / (awk \\n and \\\", sed \\. "
         "break). Use [.] or [0-9.]* instead of \\., and printf \"%c\" with 10 or 34 in awk."),
    Rule("sed-i", "error", re.compile(r"\bsed\s+(-[a-zA-Z]*i\b|--in-place)"),
         "sed -i: macOS needs a suffix argument (sed -i ''), BusyBox does not. Write to a new "
         "file with > instead."),
    Rule("grep-P", "error", re.compile(r"\bgrep\s+(-[a-zA-Z]*P|--perl)"),
         "grep -P (Perl regex) is missing in BusyBox and macOS. Use grep -E."),
    Rule("date-gnu", "error", re.compile(r"\bdate\b[^|;&]*\s(-d|--date|-v)\b"),
         "date -d (GNU/BusyBox) and date -v (macOS) are different options."),
    Rule("stat-format", "error", re.compile(r"\bstat\s+(-c|-f|--format)\b"),
         "stat -c (BusyBox) and stat -f (macOS) are different. Use ls -l or wc -c."),
    Rule("head-negative", "error", re.compile(r"\b(head|tail)\s+-n\s*-\d"),
         "a negative line count (head -n -1) is GNU only. Combine head and tail instead."),
    Rule("gawk-only", "error", re.compile(r"\b(gensub|strftime|systime|asort|asorti)\s*\("),
         "gawk-only awk function: missing in BusyBox and macOS awk."),
    Rule("find-printf", "error", re.compile(r"\bfind\b[^|;&]*-printf\b"),
         "find -printf is GNU only."),
    Rule("mac-missing", "error", re.compile(r"(^|[|;&]\s*)(tac|md5sum|sha1sum|sha256sum)\b"),
         "may be missing on macOS (it has tail -r, md5, shasum)."),
    Rule("ls-long", "note", re.compile(r"\bls\s+-[a-zA-Z]*l"),
         "ls -l shows a different owner, group and date format on each OS: check names or "
         "sizes, not the whole line."),
    Rule("count-padding", "note", re.compile(r"\buniq\s+-[a-zA-Z]*c|\bwc\b"),
         "uniq -c and wc pad numbers with a different number of spaces on each OS: compare "
         "the numbers, not the exact text."),
    Rule("git-crlf", "note", re.compile(r"\bgit\s+(add|commit\s+-[a-zA-Z]*a)"),
         "Git for Windows may print 'LF will be replaced by CRLF' (core.autocrlf). "
         "Harmless; counts and diffs stay the same."),
]


def code_lines(text: str) -> list[str]:
    """Every non-empty line inside ``` fences of a step's text."""
    out = []
    for block in _FENCE.findall(text or ""):
        out.extend(line.rstrip() for line in block.splitlines() if line.strip())
    return out


def is_command(line: str, allow: set[str]) -> bool:
    """A line the student would type: its first word is an allowed program or a
    builtin. Skips sample output and field diagrams shown in code blocks."""
    m = _FIRST_WORD.match(line)
    return bool(m) and (m.group(1).lower() in allow or m.group(1) in BUILTINS)


def commands_of(ex: dict[str, Any], allow: set[str]) -> list[tuple[int, str, str]]:
    """(step number, source, line) for every command, in the order a student runs
    them: each step's code blocks, then its teacher-only `os_check` lines."""
    out = []
    for n, st in enumerate(ex.get("steps") or [], start=1):
        out += [(n, "step", ln) for ln in code_lines(st.get("text", "")) if is_command(ln, allow)]
        out += [(n, "os_check", ln.strip()) for ln in (st.get("os_check") or []) if ln.strip()]
    return out


def lint_line(line: str) -> list[tuple[Rule, str]]:
    return [(r, line) for r in RULES if r.pattern.search(line)]


def lint_exercise(ex: dict[str, Any], allow: set[str]) -> list[dict[str, Any]]:
    """Static warnings for every command of the exercise, one per (rule, step)."""
    seen, out = set(), []
    for n, source, line in commands_of(ex, allow):
        for rule, ln in lint_line(line):
            key = (rule.code, n)
            if key in seen:
                continue
            seen.add(key)
            out.append({"step": n, "source": source, "level": rule.level, "rule": rule.code,
                        "line": ln, "message": rule.message})
    order = {"error": 0, "note": 1}
    return sorted(out, key=lambda w: (order[w["level"]], w["step"]))
