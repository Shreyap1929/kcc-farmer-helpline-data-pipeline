"""Regression tests for the Stage 3 defects found when the app was first run end to end."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.assistant.clarification import apply_followup
from src.assistant.composer import compose_reply, rewrite_problems
from src.assistant.config import chat_options, get_config
from src.assistant.language import reply_language
from src.assistant.sessions import SessionStore

GROUNDNUT = ("भुईमूग पेरणीची वेळ उन्हाळी – १५ जानेवारी ते १५ फेब्रुवारी, पेरणीचे वेळी किमान तापमान "
             "१८ अंश सेल्सिअस किंवा त्यापेक्षा जास्त असावे.")


class FakeGroq:
    def __init__(self, text):
        self.text, self.calls = text, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


def groundnut_decision():
    return {"route": "ANSWER", "crop": "Groundnut (pea nut/mung phalli)", "reasons": [],
            "query": {"text": "SOWING TIME OF GROUNDNUT CROP ?"},
            "answer_source": {"answer": GROUNDNUT, "kcc_call_id": "2055", "created_on": "2024-01-01",
                              "district": "Akola"}}


def test_configured_chat_model_is_not_the_retired_one():
    # llama-3.1-8b-instant returned 404 model_not_found, silently disabling every rewrite.
    assert get_config()["groq"]["chat_model"] != "llama-3.1-8b-instant"
    assert chat_options()["temperature"] == 0


def test_rewrite_that_changes_the_crop_is_rejected():
    # Observed live: gpt-oss-120b turned groundnut into "black gram" with every number intact.
    wrong = ("The sowing time for black gram is during summer, from January 15 to February 15. "
             "At sowing, the temperature should be at least 18 °C.")
    assert "changed_crop" in rewrite_problems(wrong, GROUNDNUT, "SOWING TIME OF GROUNDNUT CROP ?")
    reply = compose_reply(groundnut_decision(), "en", client=FakeGroq(wrong))
    assert reply.startswith(GROUNDNUT) and "black gram" not in reply


def test_rewrite_that_drops_a_number_or_refuses_is_rejected():
    dropped = "Sow groundnut in summer from January 15 to February 15."
    assert "dropped_number" in rewrite_problems(dropped, GROUNDNUT)
    assert rewrite_problems("", GROUNDNUT) == ["empty"]


def test_good_rewrite_is_used_with_question_context_and_localized_source():
    good = ("The sowing time for groundnut is from 15 January to 15 February. The minimum temperature "
            "at sowing should be 18 degrees Celsius or higher.")
    client = FakeGroq(good)
    reply = compose_reply(groundnut_decision(), "en", client=client)
    assert reply == f"{good}\n\nSource: KCC call 2055, 2024-01-01, Akola."
    prompt = client.calls[0]["messages"][1]["content"]
    assert "SOWING TIME OF GROUNDNUT CROP ?" in prompt and "Crop: Groundnut\n" in prompt  # alias stripped
    hi = compose_reply(groundnut_decision(), "hi", client=FakeGroq("भुईमूग की बुवाई 15 जनवरी से 15 फरवरी तक, 18 डिग्री."))
    assert hi.endswith("स्रोत: KCC कॉल 2055, 2024-01-01, Akola.")


def test_pointer_templates_carry_the_helpline_numbers():
    reply = compose_reply({"route": "LIVE_DATA_POINTER", "reasons": []}, "mr")
    assert "1800-180-1551" in reply
    scheme = compose_reply({"route": "SCHEME_POINTER", "reasons": []}, "en")
    assert "155261" in scheme and "14447" in scheme


@pytest.mark.parametrize("text,session,expected", [
    ("माझ्या कापसाची पाने पिवळी पडत आहेत", "en", "mr"),   # Marathi typed into an English session
    ("मेरी कपास की पत्तियाँ पीली हो रही हैं", "mr", "hi"),
    ("गहू वाण", "hi", "hi"),                              # too short to tell: the session decides
    ("Leaves are turning yellow", "en", "en"),
    ("kapus var pandhri mashi", "mr", "mr"),             # romanized Marathi keeps the chosen language
    ("", "hi", "hi"),
])
def test_reply_language_follows_what_the_farmer_wrote(text, session, expected):
    assert reply_language(text, session) == expected


def test_new_question_after_crop_clarification_is_not_swallowed(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    sid = store.create_session()["session_id"]
    store.remember_clarification(sid, "The leaves on my crop are turning yellow", "CROP_MISSING")
    result = apply_followup(store, sid, "How to control pink bollworm in cotton")
    assert result.text == "How to control pink bollworm in cotton" and result.crop is None
    assert store.get_pending_clarification(sid) is None


def test_short_crop_answer_still_completes_the_clarification(tmp_path: Path):
    store = SessionStore(tmp_path / "runtime.db")
    sid = store.create_session()["session_id"]
    store.remember_clarification(sid, "The leaves on my crop are turning yellow", "CROP_MISSING")
    result = apply_followup(store, sid, "it is cotton")
    assert result.text == "The leaves on my crop are turning yellow" and result.crop.startswith("Cotton")


def test_chat_page_explains_missing_server_and_polls_for_expert_answers():
    page = (Path(__file__).resolve().parents[1] / "src" / "api" / "static" / "chat.html").read_text(encoding="utf-8")
    assert 'window.location.protocol === "file:"' in page
    assert "/updates" in page and "trackCase(result.case_id)" in page


def test_templates_file_is_readable_utf8():
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "reply_templates.yaml").read_text(encoding="utf-8"))
    for key in ("REFERRED", "EXPERT_ANSWER_HEADER", "EXPERT_NOTE"):
        assert set(data["templates"][key]) == {"en", "mr", "hi"}


def test_tts_falls_back_to_gtts_when_edge_is_rejected(monkeypatch):
    import asyncio
    from src.assistant import tts

    async def edge_403(text, voice):
        raise RuntimeError("403 Invalid response status")

    monkeypatch.setattr(tts, "_edge_synthesize", edge_403)
    monkeypatch.setattr(tts, "_gtts_synthesize", lambda text, lang: b"gtts-mp3")
    assert asyncio.run(tts.synthesize("नमस्कार", "mr")) == b"gtts-mp3"
