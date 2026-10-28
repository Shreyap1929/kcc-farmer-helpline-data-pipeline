"""Reusing expert answers for repeat questions: safety conditions and the API loop (offline)."""
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.assistant.sessions import SessionStore
from src.review.reviewed_answers import ReviewedAnswers, delivered_text
from src.review.workflow import resolve_case

YELLOW = "माझ्या कापसाची पाने पिवळी पडत आहेत"
YELLOW_AGAIN = "माझ्या कापसाची पाने पिवळी पडत आहेत ?"  # same words, the fake embedder maps it close
SAFE_ANSWER = "कापसाला पाणी नियमित द्या आणि शेतात पाणी साचू देऊ नका."
LOW_CONF = {"route": "EXPERT_REVIEW", "reasons": [{"code": "LOW_CONFIDENCE"}]}


def fake_embed(texts):
    """Deterministic unit vectors from the words, ignoring punctuation: same words -> similarity 1."""
    out = []
    for text in texts:
        vec = np.zeros(64, dtype=np.float32)
        for word in "".join(ch for ch in text if ch.isalnum() or ch.isspace() or "ऀ" <= ch <= "ॿ").split():
            vec[zlib.crc32(word.encode()) % 64] += 1
        out.append(vec / (np.linalg.norm(vec) or 1))
    return np.stack(out)


def answered_case(store, *, text=YELLOW, answer=SAFE_ANSWER, language="mr") -> dict:
    sid = store.create_session(language=language)["session_id"]
    case_id = store.save_expert_case(session_id=sid, original_text=text, english_text="Cotton leaves yellow",
                                     language=language, reasons=[{"code": "LOW_CONFIDENCE"}], draft=None, sources=[])
    return resolve_case(store, case_id, action="answer", expert="Dr Patil", answer=answer,
                        translator=lambda t, l: t)


@pytest.fixture()
def store(tmp_path):
    return SessionStore(tmp_path / "runtime.db")


def test_safe_expert_answer_is_reused_for_the_same_question(store):
    case = answered_case(store)
    reviewed = ReviewedAnswers(store, fake_embed, threshold=0.95)
    match = reviewed.match(YELLOW_AGAIN, "mr", LOW_CONF)
    assert match["case_id"] == case["case_id"] and match["similarity"] > 0.99
    assert delivered_text(match) == SAFE_ANSWER


def test_chemical_answers_are_never_indexed(store):
    answered_case(store, answer="इमिडाक्लोप्रिड ४ मिली प्रति १० लिटर पाण्यात फवारा.")
    assert len(ReviewedAnswers(store, fake_embed, threshold=0.95)) == 0


@pytest.mark.parametrize("text,language,decision", [
    (YELLOW_AGAIN, "hi", LOW_CONF),                                                  # other language
    ("माझ्या सोयाबीनची पाने पिवळी पडत आहेत", "mr", LOW_CONF),                          # other crop
    (YELLOW_AGAIN, "mr", {"route": "EXPERT_REVIEW", "reasons": [{"code": "DOSE_QUESTION"}]}),
    (YELLOW_AGAIN, "mr", {"route": "EXPERT_REVIEW", "reasons": [{"code": "HIGH_RISK_TOPIC"}]}),
    (YELLOW_AGAIN, "mr", {"route": "CLARIFY", "reasons": [{"code": "CROP_MISSING"}]}),
    ("माझ्या कापसाची पाने पिवळी पडत आहेत किती मिली फवारू", "mr", LOW_CONF),            # asks for a dose
    ("गव्हाची पेरणी कधी करावी", "mr", LOW_CONF),                                       # different question
], ids=["language", "crop", "dose-reason", "high-risk", "not-expert-route", "dose-words", "unrelated"])
def test_reuse_is_refused_unless_every_condition_holds(store, text, language, decision):
    answered_case(store)
    assert ReviewedAnswers(store, fake_embed, threshold=0.95).match(text, language, decision) is None


def test_chat_reuses_an_answer_resolved_through_the_api(tmp_path, monkeypatch):
    import src.api.app as app_module
    import src.assistant.composer as composer
    monkeypatch.setattr(composer, "get_groq_client", lambda: None)
    monkeypatch.setattr(app_module, "translate_to_english", lambda text, language: text)
    monkeypatch.delenv("EXPERT_TOKEN", raising=False)

    class Engine:
        retriever = [1]

        def triage(self, text, district=None, crop=None, month=None):
            return {"route": "EXPERT_REVIEW", "reasons": [{"code": "LOW_CONFIDENCE"}], "sources": [],
                    "draft_for_expert": None}

    store = SessionStore(tmp_path / "assistant.db")
    app = create_app(engine=Engine(), session_store=store, review_translator=lambda t, l: t,
                     reviewed_embed=fake_embed)
    monkeypatch.setattr(app_module, "_examples", lambda engine: [])
    with TestClient(app) as api:
        first = api.post("/api/chat/session", json={"language": "mr"}).json()["session_id"]
        case_id = api.post("/api/chat/message", json={"session_id": first, "text": YELLOW}).json()["case_id"]
        api.post(f"/api/expert/cases/{case_id}/resolve",
                 json={"expert": "Dr Patil", "action": "answer", "answer": SAFE_ANSWER})

        second = api.post("/api/chat/session", json={"language": "mr"}).json()["session_id"]
        body = api.post("/api/chat/message", json={"session_id": second, "text": YELLOW_AGAIN}).json()
        assert body["route"] == "ANSWER" and body["case_id"] is None
        assert body["reviewed_case_id"] == case_id
        assert body["reply"].startswith(SAFE_ANSWER) and case_id in body["reply"]
        assert api.get("/api/expert/stats").json()["reused_answers"] == 1
        events = [e["kind"] for e in api.get(f"/api/expert/cases/{case_id}").json()["events"]]
        assert "reused" in events
