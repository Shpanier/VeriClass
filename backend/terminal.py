"""Rules for the VeriExam terminal (the plugin's checked + logged terminal).

An exercise may carry an optional `terminal:` block:

    terminal:
      allow: [ls, cat, grep, awk, sort, uniq, head, tail, wc, git]  # replaces the default list
      allow_extra: [python3]   # added on top of `allow` (or of the default list)
      scripts: true            # students may run their own .sh scripts (checked line by line)

Without one, DEFAULT_ALLOW applies. Shell builtins (cd, echo, export, test, …)
are always allowed; shells (sh, bash, powershell, cmd) and eval/exec never are —
the plugin enforces both regardless of this list.
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

_NAME_MAX = 64


def validate(cfg: Any, where: str) -> None:
    """Raise ValueError if an exercise's `terminal:` block is malformed."""
    if cfg is None:
        return
    if not isinstance(cfg, dict):
        raise ValueError(f"{where}: terminal must be a mapping")
    unknown = set(cfg) - {"allow", "allow_extra", "scripts"}
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
    allow |= {n.strip().lower() for n in cfg.get("allow_extra") or []}
    return {
        "allow": sorted(allow),
        "scripts": bool(cfg.get("scripts", True)),
        "source": "exercise" if cfg else "default",
    }
