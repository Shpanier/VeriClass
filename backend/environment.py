"""What the tutor should know about where the student works: the operating
system (plugin 0.4.3+ sends it when the session starts and with every question;
older plugins only with terminal lines), which shell the VeriClass terminal runs,
and what that terminal allows. In October 2026 the tutor blamed a long number for
an error that really came from Windows; this block is the fix."""
from typing import Any, Optional

from backend import db, terminal

_MAX_OS = 80


def clean_os(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value[:_MAX_OS] if value else None


def remember_os(session_id: str, client_os: Optional[str]) -> None:
    """Store the OS the plugin reported for this session (ignored when empty)."""
    value = clean_os(client_os)
    if not value:
        return
    with db.conn() as c:
        c.execute("UPDATE sessions SET client_os = ? WHERE id = ? AND (client_os IS NULL OR client_os != ?)",
                  (value, session_id, value))


def client_os(session_id: str) -> Optional[str]:
    """The session's OS: as reported by the plugin, else from its terminal lines."""
    with db.conn() as c:
        row = c.execute("SELECT client_os FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row and row["client_os"]:
            return row["client_os"]
        row = c.execute(
            "SELECT client_os FROM terminal_commands WHERE session_id = ? AND client_os IS NOT NULL "
            "ORDER BY id DESC LIMIT 1", (session_id,),
        ).fetchone()
    return row["client_os"] if row else None


def family(os_name: Optional[str]) -> str:
    name = (os_name or "").lower()
    if name.startswith("windows"):
        return "windows"
    if name.startswith("mac") or "darwin" in name or "os x" in name:
        return "macos"
    if "linux" in name:
        return "linux"
    return "unknown"


def tutor_block(session_id: str, ex: dict[str, Any]) -> str:
    """System-prompt lines about the student's environment."""
    os_name = client_os(session_id)
    fam = family(os_name)
    policy = terminal.policy_for(ex)
    shell = {
        "windows": "BusyBox (busybox-w32)",
        "linux": "BusyBox",
        "macos": "the system shell (/bin/sh with the BSD versions of awk, sed and grep)",
    }.get(fam, "BusyBox on Windows and Linux, the system shell on macOS")
    lines = [
        "STUDENT ENVIRONMENT (use it when you diagnose an error):",
        f"- Operating system: {os_name}." if os_name else
        "- Operating system: not reported yet (most students use Windows).",
        f"- The VeriClass terminal at the bottom of PyCharm runs each line in {shell}.",
        "- Programs allowed in the VeriClass terminal: " + ", ".join(policy["allow"])
        + ". Anything else is refused there and reported to the teacher.",
    ]
    if policy.get("blocked_hint"):
        lines.append(f"- What students should do for other commands: {policy['blocked_hint']}")
    if (ex.get("language") or "").lower() == "python":
        lines.append("- Python files run with PyCharm's green Run button (or right-click, Run).")
    if fam in ("windows", "unknown"):
        lines.append("- Windows pitfalls: never suggest a command with a backslash (use [.] or [0-9.] "
                     "in patterns, and avoid \\n escapes in printf); a project folder whose path has "
                     "non-English letters makes `cd` fail, so suggest moving it to a folder with an "
                     "English name.")
    if fam == "macos":
        lines.append("- macOS pitfalls: sed -i needs an argument (sed -i ''), and grep -P is not available.")
    return "\n".join(lines)
