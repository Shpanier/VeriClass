"""Run an exercise's terminal commands on macOS and in BusyBox, and show what differs.

Usage:
    python scripts/check_exercise_os.py ../VeriExPrivateData/exercises/lab1-linux-git
    python scripts/check_exercise_os.py config/exercises/*.yaml --no-docker

Takes exercise package folders (backend/packages.py, teacher.yaml merged in) or
one-file exercise YAMLs.

What it runs, in order, in a fresh folder: every command in the code blocks of
each step, then the step's teacher-only `os_check:` lines (put the reference
solutions there so they are checked too). Three runs:

  local    this machine's /bin/bash (on a Mac: the BSD tools students on Mac get)
  busybox  BusyBox + Git in Docker: the tools of the Windows and Linux terminal
  win-030  the same, with every \\ turned into / as plugin 0.3.0 does on Windows

First it prints the static warnings (backend/portability.py). Then every
command whose output differs between runs, after ignoring spaces before
numbers, Git hashes and temp paths. Exit code 1 when something differs or an
"error" warning was found.

Needs Docker for the BusyBox runs (busybox-w32 on Windows is the same BusyBox
code, but a slightly different version: check a real Windows machine before a
graded exam).
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import packages, portability, terminal  # noqa: E402

IMAGE = "alpine/git:v2.47.2"  # BusyBox 1.37 + Git 2.47

# Reads commands from fd 3 so a command that reads stdin can't eat the list.
DRIVER = r"""
cd "$1" || exit 2
i=0
while IFS= read -r __line <&3; do
    i=$((i+1))
    [ "$2" = slash ] && __line=$(printf '%s' "$__line" | tr '\\' '/')
    printf '\n@@VE-CMD %d\n' "$i"
    eval "$__line" </dev/null 2>&1
    printf '\n@@VE-EXIT %d %d\n' "$i" "$?"
done 3< "$1/../commands.txt"
"""

ENV = {
    "LC_COLLATE": "C", "PAGER": "cat", "GIT_PAGER": "cat",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_EDITOR": "false", "TERM": "dumb",
}


def run(kind: str, base: Path, commands: list[str]) -> dict[int, tuple[int, str]]:
    work = base / kind / "work"
    if work.parent.exists():
        shutil.rmtree(work.parent)
    work.mkdir(parents=True)
    (work.parent / "commands.txt").write_text("\n".join(commands) + "\n", encoding="utf-8")
    (work.parent / "driver.sh").write_text(DRIVER, encoding="utf-8")
    env_args = [f"{k}={v}" for k, v in ENV.items()]
    if kind == "local":
        home = work.parent / "home"
        home.mkdir()
        cmd = ["env", "-i", f"PATH=/usr/bin:/bin:/usr/sbin:/sbin", f"HOME={home}", *env_args,
               "/bin/bash", str(work.parent / "driver.sh"), str(work), "plain"]
    else:
        cmd = ["docker", "run", "--rm", "-v", f"{work.parent}:/x", "--entrypoint", "sh"]
        for e in env_args + ["HOME=/tmp"]:
            cmd += ["-e", e]
        cmd += [IMAGE, "/x/driver.sh", "/x/work", "slash" if kind == "win-030" else "plain"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600).stdout
    return parse(out)


def parse(out: str) -> dict[int, tuple[int, str]]:
    res, cur, buf = {}, None, []
    for line in out.splitlines():
        m = re.match(r"@@VE-CMD (\d+)$", line)
        e = re.match(r"@@VE-EXIT (\d+) (\d+)$", line)
        if m:
            cur, buf = int(m.group(1)), []
        elif e and cur is not None:
            res[cur] = (int(e.group(2)), normalize("\n".join(buf)))
            cur = None
        elif cur is not None:
            buf.append(line)
    return res


def normalize(text: str) -> str:
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "<hash>", text)
    text = re.sub(r"(Initialized empty Git repository in ).*", r"\1<path>", text)
    text = re.sub(r"\S*/work\b", "<work>", text)
    text = re.sub(r"(?m)^Date: .*", "Date: <date>", text)
    text = re.sub(r"/(private/)?(var|tmp)/\S*", "<tmp>", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def check(path: Path, use_docker: bool) -> int:
    ex = (packages.load_package(path) if path.is_dir()
          else yaml.safe_load(path.read_text(encoding="utf-8")))
    allow = set(terminal.policy_for(ex)["allow"])
    cmds = portability.commands_of(ex, allow)
    print(f"\n=== {ex['exercise_id']}: {len(cmds)} commands")
    bad = 0

    warnings = portability.lint_exercise(ex, allow)
    for w in warnings:
        mark = "ERROR" if w["level"] == "error" else "note "
        print(f"  {mark} step {w['step']} ({w['source']}): {w['line']}\n         {w['message']}")
        bad += w["level"] == "error"

    if not use_docker or not shutil.which("docker"):
        print("  (BusyBox runs skipped: --no-docker, or Docker is not installed)")
        return 1 if bad else 0

    lines = [c[2] for c in cmds]
    with tempfile.TemporaryDirectory(prefix="ve-os-") as tmp:
        base = Path(tmp)
        runs = {k: run(k, base, lines) for k in ("local", "busybox", "win-030")}

    for i, (step, source, line) in enumerate(cmds, start=1):
        got = {k: runs[k].get(i, (-1, "<did not run>")) for k in runs}
        if got["local"] == got["busybox"] == got["win-030"]:
            continue
        who = "local vs busybox" if got["local"] != got["busybox"] else "plugin 0.3.0 on Windows only"
        bad += got["local"] != got["busybox"]
        print(f"\n  DIFF step {step} ({source}) [{who}]: {line}")
        for k, (code, text) in got.items():
            short = text if len(text) < 300 else text[:300] + " …"
            print(f"    {k:8} exit {code}: {short!r}")
    same = sum(1 for i in range(1, len(cmds) + 1)
               if runs["local"].get(i) == runs["busybox"].get(i))
    print(f"\n  {same}/{len(cmds)} commands give the same result on macOS and BusyBox.")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--no-docker", action="store_true", help="static warnings only")
    args = ap.parse_args()
    rc = 0
    for f in args.files:
        rc |= check(f, not args.no_docker)
    sys.exit(rc)


if __name__ == "__main__":
    main()
