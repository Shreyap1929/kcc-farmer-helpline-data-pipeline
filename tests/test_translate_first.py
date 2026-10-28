"""Opt-in translated retrieval keeps the original safety text at the gate."""
import numpy as np
import pytest

from src.triage.engine import TriageEngine


class Retriever:
    def __init__(self):
        self.query = None

    def search(self, vec, **kwargs):
        self.query = (vec, kwargs)
        return []


class Classifier:
    def __init__(self):
        self.text = None

    def predict_one(self, text, vec):
        self.text = text
        return {"query_type": {"label": "Weather", "confidence": 0.5},
                "crop": {"label": "Others", "confidence": 0.0}}


class Gate:
    t = {}

    def resolve_crop(self, inp):
        self.probe_input = inp
        return inp.profile_crop, "profile" if inp.profile_crop else None

    def decide(self, inp):
        self.final_input = inp
        return type("Decision", (), {"to_dict": lambda _self: {"route": "ANSWER"}})()


@pytest.fixture
def engine():
    retriever, classifier, gate = Retriever(), Classifier(), Gate()
    texts = []

    def embed(values):
        texts.extend(values)
        return np.ones((len(values), 2), dtype=np.float32)

    instance = TriageEngine(retriever, classifier, gate, embed)
    instance.probe = (retriever, classifier, gate, texts)
    return instance


def test_default_expansion_path_is_preserved(engine):
    result = engine.triage("How to sow wheat?")
    retriever, classifier, gate, texts = engine.probe
    assert texts == ["How to sow wheat?"]
    assert classifier.text == "How to sow wheat?"
    assert gate.final_input.text == "How to sow wheat?"
    assert set(result["query"]) == {"text", "district", "crop", "month", "season", "retrieval_text"}


def test_translate_mode_uses_translation_for_retrieval_and_original_for_gate(engine):
    original = "\u092e\u0930\u093e\u0920\u0940 \u092a\u094d\u0930\u0936\u094d\u0928"
    result = engine.triage(original, translated_text="today price of onion", retrieval_mode="translate")
    retriever, classifier, gate, texts = engine.probe
    assert texts == ["today price of onion"]
    assert classifier.text == "today price of onion"
    assert gate.final_input.text == original
    assert gate.final_input.signals.live_market
    assert result["query"]["retrieval_mode"] == "translate"


def test_translate_mode_requires_translation_for_devanagari(engine):
    with pytest.raises(ValueError, match="translated_text is required"):
        engine.triage("\u092e\u0930\u093e\u0920\u0940", retrieval_mode="translate")


def test_english_is_identical_even_if_translation_mode_requested(engine):
    engine.triage("Weather tomorrow", translated_text="unrelated translation", retrieval_mode="translate")
    assert engine.probe[3] == ["Weather tomorrow"]
    assert engine.classifier.text == "Weather tomorrow"
