"""
The routing gate (source of truth, section 7).

Routes, checked in this order:
1. LIVE_DATA_POINTER  market price / weather: history cannot answer "today"
2. SCHEME_POINTER     scheme status, instalments, insurance: official pointer
3. CLARIFY            nothing usable in the question
4. OUT_OF_SCOPE       nothing agricultural and nothing similar in the KB
5. EXPERT_REVIEW      dose/chemical question (always, by decision)
6. CLARIFY            answer depends on a crop nobody has named
7. EXPERT_REVIEW      confident pest/nutrient/fertiliser/weed topic, best historical
                      answer gives chemical advice, crop mismatch, or similarity
                      below the calibrated answer threshold
8. ANSWER             low-risk, close historical answer, shown with its source

The gate is a pure function of its inputs so it can be unit-tested with fakes
and replayed in batch for evaluation. Every decision carries reason codes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from src.triage.config import gate_thresholds, load_config
from src.triage.policy import QuestionSignals, ungrounded_numbers
from src.triage.retrieval import Hit


class Route(str, Enum):
    ANSWER = "ANSWER"
    CLARIFY = "CLARIFY"
    SCHEME_POINTER = "SCHEME_POINTER"
    LIVE_DATA_POINTER = "LIVE_DATA_POINTER"
    EXPERT_REVIEW = "EXPERT_REVIEW"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass
class Reason:
    code: str
    detail: str


@dataclass
class Decision:
    route: Route
    reasons: list[Reason]
    reply: str
    draft_for_expert: str | None = None
    answer_source: Hit | None = None
    crop: str | None = None
    crop_source: str | None = None
    grounded: bool | None = None
    sources: list[Hit] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["route"] = self.route.value
        return d


@dataclass
class GateInput:
    text: str
    signals: QuestionSignals
    crops_mentioned: list[str]
    prediction: dict  # QueryClassifier.predict_one output
    hits: list[Hit]
    profile_crop: str | None = None


GENERIC_CROPS = {"", "Others", "Other"}


class Gate:
    def __init__(self, thresholds: dict | None = None):
        self.t = thresholds or gate_thresholds()
        self.pointers = load_config()["pointers"]
        self.crop_dependent = set(self.t["crop_dependent_types"])
        self.expert_only = set(self.t["expert_only_types"])

    # -- helpers -----------------------------------------------------------

    def resolve_crop(self, inp: GateInput) -> tuple[str | None, str | None]:
        """Caller profile beats the question text, which beats the classifier."""
        if inp.profile_crop:
            return inp.profile_crop, "profile"
        if inp.crops_mentioned:
            return inp.crops_mentioned[0], "question"
        crop = inp.prediction["crop"]
        if crop["confidence"] >= self.t["crop_min_confidence"]:
            return crop["label"], "classifier"
        return None, None

    @staticmethod
    def _crop_compatible(hit: Hit, crop: str | None) -> bool:
        return crop is None or hit.crop in GENERIC_CROPS or hit.crop == crop

    def _live_reply(self, market: bool) -> str:
        if market:
            return (
                "Old helpline records cannot tell today's market price. Please check today's rate "
                "with your nearest APMC market committee or on agmarknet.gov.in, or call the Kisan "
                f"Call Centre on {self.pointers['kcc_helpline']}."
            )
        return (
            "Weather changes every day, so past answers cannot be reused. Please check the latest "
            "IMD forecast for your taluka (mausam.imd.gov.in or the Meghdoot app), or call the "
            f"Kisan Call Centre on {self.pointers['kcc_helpline']}."
        )

    def _scheme_reply(self, signals: QuestionSignals) -> str:
        terms = " ".join(signals.scheme)
        if any(t in terms for t in ("विमा", "बीमा", "insurance", "bima", "vima", "pmfby", "compensation", "भरपाई")):
            return (
                "For crop insurance claims and status, call the crop insurance helpline "
                f"{self.pointers['crop_insurance_helpline']} or contact your insurance company / "
                "taluka agriculture office. Instalment and claim status can only be confirmed there."
            )
        if any(t in terms for t in ("kisan", "किसान", "हप्त", "किस्त", "hapta", "hafta", "install", "instal", "kyc", "केवायसी", "नमो", "namo")):
            return (
                "Instalment status is personal and changes over time, so it must be checked live: "
                f"use the PM-Kisan helpline {self.pointers['pm_kisan_helpline']} or the "
                "'Know your status' page on pmkisan.gov.in. For Namo Shetkari, contact your "
                "taluka agriculture office."
            )
        return (
            "Scheme rules, dates and eligibility change, so please confirm with your taluka "
            "agriculture office or the Kisan Call Centre on "
            f"{self.pointers['kcc_helpline']}."
        )

    # -- main --------------------------------------------------------------

    def decide(self, inp: GateInput) -> Decision:
        s, pred, hits = inp.signals, inp.prediction, inp.hits
        qtype = pred["query_type"]
        top_sim = hits[0].similarity if hits else 0.0
        crop, crop_source = self.resolve_crop(inp)
        base = {"crop": crop, "crop_source": crop_source, "sources": hits}

        if not inp.text.strip():
            return Decision(Route.CLARIFY, [Reason("EMPTY", "No question was heard.")],
                            "I did not catch the question. Could you say it again?", **base)

        # Classifier-only shortcuts (no keyword) need an in-domain question:
        # otherwise "who won the cricket match" could land on a scheme pointer.
        in_domain = top_sim >= self.t["out_of_scope_max_similarity"]

        # 1. Live data
        live_type = in_domain and not s.dose and qtype["label"] in ("Market Information", "Weather") \
            and qtype["confidence"] >= self.t["live_market_type_confidence"]
        if s.is_live or live_type:
            reasons = []
            if s.live_market:
                reasons.append(Reason("LIVE_MARKET_INTENT", f"Market-price words: {', '.join(s.live_market)}"))
            if s.live_weather:
                reasons.append(Reason("LIVE_WEATHER_INTENT", f"Weather words: {', '.join(s.live_weather)}"))
            if not reasons:
                reasons.append(Reason("LIVE_TYPE_PREDICTED",
                                      f"Classifier: {qtype['label']} ({qtype['confidence']:.0%})"))
            market = bool(s.live_market) or (not s.live_weather and qtype["label"] == "Market Information")
            return Decision(Route.LIVE_DATA_POINTER, reasons, self._live_reply(market), **base)

        # 2. Scheme status
        scheme_type = in_domain and qtype["label"] == "Government Schemes" \
            and qtype["confidence"] >= self.t["scheme_type_confidence"]
        if s.scheme or scheme_type:
            reasons = [Reason("SCHEME_INTENT", f"Scheme words: {', '.join(s.scheme)}")] if s.scheme else \
                [Reason("SCHEME_TYPE_PREDICTED", f"Classifier: Government Schemes ({qtype['confidence']:.0%})")]
            return Decision(Route.SCHEME_POINTER, reasons, self._scheme_reply(s), **base)

        # 3. Nothing to work with
        if not s.content_tokens and not inp.crops_mentioned and not s.dose:
            return Decision(Route.CLARIFY, [Reason("VAGUE", "No crop, problem or topic in the question.")],
                            "Which crop is this about, and what problem do you see?", **base)

        # 4. Off-topic
        agri_signal = bool(inp.crops_mentioned or s.dose or s.agri or inp.profile_crop)
        if top_sim < self.t["out_of_scope_max_similarity"] and not agri_signal:
            return Decision(
                Route.OUT_OF_SCOPE,
                [Reason("OUT_OF_SCOPE", f"Nothing similar in the helpline records (best match {top_sim:.2f}).")],
                "This helpline answers farming questions: crops, pests, fertilisers, seeds and schemes. "
                f"For other help please call {self.pointers['kcc_helpline']}.",
                **base,
            )

        # The expert's draft should be about the caller's crop when one is known.
        candidates = [h for h in hits if self._crop_compatible(h, crop)]
        draft_hit = candidates[0] if candidates else (hits[0] if hits else None)
        draft = draft_hit.answer if draft_hit else None

        # 5. Dose questions always go to an expert
        if s.dose:
            return Decision(
                Route.EXPERT_REVIEW,
                [Reason("DOSE_QUESTION", f"Asks about chemicals or doses: {', '.join(s.dose)}")],
                "This needs an expert because it involves a chemical or fertiliser dose. "
                "An agriculture expert will review it and reply.",
                draft_for_expert=draft, answer_source=draft_hit, **base,
            )

        # 6. Answer depends on the crop
        if crop is None and qtype["label"] in self.crop_dependent:
            return Decision(
                Route.CLARIFY,
                [Reason("CROP_MISSING", f"{qtype['label']} advice depends on the crop, and none was named.")],
                "Which crop is this about? And how old is the crop (days after sowing)?",
                **base,
            )

        # Defence in depth: a confident pest/disease/nutrient/weed topic goes to an
        # expert even if the closest answer text shows no chemical (doses are
        # sometimes written in ways the answer detector cannot see).
        if qtype["label"] in self.expert_only and qtype["confidence"] >= self.t["expert_type_confidence"]:
            return Decision(
                Route.EXPERT_REVIEW,
                [Reason("HIGH_RISK_TOPIC",
                        f"{qtype['label']} ({qtype['confidence']:.0%}): advice here usually involves chemicals.")],
                "An agriculture expert will check this for your crop and reply.",
                draft_for_expert=draft, answer_source=draft_hit, **base,
            )

        if not candidates:
            return Decision(
                Route.EXPERT_REVIEW,
                [Reason("CROP_MISMATCH", f"Similar past questions are about other crops, not {crop}.")],
                "An agriculture expert will review your question and reply.",
                draft_for_expert=draft, **base,
            )
        best = candidates[0]

        # 7. Chemical answers and weak matches go to the expert queue
        if best.chemical:
            return Decision(
                Route.EXPERT_REVIEW,
                [Reason("CHEMICAL_ANSWER", "The closest past answer recommends a chemical or dose.")],
                "An agriculture expert will check the right product and dose for you and reply.",
                draft_for_expert=best.answer, answer_source=best, **base,
            )
        if best.similarity < self.t["answer_min_similarity"]:
            return Decision(
                Route.EXPERT_REVIEW,
                [Reason("LOW_CONFIDENCE",
                        f"Closest past question is not close enough ({best.similarity:.3f} < "
                        f"{self.t['answer_min_similarity']:.3f}).")],
                "An agriculture expert will review your question and reply.",
                draft_for_expert=best.answer, answer_source=best, **base,
            )

        # 8. Answer from history, with its source
        reply = best.answer
        missing = ungrounded_numbers(reply, [best.answer])
        reasons = [Reason("RETRIEVED_LOW_RISK",
                          f"Close past answer ({best.similarity:.3f}) with no chemical advice; "
                          f"asked {best.times_asked}x, {best.distinct_answers} answer variant(s).")]
        return Decision(Route.ANSWER, reasons, reply, answer_source=best, grounded=not missing, **base)
