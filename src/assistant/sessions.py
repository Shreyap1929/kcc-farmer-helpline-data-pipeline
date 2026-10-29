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
            """)
            self._migrate_expert_cases(db)

    # Stage 3 created expert_cases with CHECK (status = 'pending'), so no case could
    # ever be resolved. SQLite cannot alter a CHECK, hence a copy into the v2 table.
    _CASE_COLUMNS = """
        case_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(session_id),
        original_text TEXT NOT NULL,
        english_text TEXT NOT NULL,
        language TEXT NOT NULL,
        route_reasons TEXT NOT NULL,
        draft TEXT,
        sources TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'in_review', 'answered', 'referred')),
        assigned_to TEXT,
        claimed_at TEXT,
        expert_answer TEXT,
        farmer_reply TEXT,
        resolution TEXT CHECK (resolution IN ('approved_draft', 'expert_answer', 'referred')),
        resolved_by TEXT,
        resolved_at TEXT,
        reply_checks TEXT,
        reusable INTEGER,
        delivered_at TEXT
    """
    _V1_COLUMNS = ("case_id, session_id, original_text, english_text, language, route_reasons, "
                   "draft, sources, created_at, status")

    def _migrate_expert_cases(self, db) -> None:
        existing = {row["name"] for row in db.execute("PRAGMA table_info(expert_cases)")}
        if existing and "resolution" not in existing:
            db.execute("ALTER TABLE expert_cases RENAME TO expert_cases_v1")
            db.execute(f"CREATE TABLE expert_cases ({self._CASE_COLUMNS})")
            db.execute(f"INSERT INTO expert_cases ({self._V1_COLUMNS}) "
                       f"SELECT {self._V1_COLUMNS} FROM expert_cases_v1")
            db.execute("DROP TABLE expert_cases_v1")
        db.execute(f"CREATE TABLE IF NOT EXISTS expert_cases ({self._CASE_COLUMNS})")
        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_cases_status ON expert_cases(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_cases_session ON expert_cases(session_id);
            CREATE TABLE IF NOT EXISTS case_events (
                event_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES expert_cases(case_id),
                kind TEXT NOT NULL,
                actor TEXT,
                detail TEXT,
                created_at TEXT NOT NULL
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
            db.execute(f"INSERT INTO expert_cases ({self._V1_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')", (
                case_id, session_id, original_text, english_text, language,
                json.dumps(reasons, ensure_ascii=False), draft,
                json.dumps(source_rows, ensure_ascii=False), _now(),
            ))
            self._event(db, case_id, "created", None, {"reasons": [_code(r) for r in reasons]})
        return case_id

    def get_expert_case(self, case_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM expert_cases WHERE case_id = ?", (case_id,)).fetchone()
        if not row:
            return None
        return _parse_case(row)

    # -- Stage 4: expert review --------------------------------------------

    @staticmethod
    def _event(db, case_id: str, kind: str, actor: str | None, detail: dict | None = None) -> None:
        db.execute("INSERT INTO case_events VALUES (?, ?, ?, ?, ?, ?)", (
            uuid4().hex, case_id, kind, actor, json.dumps(detail or {}, ensure_ascii=False), _now()))

    def list_cases(self, *, status: str | None = None, language: str | None = None,
                   limit: int = 200) -> list[dict]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if language:
            where.append("language = ?")
            params.append(language)
        sql = "SELECT * FROM expert_cases" + (f" WHERE {' AND '.join(where)}" if where else "")
        # Open work oldest first (first come, first served); resolved work newest first.
        order = " ORDER BY created_at DESC" if status in ("answered", "referred") else " ORDER BY created_at"
        with self._connect() as db:
            rows = db.execute(sql + order + " LIMIT ?", (*params, int(limit))).fetchall()
        return [_parse_case(row) for row in rows]

    def case_events(self, case_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM case_events WHERE case_id = ? ORDER BY created_at",
                              (case_id,)).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail"] or "{}")} for row in rows]

    def session_turns(self, session_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT text, route, created_at FROM turns WHERE session_id = ? "
                              "ORDER BY created_at", (session_id,)).fetchall()
        return [dict(row) for row in rows]

    def claim_case(self, case_id: str, expert: str) -> dict:
        """Assign an open case to an expert. Re-claiming one's own case is a no-op."""
        with self._connect() as db:
            row = db.execute("SELECT status, assigned_to FROM expert_cases WHERE case_id = ?",
                             (case_id,)).fetchone()
            if row is None:
                raise KeyError(case_id)
            if row["status"] not in OPEN_STATUSES:
                raise CaseConflict(f"case is already {row['status']}")
            if row["status"] == "in_review" and row["assigned_to"] != expert:
                raise CaseConflict(f"case is being reviewed by {row['assigned_to']}")
            if row["status"] == "pending":
                db.execute("UPDATE expert_cases SET status = 'in_review', assigned_to = ?, claimed_at = ? "
                           "WHERE case_id = ? AND status = 'pending'", (expert, _now(), case_id))
                self._event(db, case_id, "claimed", expert)
        return self.get_expert_case(case_id)

    def release_case(self, case_id: str, expert: str) -> dict:
        with self._connect() as db:
            done = db.execute("UPDATE expert_cases SET status = 'pending', assigned_to = NULL, claimed_at = NULL "
                              "WHERE case_id = ? AND status = 'in_review' AND assigned_to = ?",
                              (case_id, expert)).rowcount
            if not done:
                raise CaseConflict("only the assigned expert can release an in-review case")
            self._event(db, case_id, "released", expert)
        return self.get_expert_case(case_id)

    def resolve_case(self, case_id: str, *, status: str, expert: str, resolution: str,
                     expert_answer: str | None, farmer_reply: str, checks: dict, reusable: bool) -> dict:
        """Close an open case once; a second resolve (two experts racing) is refused."""
        with self._connect() as db:
            done = db.execute("""
                UPDATE expert_cases SET status = ?, resolution = ?, expert_answer = ?, farmer_reply = ?,
                    reply_checks = ?, reusable = ?, resolved_by = ?, resolved_at = ?,
                    assigned_to = COALESCE(assigned_to, ?)
                WHERE case_id = ? AND status IN ('pending', 'in_review')
                    AND (assigned_to IS NULL OR assigned_to = ?)""", (
                status, resolution, expert_answer, farmer_reply, json.dumps(checks, ensure_ascii=False),
                int(reusable), expert, _now(), expert, case_id, expert,
            )).rowcount
            if not done:
                raise CaseConflict("case is closed or assigned to another expert")
            self._event(db, case_id, status, expert, {"resolution": resolution, **checks})
        return self.get_expert_case(case_id)

    def retire_answer(self, case_id: str, expert: str) -> dict:
        """Stop an answered case from being reused for new questions."""
        with self._connect() as db:
            done = db.execute("UPDATE expert_cases SET reusable = 0 WHERE case_id = ? AND status = 'answered' "
                              "AND reusable = 1", (case_id,)).rowcount
            if not done:
                raise CaseConflict("only a reusable answered case can be retired")
            self._event(db, case_id, "retired", expert)
        return self.get_expert_case(case_id)

    def record_reuse(self, case_id: str, session_id: str, similarity: float) -> None:
        with self._connect() as db:
            self._event(db, case_id, "reused", None, {"session_id": session_id, "similarity": round(similarity, 4)})

    def take_updates(self, session_id: str) -> list[dict]:
        """Resolved cases the farmer has not seen yet; marks them delivered."""
        with self._connect() as db:
            rows = db.execute("""SELECT case_id, status, farmer_reply, language FROM expert_cases
                WHERE session_id = ? AND status IN ('answered', 'referred') AND delivered_at IS NULL
                ORDER BY resolved_at""", (session_id,)).fetchall()
            for row in rows:
                db.execute("UPDATE expert_cases SET delivered_at = ? WHERE case_id = ?", (_now(), row["case_id"]))
                self._event(db, row["case_id"], "delivered", None)
        return [dict(row) for row in rows]

    def stats(self) -> dict:
        with self._connect() as db:
            counts = {row["status"]: row["n"] for row in db.execute(
                "SELECT status, COUNT(*) AS n FROM expert_cases GROUP BY status")}
            minutes = [row["m"] for row in db.execute("""
                SELECT (julianday(resolved_at) - julianday(created_at)) * 1440 AS m
                FROM expert_cases WHERE resolved_at IS NOT NULL ORDER BY m""")]
            reused = db.execute("SELECT COUNT(*) FROM case_events WHERE kind = 'reused'").fetchone()[0]
            open_reasons = db.execute(
                "SELECT route_reasons FROM expert_cases WHERE status IN ('pending', 'in_review')").fetchall()
        reason_counts: dict[str, int] = {}
        for row in open_reasons:
            for reason in json.loads(row["route_reasons"]):
                code = _code(reason)
                if code:
                    reason_counts[code] = reason_counts.get(code, 0) + 1
        return {
            "by_status": {s: counts.get(s, 0) for s in ("pending", "in_review", "answered", "referred")},
            "median_minutes_to_resolve": round(minutes[len(minutes) // 2], 1) if minutes else None,
            "open_by_reason": dict(sorted(reason_counts.items(), key=lambda kv: -kv[1])),
            "reused_answers": reused,
        }


OPEN_STATUSES = ("pending", "in_review")


class CaseConflict(RuntimeError):
    """The case is not in a state that allows this action (or belongs to someone else)."""


def _code(reason) -> str | None:
    return reason.get("code") if isinstance(reason, dict) else getattr(reason, "code", None)


def _parse_case(row) -> dict:
    case = dict(row)
    case["route_reasons"] = json.loads(case["route_reasons"])
    case["sources"] = json.loads(case["sources"])
    case["reply_checks"] = json.loads(case["reply_checks"]) if case.get("reply_checks") else None
    if case.get("reusable") is not None:
        case["reusable"] = bool(case["reusable"])
    return case

