"""Plugin distribution over the (ngrok-exposed) backend.

The IDE plugins (CLion, PyCharm) can only be built on a JDK-21 machine, which is
usually not the machine running the backend. This lets the build machine PUBLISH
a freshly-built zip up to the backend, and any machine PULL + install it — all
over the same always-on tunnel that already exposes :8010.

Each product is stored independently, so BOTH can be live at once:

  POST /api/plugin/publish?version=&product=clion|pycharm   teacher-auth, raw .zip
  GET  /api/plugin/latest[?product=]                         public zip download
  GET  /api/plugin/version[?product=]                        public JSON metadata
  GET  /api/plugin/install.sh                                installer (newest, auto-IDE)
  GET  /api/plugin/install-clion.sh                          installer pinned to CLion
  GET  /api/plugin/install-pycharm.sh                        installer pinned to PyCharm

Without ?product=, version/latest return whatever was published most recently
(back-compat with the original single-product layout).

Downloads are intentionally public so the one-line install script needs no
token. The zip is a class tool, not a secret; the tunnel URL is the only gate.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from backend import deps

router = APIRouter()

# Where published zips live on the backend host. Override with PLUGIN_DIST_DIR.
DIST_DIR = Path(os.environ.get("PLUGIN_DIST_DIR", "./plugin_dist"))
_LATEST = DIST_DIR / "latest.json"           # newest of any product (back-compat)
_MAX_BYTES = 50 * 1024 * 1024  # plugin zips are ~0.4 MB; 50 MB is a sane ceiling
_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_PRODUCTS = ("clion", "pycharm")

# The installer script that students run. Served verbatim except two defaults are
# rewritten: the server URL (so it points back at whatever host served it) and,
# for the install-<product>.sh endpoints, the product to pin to.
_INSTALLER = Path(__file__).resolve().parents[2] / "scripts" / "update_plugin.sh"
_DEFAULT_LINE = 'DEFAULT_SERVER="https://upgrade-nape-smasher.ngrok-free.dev"'
_DEFAULT_PRODUCT_LINE = 'DEFAULT_PRODUCT=""'


def _check_product(product: str) -> str:
    if product not in _PRODUCTS:
        raise HTTPException(422, f"product must be one of {_PRODUCTS}.")
    return product


def _latest_path(product: str | None) -> Path:
    return DIST_DIR / (f"latest-{product}.json" if product else "latest.json")


def _read_latest(product: str | None = None) -> dict | None:
    try:
        return json.loads(_latest_path(product).read_text())
    except Exception:
        return None


@router.post("/plugin/publish")
async def publish_plugin(
    request: Request,
    version: str,
    filename: str | None = None,
    product: str = "clion",
    teacher: dict = Depends(deps.require_teacher),
):
    """Upload a built plugin zip (raw octet-stream body). Teacher only.

    `product` defaults to clion for back-compat with older publishers."""
    _check_product(product)
    data = await request.body()
    if not data:
        raise HTTPException(422, "Empty body — send the .zip as --data-binary.")
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, "Plugin zip too large.")
    if data[:2] != b"PK":
        raise HTTPException(422, "Body is not a .zip (missing PK signature).")

    version = _SAFE.sub("_", version.strip()) or "0"
    stored_name = f"veriexam-{product}-plugin-{version}.zip"
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    (DIST_DIR / stored_name).write_bytes(data)

    meta = {
        "version": version,
        "product": product,
        "filename": (filename or stored_name),
        "stored_name": stored_name,
        "size": len(data),
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "published_by": teacher.get("username", "teacher"),
    }
    blob = json.dumps(meta, indent=2)
    _latest_path(product).write_text(blob)   # per-product pointer
    _LATEST.write_text(blob)                  # newest-of-any pointer (auto endpoint)
    return {"ok": True, **meta}


@router.get("/plugin/version")
def plugin_version(product: str | None = None):
    """Metadata about the currently-published plugin (public). With ?product=,
    the newest for that product; without, the newest of any product."""
    if product is not None:
        _check_product(product)
    return _read_latest(product) or {"version": None}


def _serve_installer(request: Request, product: str | None) -> PlainTextResponse:
    """Serve update_plugin.sh with its default server URL rewritten to the host
    that served this request (so the one-liner always targets the same tunnel),
    and — for the product-pinned endpoints — its default product baked in."""
    if not _INSTALLER.exists():
        raise HTTPException(404, "Installer script is missing on the server.")
    text = _INSTALLER.read_text()
    host = request.headers.get("host", "")
    if host:
        proto = request.headers.get(
            "x-forwarded-proto", "https" if "ngrok" in host else request.url.scheme
        )
        text = text.replace(_DEFAULT_LINE, f'DEFAULT_SERVER="{proto}://{host}"')
    if product:
        text = text.replace(_DEFAULT_PRODUCT_LINE, f'DEFAULT_PRODUCT="{product}"')
    return PlainTextResponse(text, media_type="text/x-shellscript")


@router.get("/plugin/install.sh")
def install_script(request: Request):
    """Installer that grabs the newest plugin and installs into the matching IDE:

        curl -fsSL <this-url>/api/plugin/install.sh | bash
    """
    return _serve_installer(request, product=None)


@router.get("/plugin/install-clion.sh")
def install_script_clion(request: Request):
    """Installer pinned to the CLion plugin (curl -fsSL …/install-clion.sh | bash)."""
    return _serve_installer(request, product="clion")


@router.get("/plugin/install-pycharm.sh")
def install_script_pycharm(request: Request):
    """Installer pinned to the PyCharm plugin (curl -fsSL …/install-pycharm.sh | bash)."""
    return _serve_installer(request, product="pycharm")


@router.get("/plugin/latest")
def download_latest(product: str | None = None):
    """Stream the newest published plugin zip (public). With ?product=, that
    product's newest; without, the newest of any product."""
    if product is not None:
        _check_product(product)
    meta = _read_latest(product)
    if not meta:
        raise HTTPException(404, "No plugin has been published yet.")
    path = DIST_DIR / meta["stored_name"]
    if not path.exists():
        raise HTTPException(404, "Published plugin file is missing on the server.")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=meta.get("filename", meta["stored_name"]),
    )
