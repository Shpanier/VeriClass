"""Rules for the VeriClass terminal (the plugin's checked + logged terminal).

An exercise may carry an optional `terminal:` block:

    terminal:
      allow: [ls, cat, grep, awk, sort, uniq, head, tail, wc, git]  # replaces the default list
      allow_extra: [python3]   # added on top of `allow` (or of the default list)
      scripts: true            # students may run their own .sh scripts (checked line by line)
      blocked_hint: "Install packages in PyCharm's Terminal tab."  # shown under every refusal

Without one, DEFAULT_ALLOW applies, plus PYTHON_EXTRA for a Python exercise
(language: python), so `pip install` works in a Python lab. Shell builtins (cd,
echo, export, test, …) are always allowed; shells (sh, bash, powershell, cmd) and
eval/exec never are — the plugin enforces both regardless of this list.
"""
from typing import Any

# The everyday Linux toolbox for a DevOps lab: files, text processing, git.
# Deliberately absent: interpreters (python, node), network (curl, wget, ssh),
# editors (vi, nano), process control (kill), privilege (sudo).
DEFAULT_ALLOW: tuple[str, ...] = (
    # files and directories
    "ls", "cat", "head", "tail", "less", "more", "mkdir", "rmdir", "cp", "mv", "rm",
    "touch", "chmod", "ln", "find", "du", "df", "file", "stat", "tree",
    "basename", "dirname", "realpath", "readlink",
    # text processing
    "grep", "egrep", "fgrep", "wc", "sort", "uniq", "cut", "tr", "awk", "sed", "tee",
    "diff", "cmp", "comm", "paste", "join", "column", "nl", "rev", "fold", "fmt",
    "xargs", "seq", "expr",
    # archives
    "tar", "gzip", "gunzip", "zcat",
    # system info
    "date", "sleep", "whoami", "hostname", "uname", "env", "ps",
    # version control
    "git",
)

# Added to the default list in a Python exercise without a `terminal:` block. In
# October 2026 six students' `pip install` was refused at the start of a Python lab.
PYTHON_EXTRA: tuple[str, ...] = ("pip", "pip3", "python", "python3", "py")

_NAME_MAX = 64
_HINT_MAX = 300


def validate(cfg: Any, where: str) -> None:
    """Raise ValueError if an exercise's `terminal:` block is malformed."""
    if cfg is None:
        return
    if not isinstance(cfg, dict):
        raise ValueError(f"{where}: terminal must be a mapping")
    hint = cfg.get("blocked_hint")
    if hint is not None and (not isinstance(hint, str) or len(hint) > _HINT_MAX):
        raise ValueError(f"{where}: terminal.blocked_hint must be text of at most {_HINT_MAX} characters")
    unknown = set(cfg) - {"allow", "allow_extra", "scripts", "blocked_hint"}
    if unknown:
        raise ValueError(f"{where}: terminal has unknown key(s): {', '.join(sorted(unknown))}")
    for key in ("allow", "allow_extra"):
        names = cfg.get(key)
        if names is None:
            continue
        if not isinstance(names, list) or not all(
            isinstance(n, str) and n.strip() and len(n) <= _NAME_MAX and " " not in n.strip()
            for n in names
        ):
            raise ValueError(f"{where}: terminal.{key} must be a list of program names")
    if "scripts" in cfg and not isinstance(cfg["scripts"], bool):
        raise ValueError(f"{where}: terminal.scripts must be true or false")


def policy_for(exercise: dict[str, Any]) -> dict[str, Any]:
    """The effective rules the plugin enforces for this exercise."""
    cfg = exercise.get("terminal") or {}
    base = cfg.get("allow")
    allow = {n.strip().lower() for n in (base if base is not None else DEFAULT_ALLOW)}
    if base is None and (exercise.get("language") or "").lower() == "python":
        allow |= set(PYTHON_EXTRA)
    allow |= {n.strip().lower() for n in cfg.get("allow_extra") or []}
    return {
        "allow": sorted(allow),
        "scripts": bool(cfg.get("scripts", True)),
        "source": "exercise" if cfg else "default",
        # Shown under every refused line: where to run the command instead.
        "blocked_hint": (cfg.get("blocked_hint") or "").strip() or None,
    }
