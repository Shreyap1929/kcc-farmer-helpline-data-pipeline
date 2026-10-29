"""Offline tests for reply composition, session persistence and clarification state."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.assistant.clarification import apply_followup, remember_if_clarifying
from src.assistant.composer import compose_reply
from src.assistant.sessions import SessionStore


class FakeGroq:
    def __init__(self, text):
        self.text = text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


def answer_decision(answer="Sow cotton in June."):
    return {"route": "ANSWER", "reply": answer,
            "answer_source": {"answer": answer, "kcc_call_id": "123", "created_on": "2025-01-04",
                              "district": "Pune"}, "reasons": []}


def test_answer_composer_adds_source_and_rewrites_grounded_numbers():
    client = FakeGroq("Plant cotton in June.")
    reply = compose_reply(answer_decision(), "en", client=client)
    assert reply == "Plant cotton in June.\n\nSource: KCC call 123, 2025-01-04, Pune."
    assert client.calls[0]["temperature"] == 0


def test_answer_composer_falls_back_on_ungrounded_number():
    reply = compose_reply(answer_decision("Apply nothing."), "en", client=FakeGroq("Apply 20 ml."))
    assert reply.startswith("Apply nothing.")
    assert "20 ml" not in reply


def test_answer_composer_falls_back_when_llm_fails():
    class Failed:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(TimeoutError())))

    assert compose_reply(answer_decision(), "en", client=Failed()).startswith("Sow cotton in June.")


def test_non_answer_routes_use_fixed_multilingual_templates_and_review_flag():
    templates_decision = {"route": "CLARIFY", "reasons": [{"code": "CROP_MISSING"}], "reply": "unsafe ignored"}
    mr = compose_reply(templates_decision, "mr")
    assert "कोणत्या" in mr
    assert "unsafe ignored" not in mr
    import yaml
    from src.assistant.composer import TEMPLATE_PATH
    meta = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    # Reviewed templates must say who reviewed them; unreviewed ones must stay flagged.
    assert meta["needs_native_review"] is True or meta["native_review"]["by"]


def test_expert_reply_does_not_include_draft():
    decision = {"route": "EXPERT_REVIEW", "reasons": [], "reply": "gate text",
                "draft_for_expert": "PRIVATE CHEMICAL DRAFT"}
    reply = compose_reply(decision, "en", case_id="KCC-ABC123")
    assert "KCC-ABC123" in reply
    assert "PRIVATE CHEMICAL DRAFT" not in reply


def test_session_turn_and_expert_case_persistence(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    session = store.create_session(district="PUNE", crop="Cotton", language="mr")
    store.add_turn(session["session_id"], "प्रश्न", "EXPERT_REVIEW", 42.5)
    case_id = store.save_expert_case(session_id=session["session_id"], original_text="प्रश्न",
                                     english_text="question", language="mr", reasons=[{"code": "DOSE_QUESTION"}],
                                     draft="hidden dose", sources=[])
    case = store.get_expert_case(case_id)
    assert case["status"] == "pending"
    assert case["draft"] == "hidden dose"
    assert case["original_text"] == "प्रश्न" and case["english_text"] == "question"


def test_crop_followup_replays_original_question_with_detected_crop(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    session = store.create_session()
    sid = session["session_id"]
    store.remember_clarification(sid, "my crop has a disease", "CROP_MISSING")
    result = apply_followup(store, sid, "cotton")
    assert result.text == "my crop has a disease"
    assert result.crop == "Cotton (Kapas)" and result.used_pending
    assert store.get_pending_clarification(sid) is None


def test_vague_followup_combines_context_and_consumes_pending(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    sid = store.create_session()["session_id"]
    store.remember_clarification(sid, "information", "VAGUE")
    result = apply_followup(store, sid, "cotton leaves are yellow")
    assert result.text == "information cotton leaves are yellow" and result.used_pending


def test_expired_clarification_is_not_reused(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    sid = store.create_session()["session_id"]
    store.remember_clarification(sid, "information", "VAGUE")
    old = datetime.now(timezone.utc) - timedelta(minutes=11)
    # Age the pending record to exercise expiry deterministically.
    with store._connect() as db:
        db.execute("UPDATE pending_clarifications SET created_at=? WHERE session_id=?", (old.isoformat(), sid))
    result = apply_followup(store, sid, "cotton", now=datetime.now(timezone.utc))
    assert result.text == "cotton" and not result.used_pending


def test_clarification_remembers_only_supported_reasons(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    sid = store.create_session()["session_id"]
    remember_if_clarifying(store, sid, "my crop has disease", {"route": "EXPERT_REVIEW", "reasons": []})
    assert store.get_pending_clarification(sid) is None
