"""The students' link, and the public tunnel behind it.

Students open one address: this server's chat (STUDENT_CHAT_PATH, /chat). On the
lecturer's own computer that is http://localhost:<port>/chat/; for a class it
has to be reachable from outside, through a tunnel:

  cloudflared   a "quick tunnel": no account, a new random https address each
                time it starts. The default.
  ngrok         a fixed address (NGROK_DOMAIN in .env), with an ngrok account.

The dashboard starts and stops the tunnel (POST /api/share/tunnel) and shows
the link and its QR code. A tunnel started some other way (deploy/tunnel.sh,
ngrok in a terminal) is found through ngrok's local API and shown the same way.
"""
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from backend import packages

log = logging.getLogger(__name__)

_CF_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_NGROK_URL = re.compile(r"https://[A-Za-z0-9.-]+\.ngrok(?:-free)?\.(?:app|dev|io)")
_EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"))

_lock = threading.Lock()
_state: dict[str, Any] = {"state": "off", "provider": None, "url": None, "error": None,
                          "proc": None, "log": [], "started_at": None}


def port() -> int:
    """The port this server listens on (the launcher sets VERICLASS_PORT)."""
    for name in ("VERICLASS_PORT",):
        try:
            return int(os.environ.get(name, ""))
        except ValueError:
            pass
    m = re.search(r":(\d+)", os.environ.get("BACKEND_URL", ""))
    return int(m.group(1)) if m else 8010


def chat_path() -> str:
    return os.environ.get("STUDENT_CHAT_PATH", "").strip().rstrip("/")


def bin_dir() -> Path:
    """Where a tunnel program the server downloaded itself is kept."""
    return packages.DATA_DIR / "bin"


def find(name: str) -> Optional[str]:
    exe = f"{name}.exe" if os.name == "nt" else name
    local = bin_dir() / exe
    if local.is_file():
        return str(local)
    path = os.pathsep.join([os.environ.get("PATH", ""), *_EXTRA_PATH])
    return shutil.which(name, path=path)


def available() -> dict[str, bool]:
    return {"cloudflared": bool(find("cloudflared")), "ngrok": bool(find("ngrok"))}


def ngrok_domain() -> str:
    d = os.environ.get("NGROK_DOMAIN", "").strip()
    d = re.sub(r"^https?://", "", d).rstrip("/")
    return "" if d.upper().startswith("CHANGEME") else d


def lan_addresses() -> list[str]:
    """This computer's addresses on the local network (for a class on the same Wi-Fi)."""
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent: only picks the route
            found.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    return [a for a in dict.fromkeys(found) if not a.startswith("127.")]


def _external_ngrok() -> Optional[str]:
    """An ngrok agent somebody else started on this computer, forwarding to our port."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=0.4) as r:
            tunnels = json.loads(r.read().decode("utf-8")).get("tunnels", [])
    except Exception:
        return None
    want = str(port())
    for t in tunnels:
        addr = str((t.get("config") or {}).get("addr", ""))
        if addr.rsplit(":", 1)[-1] == want and str(t.get("public_url", "")).startswith("https://"):
            return t["public_url"]
    return None


def _reader(proc: subprocess.Popen, provider: str) -> None:
    pattern = _CF_URL if provider == "cloudflared" else _NGROK_URL
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        with _lock:
            if _state["proc"] is not proc:
                return
            _state["log"] = (_state["log"] + [line])[-30:]
            if _state["state"] == "starting":
                m = pattern.search(line)
                if m:
                    _state.update(state="on", url=m.group(0), error=None)
    code = proc.wait()
    with _lock:
        if _state["proc"] is proc:
            was = _state["state"]
            _state.update(proc=None, url=None,
                          state="off" if was == "stopping" else "error",
                          error=None if was == "stopping" else _why(provider, _state["log"], code))


def _why(provider: str, lines: list[str], code: int) -> str:
    text = "\n".join(lines).lower()
    if provider == "ngrok" and ("authtoken" in text or "err_ngrok_4018" in text):
        return "ngrok needs your account's token first: run `ngrok config add-authtoken <token>` once."
    if provider == "ngrok" and "err_ngrok_108" in text:
        return "Your ngrok account already has a tunnel running somewhere else."
    if provider == "ngrok" and "err_ngrok_334" in text:
        return "That ngrok address is already in use by another tunnel."
    tail = next((ln for ln in reversed(lines) if ln.strip()), "")
    return f"The tunnel stopped (exit {code}). {tail[-200:]}".strip()


def start(provider: Optional[str] = None) -> dict[str, Any]:
    """Start a tunnel to this server. provider: 'cloudflared' | 'ngrok'; None
    picks ngrok when NGROK_DOMAIN is set and ngrok is installed, else cloudflared."""
    have = available()
    if provider is None:
        provider = "ngrok" if (ngrok_domain() and have["ngrok"]) else "cloudflared"
    if provider not in ("cloudflared", "ngrok"):
        raise ValueError("Unknown tunnel provider.")
    exe = find(provider)
    if not exe:
        raise FileNotFoundError(provider)
    with _lock:
        if _state["proc"] is not None and _state["proc"].poll() is None:
            return _public()
    target = f"http://127.0.0.1:{port()}"
    if provider == "cloudflared":
        cmd = [exe, "tunnel", "--no-autoupdate", "--url", target]
    else:
        cmd = [exe, "http", "--log", "stdout", "--log-format", "logfmt"]
        if ngrok_domain():
            cmd.append(f"--url={ngrok_domain()}")
        cmd.append(str(port()))
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}  # no console window
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, **flags)
    with _lock:
        _state.update(state="starting", provider=provider, url=None, error=None, proc=proc,
                      log=[], started_at=time.time())
        if provider == "ngrok" and ngrok_domain():
            _state["url"] = f"https://{ngrok_domain()}"
    threading.Thread(target=_reader, args=(proc, provider), daemon=True).start()
    return _public()


def stop() -> dict[str, Any]:
    with _lock:
        proc = _state["proc"]
        if proc is not None and proc.poll() is None:
            _state["state"] = "stopping"
        else:
            _state.update(state="off", url=None, error=None, proc=None)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return _public()


def _public() -> dict[str, Any]:
    with _lock:
        s = {k: _state[k] for k in ("state", "provider", "url", "error")}
        if s["state"] == "starting" and _state["started_at"] and time.time() - _state["started_at"] > 45:
            s["slow"] = True
    return s


def status() -> dict[str, Any]:
    """Everything the dashboard's "Share with students" panel shows."""
    t = _public()
    external = None
    if t["state"] in ("off", "error"):
        external = _external_ngrok()
        if external:
            t = {"state": "on", "provider": "ngrok", "url": external, "error": None, "external": True}
    path = chat_path()
    suffix = f"{path}/" if path else "/"
    p = port()
    host = os.environ.get("VERICLASS_HOST", "127.0.0.1").strip()
    lan = [f"http://{a}:{p}{suffix}" for a in lan_addresses()] if host in ("0.0.0.0", "::") else []
    student_url = os.environ.get("STUDENT_URL", "").strip()
    return {
        "chat_mounted": bool(path),
        "local_url": student_url or (f"http://localhost:{p}{suffix}" if path else "http://localhost:8011/"),
        "lan_urls": lan,
        "public_url": (t["url"].rstrip("/") + suffix) if (t["state"] == "on" and t["url"]) else None,
        "tunnel": t,
        "available": available(),
        "ngrok_domain": ngrok_domain(),
        "install_hint": install_hint(),
    }


# --- getting cloudflared when it isn't installed ---------------------------------------

_RELEASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"


def _asset() -> Optional[str]:
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return f"cloudflared-darwin-{'arm64' if arm else 'amd64'}.tgz"
    if system == "Windows":
        return "cloudflared-windows-amd64.exe"
    if system == "Linux":
        return f"cloudflared-linux-{'arm64' if arm else 'amd64'}"
    return None


def install_hint() -> str:
    """The one command that installs cloudflared with the system's package manager."""
    system = platform.system()
    if system == "Darwin":
        return "brew install cloudflared"
    if system == "Windows":
        return "winget install --id Cloudflare.cloudflared"
    return "See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"


def download_cloudflared() -> str:
    """Download Cloudflare's own release of cloudflared for this computer into
    the data folder (about 20-40 MB). Returns its path."""
    asset = _asset()
    if not asset:
        raise RuntimeError("No ready-made cloudflared for this system. " + install_hint())
    target_dir = bin_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    exe = target_dir / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    tmp = target_dir / (asset + ".part")
    req = urllib.request.Request(_RELEASE + asset, headers={"User-Agent": "VeriClass"})
    with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    if asset.endswith(".tgz"):
        import tarfile

        with tarfile.open(tmp) as tar:
            member = next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "cloudflared")
            src = tar.extractfile(member)
            assert src is not None
            with exe.open("wb") as out:
                shutil.copyfileobj(src, out)
        tmp.unlink()
    else:
        os.replace(tmp, exe)
    if os.name != "nt":
        exe.chmod(0o755)
    return str(exe)
