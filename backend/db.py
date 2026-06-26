import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "./oslab.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    login_code  TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT 'student',
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    exercise        TEXT NOT NULL,
    mode            TEXT NOT NULL,
    variant         TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    body          TEXT NOT NULL,
    mode_at_time  TEXT NOT NULL,
    answer_level  TEXT,            -- 'nudge' | 'normal' | 'more' when picked by teacher; NULL otherwise
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS system_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    question     TEXT NOT NULL,
    -- English variants (the originals). Kept NOT NULL for backward compat.
    variant_nudge   TEXT NOT NULL,
    variant_normal  TEXT NOT NULL,
    variant_more    TEXT NOT NULL,
    -- Hebrew variants (added for the bilingual teacher dashboard).
    variant_nudge_he   TEXT,
    variant_normal_he  TEXT,
    variant_more_he    TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'answered' | 'expired'
    chosen_level TEXT,                              -- 'nudge' | 'normal' | 'more'
    chosen_lang  TEXT,                              -- 'en' | 'he' (language the teacher sent)
    final_text   TEXT,                              -- exact text sent (may be teacher-edited)
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    answered_at  TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS probes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    answer          TEXT,
    auto_grade      INTEGER,
    override_grade  INTEGER,
    source          TEXT NOT NULL DEFAULT 'manual',
    sent_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    answered_at     TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS api_audit_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        INTEGER,
    sanitized_input   TEXT,
    encrypted_raw     BLOB,
    called_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Exam/proctor trail: one row each time the exam client reports the student
-- leaving (or returning to) the IDE. The teacher dashboard reads these to flag
-- possible cheating. 'kind' is one of:
--   exam_started | focus_lost | minimized | fullscreen_exited
--   | focus_regained | window_restored
CREATE TABLE IF NOT EXISTS proctor_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    detail      TEXT,
    away_ms     INTEGER,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_probes_session ON probes(session_id, status);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, last_active_at);
CREATE INDEX IF NOT EXISTS idx_pending_reviews_status ON pending_reviews(status, created_at);
CREATE INDEX IF NOT EXISTS idx_proctor_session ON proctor_events(session_id, id);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    try:
        yield c
    finally:
        c.close()


def _add_missing_columns(c, table: str, columns: dict[str, str]) -> None:
    """ALTER TABLE ... ADD COLUMN for any column missing on an existing table.
    `columns` maps column name -> SQL type. CREATE TABLE IF NOT EXISTS never
    updates an already-created table, so pre-existing DBs need this."""
    existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, sqltype in columns.items():
        if name not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}")


def init_schema() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        # Tiny migrations: CREATE IF NOT EXISTS won't add columns to a table
        # that already exists, so back-fill them on pre-existing DBs.
        _add_missing_columns(c, "messages", {"answer_level": "TEXT"})
        _add_missing_columns(c, "pending_reviews", {
            "variant_nudge_he": "TEXT",
            "variant_normal_he": "TEXT",
            "variant_more_he": "TEXT",
            "chosen_lang": "TEXT",
            "final_text": "TEXT",
        })
