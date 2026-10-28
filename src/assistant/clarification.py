"""Apply one-turn, time-limited clarification follow-ups."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.triage.crops import detect_crops

MAX_PENDING_SECONDS = 10 * 60


@dataclass(frozen=True)
class ClarifiedInput:
    text: str
    crop: str | None = None
    used_pending: bool = False


def apply_followup(store, session_id: str, text: str, *, now: datetime | None = None) -> ClarifiedInput:
    pending = store.get_pending_clarification(session_id)
    if not pending:
        return ClarifiedInput(text)
    now = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(pending["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    store.clear_pending_clarification(session_id)
    if (now - created).total_seconds() > MAX_PENDING_SECONDS:
        return ClarifiedInput(text)

    if pending["reason"] == "CROP_MISSING":
        crops = detect_crops(text)
        if crops:
            return ClarifiedInput(pending["original_text"], crop=crops[0], used_pending=True)
        return ClarifiedInput(f"{pending['original_text']} {text}".strip(), used_pending=True)
    if pending["reason"] == "VAGUE":
        return ClarifiedInput(f"{pending['original_text']} {text}".strip(), used_pending=True)
    return ClarifiedInput(text)


def remember_if_clarifying(store, session_id: str, text: str, decision: dict) -> None:
    if decision.get("route") != "CLARIFY":
        return
    codes = {_value.get("code") if isinstance(_value, dict) else getattr(_value, "code", None)
             for _value in (decision.get("reasons") or [])}
    reason = next((code for code in ("CROP_MISSING", "VAGUE") if code in codes), None)
    if reason:
        store.remember_clarification(session_id, text, reason)

