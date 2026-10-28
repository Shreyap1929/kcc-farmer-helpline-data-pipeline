"""
API contract tests with a fake engine (no models or data needed).
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.app import create_app
from src.assistant.sessions import SessionStore
from src.assistant.translate import AssistantUnavailable


class FakeRetriever:
    def __len__(self):
        return 3


class FakeEngine:
    retriever = FakeRetriever()

    def __init__(self):
        self.calls = []

    def triage(self, text, district=None, crop=None, month=None):
        self.calls.append((text, district, crop, month))
        if "expert" in text:
            return {"route": "EXPERT_REVIEW", "reply": "gate draft", "draft_for_expert": "PRIVATE DRAFT",
                    "sources": [], "reasons": [{"code": "DOSE_QUESTION"}]}
        return {"route": "ANSWER", "reply": "ok", "reasons": [{"code": "RETRIEVED_LOW_RISK", "detail": ""}]}

    def meta(self):
        return {"districts": [{"value": "PUNE", "label": "Pune"}], "crops": ["Wheat"], "kb_records": 3}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import src.assistant.composer as composer
    import src.api.app as app_module
    monkeypatch.setattr(composer, "get_groq_client", lambda: None)
    monkeypatch.setattr(app_module, "translate_to_english", lambda text, language: text)
    engine = FakeEngine()
    async def fake_tts(text, language):
        return b"reply-audio"

    audio_translate_calls = []
    def fake_audio_translate(audio, filename, content_type):
        audio_translate_calls.append((audio, filename, content_type))
        return "translated voice question"

    store = SessionStore(tmp_path / "assistant.db")
    with TestClient(create_app(engine=engine, session_store=store,
                               transcriber=lambda *args: {"text": "question", "language": "en"},
                               audio_translator=fake_audio_translate,
                               tts=fake_tts)) as c:
        c.engine = engine
        c.store = store
        c.audio_translate_calls = audio_translate_calls
        yield c


def test_console_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "KCC Triage Console" in r.text


def test_farmer_chat_page_is_served_separately(client):
    response = client.get("/chat")
    assert response.status_code == 200
    assert "KCC Farmer Helpline" in response.text
    assert "Conversation messages" in response.text


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "kb_records": 3}


def test_meta_includes_probe_examples(client):
    body = client.get("/api/meta").json()
    assert body["districts"][0]["value"] == "PUNE"
    assert len(body["examples"]) > 10
    assert {"text", "lang", "expected", "route"} <= set(body["examples"][0])
    assert body["examples"][0]["route"] == "ANSWER"  # what the (fake) engine actually returned


def test_triage_passes_profile_through(client):
    client.engine.calls.clear()  # start-up already ran the example probes
    r = client.post("/api/triage", json={"text": "Varieties of wheat", "district": "PUNE", "crop": "Wheat", "month": 11})
    assert r.status_code == 200
    assert r.json()["route"] == "ANSWER"
    assert client.engine.calls[-1] == ("Varieties of wheat", "PUNE", "Wheat", 11)


@pytest.mark.parametrize("payload", [
    {"text": "   "},
    {"text": "x", "month": 13},
    {"text": "x" * 1001},
    {},
])
def test_triage_rejects_bad_input(client, payload):
    assert client.post("/api/triage", json=payload).status_code == 422


def test_chat_session_and_message_text_fallback(client):
    session = client.post("/api/chat/session", json={"district": "PUNE", "crop": "Wheat"}).json()
    response = client.post("/api/chat/message", json={"session_id": session["session_id"], "text": "wheat"})
    assert response.status_code == 200
    assert response.json()["route"] == "ANSWER"
    assert response.json()["reply"].startswith("ok")


def test_chat_message_rejects_missing_session_and_blank_text(client):
    assert client.post("/api/chat/message", json={"session_id": "missing", "text": "hello"}).status_code == 404
    sid = client.post("/api/chat/session", json={}).json()["session_id"]
    assert client.post("/api/chat/message", json={"session_id": sid, "text": "  "}).status_code == 422


def test_expert_case_is_saved_but_draft_is_hidden(client):
    sid = client.post("/api/chat/session", json={}).json()["session_id"]
    result = client.post("/api/chat/message", json={"session_id": sid, "text": "expert review please"}).json()
    assert result["case_id"]
    assert "PRIVATE DRAFT" not in result["reply"]
    assert client.store.get_expert_case(result["case_id"])["draft"] == "PRIVATE DRAFT"


def test_voice_upload_returns_transcript_text_and_retrievable_reply_audio(client):
    sid = client.post("/api/chat/session", json={}).json()["session_id"]
    result = client.post("/api/chat/voice", data={"session_id": sid},
                         files={"audio": ("note.webm", b"fake audio", "audio/webm")})
    assert result.status_code == 200
    body = result.json()
    assert body["transcript"] == "question" and body["reply"]
    assert client.audio_translate_calls == [(b"fake audio", "note.webm", "audio/webm")]
    audio = client.get(body["audio_url"])
    assert audio.status_code == 200 and audio.content == b"reply-audio"
    assert audio.headers["content-type"] == "audio/mpeg"


def test_voice_unavailable_is_clear_and_not_crash(client):
    import src.api.app as app_module
    def unavailable(*args):
        raise AssistantUnavailable("voice unavailable: Groq is not configured")
    client.app.state.transcriber = unavailable
    sid = client.post("/api/chat/session", json={}).json()["session_id"]
    result = client.post("/api/chat/voice", data={"session_id": sid},
                         files={"audio": ("note.webm", b"fake audio", "audio/webm")})
    assert result.status_code == 503
    assert "voice unavailable" in result.json()["detail"]


def test_expired_or_unknown_audio_is_not_available(client):
    assert client.get("/api/chat/audio/no-such-id").status_code == 404
