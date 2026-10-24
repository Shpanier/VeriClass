"""A class session in numbers, for the lecturer's own Claude Code session (MCP
tool session_report) to write a report from, like the October 2026 reports.

Students are numbered (S01, S02, … in the order they came in) and no names,
usernames, emails, login codes or file paths are included: whatever the tool
returns is sent to the model. With include_questions the students' questions
are added as they wrote them (they rarely contain names, but they may).
"""
import json
import statistics
from collections import Counter
from typing import Any, Optional

from backend import db, environment, steps


def _local_date_sql(col: str) -> str:
    return f"date({col}, 'localtime')"


def session_report(exercise_id: Optional[str] = None, course_id: Optional[str] = None,
                   date: Optional[str] = None, include_questions: bool = False) -> dict[str, Any]:
    with db.conn() as c:
        where, args = [], []
        if exercise_id:
            where.append("s.exercise = ?")
            args.append(exercise_id)
        if course_id:
            where.append("s.course_id = ?")
            args.append(course_id)
        base = " AND ".join(where) or "1=1"
        if not date:
            row = c.execute(
                f"SELECT MAX({_local_date_sql('s.started_at')}) AS d FROM sessions s "
                f"JOIN users u ON u.id = s.user_id WHERE u.role = 'student' AND {base}", args,
            ).fetchone()
            date = row["d"]
        if not date:
            return {"found": False, "message": "No student sessions match."}
        sessions = [dict(r) for r in c.execute(
            f"SELECT s.* FROM sessions s JOIN users u ON u.id = s.user_id "
            f"WHERE u.role = 'student' AND {base} AND ({_local_date_sql('s.started_at')} = ? "
            f"OR {_local_date_sql('s.last_active_at')} = ?) ORDER BY s.started_at",
            (*args, date, date),
        )]
        if not sessions:
            return {"found": False, "date": date, "message": "No student sessions on that date."}
        ids = [s["id"] for s in sessions]
        num = {sid: f"S{i:02d}" for i, sid in enumerate(ids, 1)}
        marks = ",".join("?" * len(ids))

        def rows(sql: str, extra: tuple = ()) -> list[dict]:
            return [dict(r) for r in c.execute(sql.format(marks=marks), (*ids, *extra))]

        messages = rows("SELECT session_id, role, body, answer_level, model, created_at FROM messages "
                        "WHERE session_id IN ({marks}) ORDER BY created_at, id")
        reviews = rows("SELECT * FROM pending_reviews WHERE session_id IN ({marks}) ORDER BY created_at")
        checks = rows("SELECT * FROM step_checks WHERE session_id IN ({marks}) ORDER BY created_at")
        terminal = rows("SELECT session_id, line, allowed, reason, commands, exit_code, client_os "
                        "FROM terminal_commands WHERE session_id IN ({marks}) ORDER BY id")

    def secs(a: Optional[str], b: Optional[str]) -> Optional[float]:
        if not a or not b:
            return None
        from datetime import datetime
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()

    def summary(values: list[float]) -> Optional[dict]:
        if not values:
            return None
        return {"median": round(statistics.median(values), 1), "mean": round(statistics.mean(values), 1),
                "max": round(max(values), 1), "min": round(min(values), 1), "n": len(values)}

    answered = [r for r in reviews if r["status"] == "answered"]
    waits = [w for w in (secs(r["created_at"], r["answered_at"]) for r in answered) if w is not None]
    decided = [ch for ch in checks if ch["status"] != "pending"]
    decision_times = [d for d in (secs(ch["created_at"], ch["decided_at"]) for ch in decided) if d is not None]
    os_of = {sid: environment.client_os(sid) for sid in ids}

    # How complete the approved submissions were (step questions vs answered).
    from backend import exercises
    incomplete = 0
    for ch in checks:
        if ch["status"] != "approved":
            continue
        try:
            ex = exercises.get(next(s["exercise"] for s in sessions if s["id"] == ch["session_id"]))
        except KeyError:
            continue
        st = steps.steps_of(ex)
        step = st[ch["step"] - 1] if 0 < ch["step"] <= len(st) else None
        q = steps.question_count(step) if step else None
        a = steps.answered_count(ch["answer"], q)
        if q and a is not None and a < q:
            incomplete += 1

    programs = Counter()
    for t in terminal:
        if t["allowed"]:
            programs.update(json.loads(t["commands"] or "[]"))
    per_student = []
    for s in sessions:
        sid = s["id"]
        mine = [m for m in messages if m["session_id"] == sid]
        per_student.append({
            "student": num[sid],
            "os": environment.family(os_of[sid]),
            "first_seen": s["started_at"],
            "last_active": s["last_active_at"],
            "messages": sum(1 for m in mine if m["role"] == "user"),
            "questions_to_teacher": sum(1 for r in reviews if r["session_id"] == sid),
            "step_submissions": sum(1 for ch in checks if ch["session_id"] == sid),
            "steps_approved": len({ch["step"] for ch in checks if ch["session_id"] == sid and ch["status"] == "approved"}),
            "terminal_lines": sum(1 for t in terminal if t["session_id"] == sid),
            "blocked": sum(1 for t in terminal if t["session_id"] == sid and not t["allowed"]),
        })

    report: dict[str, Any] = {
        "found": True,
        "date": date,
        "exercise_id": exercise_id or sorted({s["exercise"] for s in sessions}),
        "course_id": course_id,
        "window": {"first_session": sessions[0]["started_at"],
                   "last_activity": max(s["last_active_at"] for s in sessions), "timezone": "UTC"},
        "students": len(sessions),
        "operating_systems": dict(Counter(environment.family(os_of[sid]) for sid in ids)),
        "messages": {"from_students": sum(1 for m in messages if m["role"] == "user"),
                     "replies": sum(1 for m in messages if m["role"] == "assistant"),
                     "students_who_wrote": len({m["session_id"] for m in messages if m["role"] == "user"})},
        "review_queue": {
            "questions": len(reviews),
            "answered": len(answered),
            "expired": sum(1 for r in reviews if r["status"] == "expired"),
            "waiting": sum(1 for r in reviews if r["status"] == "pending"),
            "wait_seconds": summary(waits),
            "levels_sent": dict(Counter(r["chosen_level"] for r in answered)),
            "languages_sent": dict(Counter(r["chosen_lang"] for r in answered)),
            "drafted_by": dict(Counter(r["model"] or "unknown" for r in reviews)),
            "redone_with_stronger_model": sum(1 for r in reviews if r["regenerated_at"]),
            "with_bank_match": sum(1 for r in reviews if r["bank_match"]),
        },
        "steps": {
            "submissions": len(checks),
            "approved": sum(1 for ch in checks if ch["status"] == "approved"),
            "returned": sum(1 for ch in checks if ch["status"] == "returned"),
            "waiting": sum(1 for ch in checks if ch["status"] == "pending"),
            "decision_seconds": summary(decision_times),
            "approved_with_fewer_answers_than_questions": incomplete,
        },
        "terminal": {
            "lines": len(terminal),
            "ran": sum(1 for t in terminal if t["allowed"]),
            "blocked": sum(1 for t in terminal if not t["allowed"]),
            "top_programs": dict(programs.most_common(12)),
            "blocked_reasons": dict(Counter((t["reason"] or "")[:80] for t in terminal if not t["allowed"]).most_common(8)),
            "nonzero_exit": sum(1 for t in terminal if t["allowed"] and t["exit_code"] not in (0, None)),
        },
        "per_student": per_student,
    }
    if include_questions:
        report["questions"] = [
            {"student": num[m["session_id"]], "at": m["created_at"], "text": m["body"][:600]}
            for m in messages if m["role"] == "user"
        ]
    return report
