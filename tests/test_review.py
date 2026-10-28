"""Stage 4 expert review: storage, the LangGraph resolution workflow and the API (offline)."""
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.assistant.sessions import CaseConflict, SessionStore
from src.assistant.translate import AssistantUnavailable
from src.review.workflow import ReviewError, build_review_graph, resolve_case
from test_api import FakeEngine  # pytest puts tests/ on sys.path (rootdir-relative, no package)

MR_QUESTION = "कापसावर पांढरी माशी आली आहे, काय फवारावे?"
CHEMICAL_DRAFT = "इमिडाक्लोप्रिड १७.८ एसएल ४ मिली प्रति १० लिटर पाण्यात फवारणी करावी."


def new_case(store: SessionStore, *, language="mr", draft=CHEMICAL_DRAFT, text=MR_QUESTION) -> str:
    sid = store.create_session(language=language)["session_id"]
    store.add_turn(sid, text, "EXPERT_REVIEW", 12.0)
    return store.save_expert_case(session_id=sid, original_text=text, english_text="Whitefly on cotton, what to spray?",
                                  language=language, reasons=[{"code": "DOSE_QUESTION", "detail": "spray"}],
                                  draft=draft, sources=[])


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "runtime.db")


# -- storage ----------------------------------------------------------------

def test_stage3_database_is_migrated_and_keeps_cases(tmp_path: Path):
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY, district TEXT, month INTEGER, crop TEXT,
                                   language TEXT, created_at TEXT NOT NULL);
            CREATE TABLE expert_cases (case_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
                original_text TEXT NOT NULL, english_text TEXT NOT NULL, language TEXT NOT NULL,
                route_reasons TEXT NOT NULL, draft TEXT, sources TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status = 'pending'));
            INSERT INTO sessions VALUES ('s1', NULL, NULL, NULL, 'mr', '2026-10-28T10:00:00+00:00');
            INSERT INTO expert_cases VALUES ('KCC-OLD', 's1', 'प्रश्न', 'question', 'mr', '[]', 'draft', '[]',
                                             '2026-10-28T10:00:00+00:00', 'pending');
        """)
    store = SessionStore(db_path)
    case = store.get_expert_case("KCC-OLD")
    assert case["status"] == "pending" and case["draft"] == "draft"
    store.claim_case("KCC-OLD", "Dr Patil")
    assert store.get_expert_case("KCC-OLD")["status"] == "in_review"  # impossible under the old CHECK


def test_claim_is_exclusive_and_release_reopens(store):
    case_id = new_case(store)
    assert store.claim_case(case_id, "Dr Patil")["assigned_to"] == "Dr Patil"
    assert store.claim_case(case_id, "Dr Patil")["status"] == "in_review"  # idempotent for the owner
    with pytest.raises(CaseConflict):
        store.claim_case(case_id, "Dr Shinde")
    with pytest.raises(CaseConflict):
        store.release_case(case_id, "Dr Shinde")
    assert store.release_case(case_id, "Dr Patil")["status"] == "pending"
    assert [e["kind"] for e in store.case_events(case_id)] == ["created", "claimed", "released"]


# -- workflow ---------------------------------------------------------------

def test_approved_marathi_draft_goes_out_untranslated_and_is_not_reusable(store):
    case_id = new_case(store)
    calls = []
    result = resolve_case(store, case_id, action="approve_draft", expert="Dr Patil",
                          translator=lambda text, target: calls.append(text) or text)
    assert calls == []  # same language, nothing to translate
    assert result["status"] == "answered" and result["resolution"] == "approved_draft"
    assert result["farmer_reply"].startswith(f"प्रकरण {case_id} साठी तज्ज्ञांचे उत्तर:")
    assert CHEMICAL_DRAFT in result["farmer_reply"]
    assert result["reply_checks"]["localization"] == "not_needed"
    assert result["reply_checks"]["chemical"] is True and result["reusable"] is False


def test_english_answer_is_translated_when_numbers_survive(store):
    case_id = new_case(store)
    result = resolve_case(store, case_id, action="answer", expert="Dr Patil",
                          answer="Spray neem oil 5 ml per litre of water on cotton.",
                          translator=lambda text, target: "कापसावर निंबोळी तेल ५ मिली प्रति लिटर पाण्यात फवारा.")
    assert "निंबोळी तेल ५ मिली" in result["farmer_reply"]
    assert result["reply_checks"]["localization"] == "translated"
    assert result["expert_answer"].startswith("Spray neem oil")


@pytest.mark.parametrize("bad_translation,problem", [
    ("कापसावर निंबोळी तेल ५० मिली प्रति लिटर फवारा.", "added_number"),
    ("कापसावर निंबोळी तेल प्रति लिटर पाण्यात फवारा.", "dropped_number"),
    ("सोयाबीनवर निंबोळी तेल ५ मिली प्रति लिटर पाण्यात फवारा.", "changed_crop"),
], ids=["added-number", "dropped-number", "changed-crop"])
def test_unsafe_translation_falls_back_to_the_experts_words(store, bad_translation, problem):
    case_id = new_case(store)
    answer = "Spray neem oil 5 ml per litre of water on cotton."
    result = resolve_case(store, case_id, action="answer", expert="Dr Patil", answer=answer,
                          translator=lambda text, target: bad_translation)
    assert answer in result["farmer_reply"] and bad_translation not in result["farmer_reply"]
    assert problem in result["reply_checks"]["localization"]


def test_translation_outage_still_delivers(store):
    case_id = new_case(store)

    def down(text, target):
        raise AssistantUnavailable("down")

    result = resolve_case(store, case_id, action="answer", expert="Dr Patil",
                          answer="Remove affected leaves and keep the field clean.", translator=down)
    assert result["status"] == "answered"
    assert result["reply_checks"]["localization"] == "fallback:unavailable"
    assert result["reusable"] is True  # no chemical, no date: safe to consider for reuse


def test_referral_uses_template_and_translates_note(store):
    case_id = new_case(store, language="hi", text="मेरी कपास की फसल सूख रही है")
    result = resolve_case(store, case_id, action="refer", expert="Dr Patil", note="Please bring a sample of the plant.",
                          translator=lambda text, target: "कृपया पौधे का नमूना साथ लाएँ.")
    assert result["status"] == "referred" and result["resolution"] == "referred"
    assert "कृषि विज्ञान केंद्र" in result["farmer_reply"] and "1800-180-1551" in result["farmer_reply"]
    assert "कृपया पौधे का नमूना साथ लाएँ." in result["farmer_reply"]
    assert result["reusable"] is False


@pytest.mark.parametrize("kwargs,message", [
    ({"action": "answer", "expert": "", "answer": "x"}, "expert name"),
    ({"action": "answer", "expert": "Dr Patil", "answer": "   "}, "answer text"),
    ({"action": "delete", "expert": "Dr Patil"}, "action must be"),
], ids=["no-expert", "empty-answer", "bad-action"])
def test_invalid_submissions_are_refused(store, kwargs, message):
    case_id = new_case(store)
    with pytest.raises(ReviewError, match=message):
        resolve_case(store, case_id, translator=lambda t, l: t, **kwargs)
    assert store.get_expert_case(case_id)["status"] == "pending"


def test_cannot_approve_missing_draft_or_resolve_twice_or_take_anothers_case(store):
    graph = build_review_graph(store, lambda t, l: t)
    no_draft = new_case(store, draft=None)
    with pytest.raises(ReviewError, match="no draft"):
        resolve_case(store, no_draft, action="approve_draft", expert="Dr Patil", graph=graph)

    taken = new_case(store)
    store.claim_case(taken, "Dr Shinde")
    with pytest.raises(ReviewError, match="being reviewed by Dr Shinde"):
        resolve_case(store, taken, action="answer", expert="Dr Patil", answer="ok", graph=graph)

    done = new_case(store)
    resolve_case(store, done, action="approve_draft", expert="Dr Patil", graph=graph)
    with pytest.raises(ReviewError, match="already answered"):
        resolve_case(store, done, action="approve_draft", expert="Dr Patil", graph=graph)


def test_updates_are_delivered_once_and_stats_count_them(store):
    case_id = new_case(store)
    sid = store.get_expert_case(case_id)["session_id"]
    assert store.take_updates(sid) == []
    resolve_case(store, case_id, action="approve_draft", expert="Dr Patil", translator=lambda t, l: t)
    first = store.take_updates(sid)
    assert [u["case_id"] for u in first] == [case_id]
    assert store.take_updates(sid) == []
    stats = store.stats()
    assert stats["by_status"]["answered"] == 1 and stats["median_minutes_to_resolve"] is not None


# -- API --------------------------------------------------------------------

@pytest.fixture()
def api(tmp_path, monkeypatch):
    import src.api.app as app_module
    import src.assistant.composer as composer
    monkeypatch.setattr(composer, "get_groq_client", lambda: None)
    monkeypatch.setattr(app_module, "translate_to_english", lambda text, language: f"EN: {text}")
    monkeypatch.delenv("EXPERT_TOKEN", raising=False)

    async def fake_tts(text, language):
        return b"expert-audio"

    store = SessionStore(tmp_path / "assistant.db")
    app = create_app(engine=FakeEngine(), session_store=store, tts=fake_tts,
                     review_translator=lambda text, target: text)
    with TestClient(app) as c:
        c.store = store
        yield c


def _expert_case(api, language="mr"):
    sid = api.post("/api/chat/session", json={"language": language}).json()["session_id"]
    body = api.post("/api/chat/message", json={"session_id": sid, "text": "कापूस expert प्रश्न"}).json()
    return sid, body["case_id"]


def test_expert_flow_end_to_end_reaches_the_farmer(api):
    sid, case_id = _expert_case(api)
    assert api.get("/expert").status_code == 200
    queue = api.get("/api/expert/cases").json()["cases"]
    assert [c["case_id"] for c in queue] == [case_id] and queue[0]["english_text"].startswith("EN:")
    detail = api.get(f"/api/expert/cases/{case_id}").json()
    assert detail["draft"] == "PRIVATE DRAFT" and detail["conversation"][0]["route"] == "EXPERT_REVIEW"

    assert api.get(f"/api/chat/session/{sid}/updates").json() == {"updates": []}
    assert api.post(f"/api/expert/cases/{case_id}/claim", json={"expert": "Dr Patil"}).json()["status"] == "in_review"
    assert api.post(f"/api/expert/cases/{case_id}/claim", json={"expert": "Dr Shinde"}).status_code == 409
    resolved = api.post(f"/api/expert/cases/{case_id}/resolve",
                        json={"expert": "Dr Patil", "action": "answer", "answer": "पिकाची पाहणी करा."})
    assert resolved.status_code == 200 and resolved.json()["status"] == "answered"

    updates = api.get(f"/api/chat/session/{sid}/updates").json()["updates"]
    assert len(updates) == 1 and "पिकाची पाहणी करा." in updates[0]["reply"]
    assert api.get(updates[0]["audio_url"]).content == b"expert-audio"
    assert api.get(f"/api/chat/session/{sid}/updates").json() == {"updates": []}
    assert api.get("/api/expert/stats").json()["by_status"]["answered"] == 1


def test_expert_api_errors(api):
    _, case_id = _expert_case(api)
    assert api.get("/api/expert/cases/KCC-NOPE").status_code == 404
    assert api.get("/api/expert/cases?status=closed").status_code == 422
    assert api.post(f"/api/expert/cases/{case_id}/resolve",
                    json={"expert": "Dr Patil", "action": "answer", "answer": ""}).status_code == 422
    assert api.post(f"/api/expert/cases/{case_id}/resolve",
                    json={"expert": "Dr Patil", "action": "approve_draft"}).status_code == 200
    again = api.post(f"/api/expert/cases/{case_id}/resolve", json={"expert": "Dr Patil", "action": "approve_draft"})
    assert again.status_code == 409
    assert api.get("/api/chat/session/missing/updates").status_code == 404


def test_expert_token_is_enforced_when_configured(api, monkeypatch):
    monkeypatch.setenv("EXPERT_TOKEN", "s3cret")
    assert api.get("/api/expert/cases").status_code == 401
    assert api.get("/api/expert/cases", headers={"X-Expert-Token": "wrong"}).status_code == 401
    assert api.get("/api/expert/cases", headers={"X-Expert-Token": "s3cret"}).status_code == 200
