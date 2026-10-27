"""
Unit tests for the routing gate, using fake classifier output and fake
retrieval hits. No data files or models needed.
"""
import itertools
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.triage.config import load_config
from src.triage.crops import detect_crops
from src.triage.gate import Gate, GateInput, Route
from src.triage.policy import question_signals
from src.triage.retrieval import Hit

COTTON = "Cotton (Kapas)"
WHEAT = "Wheat"


@pytest.fixture(scope="module")
def gate():
    t = dict(load_config()["gate"])
    t.update(answer_min_similarity=0.92, out_of_scope_max_similarity=0.82)
    return Gate(t)


def pred(qtype="Varieties", qconf=0.9, crop=WHEAT, cconf=0.3):
    return {
        "query_type": {"label": qtype, "confidence": qconf, "alternatives": []},
        "crop": {"label": crop, "confidence": cconf, "alternatives": []},
    }


def hit(sim=0.95, chemical=False, crop=WHEAT, answer="गव्हाचे सुधारित वाण: फुले समाधान, एमएसीएस 6222.", call="1"):
    return Hit(
        kcc_call_id=call, question="VARIETIES OF WHEAT ?", answer=answer, similarity=sim, score=sim,
        created_on="2024-11-12", district="Pune", crop=crop, season="rabi", query_type="Varieties",
        answer_lang="marathi", risk="chemical" if chemical else "low", chemical=chemical,
        times_asked=40, distinct_answers=3, answer_share=0.6, source_file="mh-2024-11.csv", source_row=7,
    )


def run(gate, text, prediction=None, hits=None, profile_crop=None):
    return gate.decide(GateInput(
        text=text, signals=question_signals(text), crops_mentioned=detect_crops(text),
        prediction=prediction or pred(), hits=[hit()] if hits is None else hits, profile_crop=profile_crop,
    ))


# --- routes ----------------------------------------------------------------------

def test_answer_happy_path(gate):
    d = run(gate, "Varieties of wheat")
    assert d.route == Route.ANSWER
    assert d.reply == d.answer_source.answer
    assert d.grounded is True
    assert d.reasons[0].code == "RETRIEVED_LOW_RISK"


@pytest.mark.parametrize("text", ["MARKET RATE OF ONION ?", "कांद्याचा आजचा बाजारभाव काय आहे"])
def test_market_goes_to_live_pointer(gate, text):
    d = run(gate, text)
    assert d.route == Route.LIVE_DATA_POINTER
    assert d.reasons[0].code == "LIVE_MARKET_INTENT"
    assert "agmarknet" in d.reply


def test_weather_goes_to_live_pointer(gate):
    d = run(gate, "उद्या पाऊस पडेल का")
    assert d.route == Route.LIVE_DATA_POINTER
    assert "IMD" in d.reply


def test_confident_market_classifier_alone_triggers_live(gate):
    d = run(gate, "cotton selling today", prediction=pred("Market Information", 0.9))
    assert d.route == Route.LIVE_DATA_POINTER
    assert d.reasons[0].code == "LIVE_TYPE_PREDICTED"


def test_live_type_prediction_ignored_for_dose_questions(gate):
    # Noisy labels: "FERTILIZER DOSE OF MAIZE" is sometimes labelled Weather.
    d = run(gate, "fertilizer dose of maize", prediction=pred("Weather", 0.95))
    assert d.route == Route.EXPERT_REVIEW


def test_pm_kisan_goes_to_scheme_pointer(gate):
    d = run(gate, "पीएम किसान योजनेचा पुढचा हप्ता कधी येणार")
    assert d.route == Route.SCHEME_POINTER
    assert "155261" in d.reply


def test_crop_insurance_pointer_uses_insurance_helpline(gate):
    d = run(gate, "पीक विमा नुकसान भरपाई कशी मिळेल")
    assert d.route == Route.SCHEME_POINTER
    assert "14447" in d.reply


@pytest.mark.parametrize("text", ["information", "माहिती हवी"])
def test_vague_question_asks_to_clarify(gate, text):
    d = run(gate, text)
    assert d.route == Route.CLARIFY and d.reasons[0].code == "VAGUE"


def test_empty_question(gate):
    assert run(gate, "   ").route == Route.CLARIFY


def test_off_topic_low_similarity(gate):
    d = run(gate, "Who won the cricket match", prediction=pred("Other", 0.4), hits=[hit(sim=0.78)])
    assert d.route == Route.OUT_OF_SCOPE


@pytest.mark.parametrize("qtype", ["Government Schemes", "Market Information"])
def test_off_topic_is_not_rescued_by_a_confident_classifier(gate, qtype):
    # Classifier-only shortcuts to the scheme/live pointers need an in-domain match.
    d = run(gate, "Who won the cricket match", prediction=pred(qtype, 0.95), hits=[hit(sim=0.78)])
    assert d.route == Route.OUT_OF_SCOPE


def test_low_similarity_with_a_crop_is_not_out_of_scope(gate):
    d = run(gate, "strange spots on wheat leaves", prediction=pred("Cultural Practices", 0.8), hits=[hit(sim=0.78)])
    assert d.route == Route.EXPERT_REVIEW
    assert d.reasons[0].code == "LOW_CONFIDENCE"


def test_farm_words_prevent_out_of_scope_for_marathi(gate):
    # Cross-lingual similarity is lower; "पिकावर रोग" (disease on the crop) is clearly farming.
    d = run(gate, "पिकावर रोग आला आहे", prediction=pred("Plant Protection", 0.7, cconf=0.2), hits=[hit(sim=0.80)])
    assert d.route == Route.CLARIFY and d.reasons[0].code == "CROP_MISSING"


def test_confident_high_risk_topic_goes_to_expert_even_with_clean_answer(gate):
    # No dose words, clean-looking answer: only the topic prediction catches it.
    d = run(gate, "wheat leaves turning yellow", prediction=pred("Nutrient Management", 0.85), hits=[hit(sim=0.99)])
    assert d.route == Route.EXPERT_REVIEW and d.reasons[0].code == "HIGH_RISK_TOPIC"


def test_unconfident_high_risk_topic_falls_through_to_answer_checks(gate):
    d = run(gate, "Varieties of wheat", prediction=pred("Plant Protection", 0.4), hits=[hit(sim=0.97)])
    assert d.route == Route.ANSWER


def test_dose_question_always_goes_to_expert_with_draft(gate):
    d = run(gate, "Fertilizer dose for wheat", prediction=pred("Fertilizer Use and Availability"), hits=[hit(sim=0.99)])
    assert d.route == Route.EXPERT_REVIEW
    assert d.reasons[0].code == "DOSE_QUESTION"
    assert d.draft_for_expert


def test_expert_draft_prefers_the_callers_crop(gate):
    papaya = hit(sim=0.99, crop="Papaya", answer="papaya answer", call="p")
    cotton = hit(sim=0.95, crop=COTTON, answer="cotton answer", call="c")
    d = run(gate, "cotton whitefly spray dose", prediction=pred("Plant Protection"), hits=[papaya, cotton])
    assert d.reasons[0].code == "DOSE_QUESTION"
    assert d.draft_for_expert == "cotton answer" and d.answer_source.kcc_call_id == "c"


def test_crop_dependent_question_without_crop_asks_for_crop(gate):
    d = run(gate, "My crop has a disease what should I do", prediction=pred("Plant Protection", 0.8, cconf=0.2))
    assert d.route == Route.CLARIFY and d.reasons[0].code == "CROP_MISSING"


def test_profile_crop_removes_need_to_clarify(gate):
    d = run(gate, "Leaves are turning yellow", prediction=pred("Plant Protection", 0.8, cconf=0.2),
            hits=[hit(sim=0.95, crop=COTTON, chemical=True)], profile_crop=COTTON)
    assert d.route == Route.EXPERT_REVIEW
    assert d.crop == COTTON and d.crop_source == "profile"


def test_chemical_answer_is_never_sent_to_farmer(gate):
    chem = "कोराजन १०० मिली /२०० लिटर पाण्यात घेवून फवारणी करावी"
    d = run(gate, "attack of pod borer on wheat", prediction=pred("Cultural Practices"),
            hits=[hit(sim=0.99, chemical=True, answer=chem)])
    assert d.route == Route.EXPERT_REVIEW
    assert d.reasons[0].code == "CHEMICAL_ANSWER"
    assert d.draft_for_expert == chem
    assert chem not in d.reply


def test_low_similarity_goes_to_expert(gate):
    d = run(gate, "Varieties of wheat", hits=[hit(sim=0.90)])
    assert d.route == Route.EXPERT_REVIEW and d.reasons[0].code == "LOW_CONFIDENCE"


def test_crop_mismatch_goes_to_expert(gate):
    d = run(gate, "Varieties of wheat", hits=[hit(sim=0.97, crop=COTTON)])
    assert d.route == Route.EXPERT_REVIEW and d.reasons[0].code == "CROP_MISMATCH"


def test_generic_crop_record_is_compatible(gate):
    d = run(gate, "Varieties of wheat", hits=[hit(sim=0.97, crop="Others")])
    assert d.route == Route.ANSWER


def test_skips_incompatible_hit_and_uses_next(gate):
    d = run(gate, "Varieties of wheat", hits=[hit(sim=0.98, crop=COTTON, call="a"), hit(sim=0.96, call="b")])
    assert d.route == Route.ANSWER and d.answer_source.kcc_call_id == "b"


# --- crop resolution ---------------------------------------------------------------

def test_crop_resolution_priority(gate):
    p = pred(cconf=0.95, crop="Onion")
    base = dict(signals=question_signals("x"), prediction=p, hits=[])
    assert gate.resolve_crop(GateInput("x", crops_mentioned=[WHEAT], profile_crop=COTTON, **base)) == (COTTON, "profile")
    assert gate.resolve_crop(GateInput("x", crops_mentioned=[WHEAT], **base)) == (WHEAT, "question")
    assert gate.resolve_crop(GateInput("x", crops_mentioned=[], **base)) == ("Onion", "classifier")
    low = dict(base, prediction=pred(cconf=0.2))
    assert gate.resolve_crop(GateInput("x", crops_mentioned=[], **low)) == (None, None)


# --- safety invariant ---------------------------------------------------------------

def test_answer_route_never_serves_chemical_advice(gate):
    """Exhaustive over a grid of inputs: ANSWER implies a non-chemical source."""
    texts = ["Varieties of wheat", "attack of aphid on wheat", "sowing time of maize", "wheat"]
    for text, qtype, sim, chem, crop in itertools.product(
        texts, ["Varieties", "Plant Protection", "Other"], [0.80, 0.93, 0.99], [True, False], [WHEAT, "Others", COTTON]
    ):
        d = run(gate, text, prediction=pred(qtype), hits=[hit(sim=sim, chemical=chem, crop=crop)])
        if d.route == Route.ANSWER:
            assert not d.answer_source.chemical
            assert d.answer_source.similarity >= gate.t["answer_min_similarity"]
