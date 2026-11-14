"""CI: a VeriClass that was just installed, used the way a new lecturer and a
student would. Waits for the server, then: the dashboard and the chat answer, the
first lecturer account, the sample exercise uploaded as a zip (Hebrew included),
a course with a student from a Hebrew CSV, and that student signing in to the chat.

    python .github/smoke.py http://127.0.0.1:8010 <the VeriClass folder> [seconds to wait]

Standard library only, so any Python runs it.
"""
import base64
import http.cookiejar
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

BASE = sys.argv[1].rstrip("/")
ROOT = Path(sys.argv[2])
WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 120

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
failed = []


def call(method, path, body=None, token=None, form=None):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=60) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failed.append(name)
        print(f"::error title=Smoke test::{name}: {str(detail)[:300]}")
    return ok


t0 = time.time()
while True:
    try:
        if call("GET", "/healthz")[0] == 200:
            break
    except OSError:
        pass
    if time.time() - t0 > WAIT:
        check(f"the server answers within {WAIT} s", False)
        sys.exit(1)
    time.sleep(3)
print(f"server up after {time.time() - t0:.0f} s")

status, page = call("GET", "/")
check("the dashboard page", status == 200 and '<div id="root">' in page, status)
status, page = call("GET", "/chat/")
check("the student chat page", status == 200 and "<html" in page.lower(), status)
status, st = call("GET", "/api/setup/status")
check("a new install asks for the first lecturer", status == 200 and st.get("needs_teacher") is True, st)

status, r = call("POST", "/api/setup/teacher",
                 {"name": "מרצה בדיקה", "username": "lecturer", "password": "Smoke-test-2026"})
if not check("the first lecturer account", status in (200, 201) and bool(r.get("token")), r):
    sys.exit(1)
token = r["token"]

buf = io.BytesIO()
lab = ROOT / "examples" / "first-lab"
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(lab.rglob("*")):
        if f.is_file():
            z.write(f, Path("first-lab") / f.relative_to(lab))
status, r = call("POST", "/api/exercises/import",
                 {"zip_base64": base64.b64encode(buf.getvalue()).decode(), "replace": True}, token)
check("the sample exercise uploads as a zip", status == 200 and r.get("ok"), r)
status, r = call("GET", "/api/exercises", token=token)
items = r if isinstance(r, list) else r.get("exercises", []) if isinstance(r, dict) else []
lab_ex = next((e for e in items if e.get("exercise_id") == "first-lab"), {})
check("its Hebrew title reads back", "חימום" in json.dumps(lab_ex, ensure_ascii=False), lab_ex)

status, r = call("POST", "/api/courses", {"course_id": "smoke", "name": "קורס בדיקה"}, token)
check("a course", status == 201, r)
status, r = call("PUT", "/api/courses/smoke", {"name": "קורס בדיקה", "exercises": ["first-lab"],
                                               "default_exercise": "first-lab"}, token)
check("the course offers the exercise", status == 200, r)
csv = "שם,ת.ז.\nדנה כהן,000000018\n".encode("utf-8")
status, r = call("POST", "/api/students/import", {"content_base64": base64.b64encode(csv).decode(),
                                                  "course_id": "smoke", "dry_run": False}, token)
rows = r.get("rows", []) if isinstance(r, dict) else []
code = rows[0].get("code") if rows else None
check("a student from a Hebrew CSV", status == 200 and bool(code), r)

if code:
    status, r = call("POST", "/chat/login", form={"username": code, "password": code})
    check("the student signs in to the chat", status == 200, r)
    status, r = call("GET", "/chat/user")
    check("the chat knows the student", status == 200 and isinstance(r, dict)
          and r.get("identifier") == code.lower(), r)
    status, r = call("POST", "/chat/login", form={"username": code, "password": "wrong"})
    check("a wrong password is refused", status in (401, 403), status)

print("FAILED: " + ", ".join(failed) if failed else "all smoke checks passed")
sys.exit(1 if failed else 0)
