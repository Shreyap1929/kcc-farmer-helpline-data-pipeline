"""
Stage 5 answerability: features, the answer policy, and how the gate uses it.
Fake hits, classifier output and closeness; no data files or models needed.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.triage.answerability import FEATURES, AnswerPolicy, feature_rows, is_devanagari
from src.triage.answerability_train import lowest_feasible, script_threshold
from src.triage.config import load_config
from src.triage.crops import detect_crops
from src.triage.gate import Gate, GateInput, Route
from src.triage.policy import question_signals
from src.triage.retrieval import Hit

WHEAT = "Wheat"
MR_VARIETIES = "गव्हाच्या सुधारित जाती कोणत्या आहेत?"


def pred(qtype="Varieties", qconf=0.9, crop=WHEAT, cconf=0.3):
    return {
        "query_type": {"label": qtype, "confidence": qconf, "alternatives": []},
        "crop": {"label": crop, "confidence": cconf, "alternatives": []},
    }


def hit(sim=0.95, chemical=False, crop=WHEAT, answer="गव्हाचे सुधारित वाण: फुले समाधान, एमएसीएस 6222.",
        call="1", qtype="Varieties"):
    return Hit(
        kcc_call_id=call, question="VARIETIES OF WHEAT ?", answer=answer, similarity=sim, score=sim,
        created_on="2024-11-12", district="Pune", crop=crop, season="rabi", query_type=qtype,
        answer_lang="marathi", risk="chemical" if chemical else "low", chemical=chemical,
        times_asked=40, distinct_answers=3, answer_share=0.6, source_file="mh-2024-11.csv", source_row=7,
    )


class FakeCloseness:
    """Exact-match closeness: 1 if the two answers are identical."""

    def __call__(self, a, b):
        return np.array([float(x == y) for x, y in zip(a, b)])


class FakeModel:
    def __init__(self, p):
        self.p = p
        self.seen = []

    def predict_proba(self, x):
        self.seen.append(x)
        return np.array([[1 - self.p, self.p]] * len(x))


def model_policy(p, threshold=0.5, min_similarity=0.85):
    return AnswerPolicy(mode="model", threshold=threshold, min_similarity=min_similarity,
                        model=FakeModel(p), closeness=FakeCloseness())


@pytest.fixture(scope="module")
def thresholds():
    t = dict(load_config()["gate"])
    t.update(answer_min_similarity=0.98, out_of_scope_max_similarity=0.82)
    return t


def run(gate, text, prediction=None, hits=None, profile_crop=None):
    return gate.decide(GateInput(
        text=text, signals=question_signals(text), crops_mentioned=detect_crops(text),
        prediction=prediction or pred(), hits=[hit()] if hits is None else hits, profile_crop=profile_crop,
    ))


# --- features ------------------------------------------------------------------

def test_feature_vector_matches_feature_names():
    hits = [hit(0.9, call="1"), hit(0.88, call="2"), hit(0.8, call="3", answer="other")]
    x = feature_rows([(MR_VARIETIES, pred(), WHEAT, hits[0], hits, hits)], FakeCloseness())
    assert x.shape == (1, len(FEATURES))
    f = dict(zip(FEATURES, x[0]))
    assert f["sim1"] == pytest.approx(0.9)
    assert f["sim1_dev"] == pytest.approx(0.9) and f["devanagari"] == 1.0
    assert f["gap"] == pytest.approx(0.02)
    # one of the two other answers is identical to the best one
    assert f["consensus_mean"] == pytest.approx(0.5) and f["consensus_max"] == 1.0
    assert f["crop_known"] == 1.0 and f["crop_match"] == 1.0 and f["type_match"] == 1.0


def test_latin_question_has_no_devanagari_shift():
    h = hit(0.97)
    f = dict(zip(FEATURES, feature_rows([("varieties of wheat", pred(), None, h, [h], [h])], FakeCloseness())[0]))
    assert f["sim1_dev"] == 0.0 and f["devanagari"] == 0.0
    assert f["crop_known"] == 0.0 and f["consensus_mean"] == 0.0 and f["gap"] == pytest.approx(0.97)


def test_is_devanagari():
    assert is_devanagari(MR_VARIETIES) and not is_devanagari("kapus var mashi")


# --- the policy ----------------------------------------------------------------

def test_policy_answers_above_its_cutoff():
    h = hit(0.9)
    v = model_policy(0.7).decide(MR_VARIETIES, pred(), WHEAT, h, [h], [h])
    assert v.answer and v.probability == pytest.approx(0.7)


def test_policy_refuses_below_its_cutoff():
    h = hit(0.9)
    v = model_policy(0.3).decide(MR_VARIETIES, pred(), WHEAT, h, [h], [h])
    assert not v.answer and "30%" in v.detail


def test_similarity_floor_overrides_a_confident_model():
    h = hit(0.84)
    v = model_policy(0.99).decide(MR_VARIETIES, pred(), WHEAT, h, [h], [h])
    assert not v.answer and "too far" in v.detail


def test_per_script_policy_uses_the_question_script():
    policy = AnswerPolicy(mode="per_script", threshold=0.9, min_similarity=0.85,
                          script_thresholds={"latin": 0.98, "devanagari": 0.9})
    h = hit(0.93)
    assert policy.decide(MR_VARIETIES, pred(), WHEAT, h, [h], [h]).answer
    assert not policy.decide("varieties of wheat", pred(), WHEAT, h, [h], [h]).answer


def test_load_ignores_a_policy_that_was_not_adopted(tmp_path, monkeypatch):
    monkeypatch.setenv("KCC_ARTIFACTS_DIR", str(tmp_path))
    assert AnswerPolicy.load() is None
    AnswerPolicy(mode="none", threshold=1.01, min_similarity=0.85).save()
    assert AnswerPolicy.load() is None
    AnswerPolicy(mode="per_script", threshold=0.9, min_similarity=0.85,
                 script_thresholds={"latin": 0.98, "devanagari": 0.9}).save()
    assert AnswerPolicy.load().mode == "per_script"


# --- the gate with a policy ----------------------------------------------------

def test_without_a_policy_the_gate_is_unchanged(thresholds):
    d = run(Gate(thresholds), MR_VARIETIES, hits=[hit(0.9)])
    assert d.route == Route.EXPERT_REVIEW and d.reasons[0].code == "LOW_CONFIDENCE"
    assert d.answerability is None


def test_policy_can_answer_a_devanagari_question_below_the_english_cutoff(thresholds):
    d = run(Gate(thresholds, answer_policy=model_policy(0.8)), MR_VARIETIES, hits=[hit(0.9)])
    assert d.route == Route.ANSWER and d.reasons[0].code == "RETRIEVED_LOW_RISK"
    assert d.answerability == pytest.approx(0.8)
    assert d.answer_source.kcc_call_id == "1"


def test_policy_refusal_keeps_the_low_confidence_code(thresholds):
    # Expert-answer reuse (src/review/reviewed_answers.py) keys on LOW_CONFIDENCE.
    d = run(Gate(thresholds, answer_policy=model_policy(0.1)), MR_VARIETIES, hits=[hit(0.99)])
    assert d.route == Route.EXPERT_REVIEW and d.reasons[0].code == "LOW_CONFIDENCE"
    assert d.draft_for_expert == hit().answer


@pytest.mark.parametrize("text,hits,prediction,code", [
    ("dose of urea for wheat", [hit(0.99)], None, "DOSE_QUESTION"),
    ("गव्हावर कोणते औषध फवारावे?", [hit(0.99)], None, "DOSE_QUESTION"),
    ("varieties of wheat", [hit(0.99, chemical=True)], None, "CHEMICAL_ANSWER"),
    ("wheat leaves turning yellow", [hit(0.99)], pred("Plant Protection", 0.9), "HIGH_RISK_TOPIC"),
    ("varieties of wheat", [hit(0.99, crop="Cotton (Kapas)")], None, "CROP_MISMATCH"),
])
def test_safety_rules_run_before_the_policy(thresholds, text, hits, prediction, code):
    policy = model_policy(1.0)
    d = run(Gate(thresholds, answer_policy=policy), text, prediction=prediction, hits=hits)
    assert d.route == Route.EXPERT_REVIEW and d.reasons[0].code == code
    assert policy.model.seen == []  # never consulted


def test_live_and_scheme_questions_never_reach_the_policy(thresholds):
    policy = model_policy(1.0)
    gate = Gate(thresholds, answer_policy=policy)
    assert run(gate, "onion rate today").route == Route.LIVE_DATA_POINTER
    assert run(gate, "पीएम किसान हप्ता कधी येणार").route == Route.SCHEME_POINTER
    assert policy.model.seen == []


# --- operating-point selection ---------------------------------------------------

def test_lowest_feasible_requires_target_in_each_script(monkeypatch):
    import src.triage.answerability_train as tr

    monkeypatch.setattr(tr, "MIN_ANSWERED", {"latin": 2, "devanagari": 1})
    score = np.array([0.9, 0.8, 0.7, 0.6, 0.9, 0.4])
    close = np.array([1, 1, 0, 0, 1, 0], bool)
    script = np.array(["latin"] * 4 + ["devanagari"] * 2)
    grid = np.round(np.arange(0.3, 0.95, 0.1), 2)
    # At 0.4 Devanagari answers half wrong; at 0.5 Latin is 2/4; first feasible at 0.8 (all close).
    assert lowest_feasible(score, close, script, 0.75, grid) == pytest.approx(0.8)
    assert lowest_feasible(score, close, script, 1.01, grid) is None


def test_script_threshold_disables_when_target_unreachable():
    sim = np.array([0.95, 0.9, 0.85])
    assert script_threshold(sim, np.array([1, 0, 0], bool), 0.9, 1) == pytest.approx(0.9025, abs=0.003)
    assert script_threshold(sim, np.array([0, 0, 0], bool), 0.5, 1) == 1.01
