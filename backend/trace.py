"""The student's exported trace: checking it and importing what never arrived.

The plugin keeps a local copy of everything it sends (terminal lines with their
full output, proctor events, pastes) plus the chat, so a student whose reports
didn't get through (network or tunnel down, IDE crash) can export it as CSV and
hand it in. Each row is signed with the session's trace_key (made by
POST /sessions) in a chain:

    mac_n = HMAC-SHA256(trace_key, "\\n".join([mac_{n-1}, seq, client_id,
                                               at_utc, session_id, kind, payload]))

with mac_0 = "". Editing, reordering or deleting a row breaks the chain from
that row on; the plugin ends each export with an `export_end` row, so a file
cut short is caught too. Only `payload` (the exact JSON the plugin sent, or
would have sent) is signed; the other columns are a readable copy of it.

Tamper-evident, not tamper-proof: the key sits in the student's IDE while the
session runs.
"""
import csv
import hashlib
import hmac
import io
import json
from typing import Optional

COLUMNS = [
    "seq", "at_utc", "at_local", "session_id", "student", "kind", "where",
    "text", "output", "exit_code", "delivered", "client_id", "payload", "mac",
]

MAX_CSV_BYTES = 32 * 1024 * 1024


def row_mac(key: str, prev_mac: str, seq: str, client_id: str, at_utc: str,
            session_id: str, kind: str, payload: str) -> str:
    msg = "\n".join([prev_mac, seq, client_id, at_utc, session_id, kind, payload])
    return hmac.new(key.encode(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def parse(text: str) -> list[dict]:
    """The export's rows. Raises ValueError when it isn't a VeriClass export."""
    if text.startswith("﻿"):  # Excel-friendly BOM the plugin writes
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None or [f.strip() for f in reader.fieldnames] != COLUMNS:
        raise ValueError("This isn't a VeriClass trace export (unexpected columns).")
    return [dict(r) for r in reader]


def verify(rows: list[dict], key_for_session) -> dict:
    """Check the chain. `key_for_session(session_id)` returns the trace_key or
    None. Returns a summary plus one entry per row:
    {seq, kind, client_id, valid, payload (parsed, or None)}."""
    if not rows:
        return {"ok": False, "error": "The file has no rows.", "rows": []}
    session_ids = {r["session_id"] for r in rows}
    if len(session_ids) != 1:
        return {"ok": False, "error": "The file mixes several sessions.", "rows": []}
    session_id = session_ids.pop()
    key = key_for_session(session_id)
    if not key:
        return {"ok": False, "error": "Unknown session, or one from before signed exports.",
                "session_id": session_id, "rows": []}

    out = []
    prev = ""
    first_bad: Optional[int] = None
    expected_seq = None
    for r in rows:
        want = row_mac(key, prev, r["seq"], r["client_id"], r["at_utc"], r["session_id"], r["kind"], r["payload"])
        valid = hmac.compare_digest(want, r["mac"].strip().lower())
        try:
            seq = int(r["seq"])
        except ValueError:
            seq, valid = None, False
        # The journal continues across IDE restarts, so an export starts at any seq.
        if expected_seq is not None and seq != expected_seq:
            valid = False
        expected_seq = (seq + 1) if seq is not None else None
        if not valid and first_bad is None:
            first_bad = len(out)
        if first_bad is not None:
            valid = False  # everything after a broken link is unproven
        try:
            payload = json.loads(r["payload"]) if r["payload"] else None
        except ValueError:
            payload = None
        out.append({"seq": seq, "kind": r["kind"], "client_id": r["client_id"], "at_utc": r["at_utc"],
                    "valid": valid, "payload": payload if isinstance(payload, dict) else None})
        prev = r["mac"].strip().lower()

    complete = bool(out) and out[-1]["kind"] == "export_end" and out[-1]["valid"]
    return {
        "ok": first_bad is None and complete,
        "session_id": session_id,
        "rows": out,
        "valid_rows": sum(1 for x in out if x["valid"]),
        "first_bad_seq": out[first_bad]["seq"] if first_bad is not None else None,
        "complete": complete,
        "error": None if first_bad is None and complete else (
            f"Row {out[first_bad]['seq']} was changed, removed or reordered — rows from it on are not trusted."
            if first_bad is not None else
            "The file was cut short (its end marker is missing)."
        ),
    }
