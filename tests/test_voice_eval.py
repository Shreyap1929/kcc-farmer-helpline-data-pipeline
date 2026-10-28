from pathlib import Path

from src.assistant.voice_eval import character_error_rate, evaluate


class Engine:
    def triage(self, text):
        return {"route": "EXPERT_REVIEW" if "disease" in text else "ANSWER"}


def test_character_error_rate_uses_unicode_codepoints_and_whitespace_normalization():
    assert character_error_rate("abc", "abc") == 0
    assert character_error_rate("abc", "adc") == 1 / 3
    assert character_error_rate("a  b", "a b") == 0
    assert character_error_rate("", "text") is None


def test_missing_audio_is_reported_without_fabricated_metrics(tmp_path, monkeypatch):
    import src.assistant.voice_eval as voice_eval
    monkeypatch.setattr(voice_eval, "AUDIO_ROOT", tmp_path)
    report, results = evaluate(Engine(), rows=[{"file": "missing.mp3", "speaker": "synthetic-edge",
                                                "lang": "mr", "noisy": "false", "reference_text": "ref",
                                                "expected_route": ""}],
                               transcriber=lambda *_: (_ for _ in ()).throw(AssertionError("should not transcribe")))
    assert results[0]["status"] == "audio missing"
    assert "No CER or route-agreement score" in report


def test_voice_route_agreement_uses_typed_reference_and_transcript(tmp_path, monkeypatch):
    import src.assistant.voice_eval as voice_eval
    monkeypatch.setattr(voice_eval, "AUDIO_ROOT", tmp_path)
    (tmp_path / "note.mp3").write_bytes(b"opaque test bytes")
    report, results = evaluate(Engine(), rows=[{"file": "note.mp3", "speaker": "synthetic-test",
                                                "lang": "en", "noisy": "false", "reference_text": "disease",
                                                "expected_route": "EXPERT_REVIEW"}],
                               transcriber=lambda *_: {"text": "disease"})
    assert results[0]["cer"] == 0
    assert results[0]["typed_route"] == results[0]["voice_route"] == "EXPERT_REVIEW"
    assert results[0]["route_agreement"] and results[0]["expected_route_match"]
    assert "synthetic" in report


def test_voice_audio_path_cannot_escape_audio_root(tmp_path, monkeypatch):
    import src.assistant.voice_eval as voice_eval
    monkeypatch.setattr(voice_eval, "AUDIO_ROOT", tmp_path / "audio")
    report, results = evaluate(Engine(), rows=[{"file": "../secret.mp3", "speaker": "test",
                                                "lang": "hi", "noisy": "false", "reference_text": "ref",
                                                "expected_route": ""}])
    assert results[0]["status"] == "invalid audio path"
