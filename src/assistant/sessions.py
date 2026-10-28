"""Small SQLite persistence layer for chat state and expert hand-off cases."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from src.assistant.config import REPO_ROOT

DEFAULT_DB = REPO_ROOT / "data" / "runtime" / "assistant.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Persists text and routing state; farmer audio is never written to disk."""

    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    district TEXT,
                    month INTEGER,
                    crop TEXT,
                    language TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    text TEXT NOT NULL,
                    route TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_clarifications (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
                    original_text TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expert_cases (
                    case_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    original_text TEXT NOT NULL,
                    english_text TEXT NOT NULL,
                    language TEXT NOT NULL,
                    route_reasons TEXT NOT NULL,
                    draft TEXT,
                    sources TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status = 'pending')
                );
            """)

    def create_session(self, *, district=None, month=None, crop=None, language=None) -> dict:
        session_id = uuid4().hex
        row = {"session_id": session_id, "district": district, "month": month, "crop": crop,
               "language": language, "created_at": _now()}
        with self._connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)", tuple(row.values()))
        return row

    def get_session(self, session_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def add_turn(self, session_id: str, text: str, route: str, latency_ms: float) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?)",
                       (uuid4().hex, session_id, text, route, float(latency_ms), _now()))

    def remember_clarification(self, session_id: str, original_text: str, reason: str) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO pending_clarifications VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET original_text=excluded.original_text,
                reason=excluded.reason, created_at=excluded.created_at""",
                       (session_id, original_text, reason, _now()))

    def get_pending_clarification(self, session_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM pending_clarifications WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def clear_pending_clarification(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM pending_clarifications WHERE session_id = ?", (session_id,))

    def save_expert_case(self, *, session_id: str, original_text: str, english_text: str,
                         language: str, reasons: list, draft: str | None, sources: list) -> str:
        case_id = f"KCC-{uuid4().hex[:10].upper()}"
        source_rows = [s.to_dict() if hasattr(s, "to_dict") else s for s in sources]
        with self._connect() as db:
            db.execute("INSERT INTO expert_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')", (
                case_id, session_id, original_text, english_text, language,
                json.dumps(reasons, ensure_ascii=False), draft,
                json.dumps(source_rows, ensure_ascii=False), _now(),
            ))
        return case_id

    def get_expert_case(self, case_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM expert_cases WHERE case_id = ?", (case_id,)).fetchone()
        if not row:
            return None
        case = dict(row)
        case["route_reasons"] = json.loads(case["route_reasons"])
        case["sources"] = json.loads(case["sources"])
        return case

