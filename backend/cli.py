"""`vericlass`: start everything with one command.

One server on one port: the lecturer's dashboard at /, the students' chat at
/chat, the API under /api. The start scripts (start.command, start.bat,
start.sh) run this; so does `uv run vericlass`.

    vericlass                 start on port 8010 and open the dashboard
    vericlass --port 8020     another port
    vericlass --lan           also reachable from the local network (same Wi-Fi)
    vericlass --no-browser    don't open the browser
"""
import argparse
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _utf8_or_restart(argv: list[str]) -> None:
    """Windows consoles and files default to a legacy code page, and the
    exercises are written in UTF-8 (Hebrew too): run in Python's UTF-8 mode."""
    if os.name == "nt" and not sys.flags.utf8_mode:
        env = dict(os.environ, PYTHONUTF8="1")
        sys.exit(subprocess.call([sys.executable, "-m", "backend.cli", *argv], env=env, cwd=str(ROOT)))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def _is_vericlass(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _keep_awake() -> None:
    """A sleeping laptop drops every student: stay awake while the server runs."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.name == "nt":
            import ctypes

            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED, until this process ends
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
    except Exception:
        pass  # a convenience, never a reason not to start


def _open_when_ready(port: int) -> None:
    for _ in range(240):
        if _is_vericlass(port):
            try:
                webbrowser.open(f"http://localhost:{port}/")
            except Exception:
                pass
            return
        time.sleep(0.5)


def _first_env_file() -> None:
    """A new install: create .env with a secret for the students' login page
    (so passwords are typed in a hidden field, not into the chat). The API key
    is added from the dashboard."""
    from backend import settings

    path = settings.env_file()
    if path.is_file():
        return
    example = ROOT / ".env.example"
    if example.is_file():
        path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    settings.save_env({"CHAINLIT_AUTH_SECRET": secrets.token_urlsafe(48)})


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    _utf8_or_restart(argv)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from dotenv import load_dotenv

    _first_env_file()
    load_dotenv(os.environ.get("VERICLASS_ENV_FILE") or ROOT / ".env")

    parser = argparse.ArgumentParser(prog="vericlass", description="Start VeriClass: the lecturer's "
                                     "dashboard and the students' chat, on one port.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("VERICLASS_PORT") or 8010))
    parser.add_argument("--host", default=os.environ.get("VERICLASS_HOST") or "127.0.0.1",
                        help="the address to listen on (default: this computer only)")
    parser.add_argument("--lan", action="store_true",
                        help="listen on every network address, so students on the same Wi-Fi can connect")
    parser.add_argument("--no-browser", action="store_true", help="don't open the dashboard in the browser")
    parser.add_argument("--no-chat", action="store_true",
                        help="don't serve the students' chat (run student_app yourself)")
    args = parser.parse_args(argv)
    host = "0.0.0.0" if args.lan else args.host

    if not _port_free("127.0.0.1" if host in ("0.0.0.0", "::") else host, args.port):
        if _is_vericlass(args.port):
            print(f"\n  VeriClass is already running: http://localhost:{args.port}/\n")
            if not args.no_browser:
                webbrowser.open(f"http://localhost:{args.port}/")
            return
        sys.exit(f"\n  Port {args.port} is used by another program. Start on a different one:\n"
                 f"      vericlass --port {args.port + 10}\n")

    os.environ["VERICLASS_PORT"] = str(args.port)
    os.environ["VERICLASS_HOST"] = host
    os.environ["BACKEND_URL"] = f"http://127.0.0.1:{args.port}"
    if args.no_chat:
        os.environ["STUDENT_CHAT_PATH"] = ""
    elif not os.environ.get("STUDENT_CHAT_PATH", "").strip():
        os.environ["STUDENT_CHAT_PATH"] = "/chat"

    _keep_awake()
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(args.port,), daemon=True).start()

    import uvicorn

    print("\n  Starting VeriClass (the first start takes a little longer)...", flush=True)
    uvicorn.run("backend.main:app", host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
