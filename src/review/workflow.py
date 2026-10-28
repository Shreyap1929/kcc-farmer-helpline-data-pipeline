"""
Resolving an expert case, as a LangGraph state graph.

    validate --error--> END
        |--refer------------------------------> refer_reply --> persist --> END
        `--approve_draft / answer --> annotate --needs translation--> localize --> compose --> persist
                                              `--same language-----------------> compose

The expert is the authority on content, so nothing here blocks an answer for being
chemical. What the graph does guard is the step the expert cannot see: translating
their answer into the farmer's language. A translation that adds or drops a number or
names a different crop is discarded and the expert's own words are sent instead, with
the reason recorded on the case. Every answer is also tagged with the Stage 2 answer
policy, so chemical or time-sensitive answers are never marked reusable.
"""
from __future__ import annotations

from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.assistant.composer import rewrite_problems, template_text
from src.assistant.language import detect_language
from src.assistant.sessions import OPEN_STATUSES, SessionStore
from src.assistant.translate import AssistantUnavailable, translate_text
from src.triage.policy import answer_signals

Action = Literal["approve_draft", "answer", "refer"]
ACTIONS = ("approve_draft", "answer", "refer")
MAX_ANSWER_CHARS = 2000

Translator = Callable[[str, str], str]


class ReviewState(TypedDict, total=False):
    case: dict
    action: str
    expert: str
    answer: str
    note: str
    error: str
    answer_language: str
    delivered_text: str
    farmer_reply: str
    checks: dict
    reusable: bool
    result: dict


class ReviewError(ValueError):
    """The expert's submission cannot be applied (bad input or wrong case state)."""


def _validate(state: ReviewState) -> ReviewState:
    case, action = state["case"], state.get("action")
    answer = (state.get("answer") or "").strip()
    if not (state.get("expert") or "").strip():
        return {"error": "expert name is required"}
    if action not in ACTIONS:
        return {"error": f"action must be one of {', '.join(ACTIONS)}"}
    if case["status"] not in OPEN_STATUSES:
        return {"error": f"case is already {case['status']}"}
    if case["status"] == "in_review" and case.get("assigned_to") not in (None, state["expert"]):
        return {"error": f"case is being reviewed by {case['assigned_to']}"}
    if action == "approve_draft":
        if not (case.get("draft") or "").strip():
            return {"error": "this case has no draft to approve"}
        answer = case["draft"].strip()
    if action == "answer" and not answer:
        return {"error": "answer text is required"}
    if len(answer) > MAX_ANSWER_CHARS:
        return {"error": f"answer is longer than {MAX_ANSWER_CHARS} characters"}
    return {"answer": answer, "checks": {}}


def _after_validate(state: ReviewState) -> str:
    if state.get("error"):
        return "error"
    return "refer" if state["action"] == "refer" else "answer"


def _annotate(state: ReviewState) -> ReviewState:
    signals = answer_signals(state["answer"])
    checks = {
        **state.get("checks", {}),
        "chemical": signals.chemical,
        "time_sensitive": signals.time_sensitive,
    }
    return {
        "answer_language": detect_language(state["answer"]),
        "checks": checks,
        # Reuse for future auto-answers is only ever considered for safe, timeless advice.
        "reusable": not (signals.chemical or signals.time_sensitive),
    }


def _needs_translation(state: ReviewState) -> str:
    return "localize" if state["answer_language"] != state["case"]["language"] else "compose"


def _localized(text: str, target: str, translator: Translator, context: str) -> tuple[str, str]:
    """(text to send, outcome). Falls back to the original on any doubt."""
    try:
        candidate = translator(text, target)
    except (AssistantUnavailable, ValueError):
        return text, "fallback:unavailable"
    problems = rewrite_problems(candidate, text, context)
    if problems:
        return text, "fallback:" + ",".join(problems)
    return candidate, "translated"


def _make_localize(translator: Translator):
    def localize(state: ReviewState) -> ReviewState:
        case = state["case"]
        text, outcome = _localized(state["answer"], case["language"], translator,
                                   f"{case['original_text']} {case['english_text']}")
        return {"delivered_text": text, "checks": {**state["checks"], "localization": outcome}}
    return localize


def _compose(state: ReviewState) -> ReviewState:
    case = state["case"]
    checks = dict(state["checks"])
    checks.setdefault("localization", "not_needed")
    text = state.get("delivered_text") or state["answer"]
    header = template_text("EXPERT_ANSWER_HEADER", case["language"], case_id=case["case_id"])
    return {"farmer_reply": f"{header}\n{text}", "checks": checks}


def _make_refer_reply(translator: Translator):
    def refer_reply(state: ReviewState) -> ReviewState:
        case = state["case"]
        reply = template_text("REFERRED", case["language"], case_id=case["case_id"])
        checks = {"localization": "template"}
        note = (state.get("note") or "").strip()
        if note:
            if detect_language(note) != case["language"]:
                note, checks["localization"] = _localized(note, case["language"], translator, case["original_text"])
            reply += f"\n{template_text('EXPERT_NOTE', case['language'])} {note}"
        return {"farmer_reply": reply, "checks": checks, "reusable": False}
    return refer_reply


def _make_persist(store: SessionStore):
    def persist(state: ReviewState) -> ReviewState:
        action = state["action"]
        result = store.resolve_case(
            state["case"]["case_id"],
            status="referred" if action == "refer" else "answered",
            expert=state["expert"],
            resolution={"approve_draft": "approved_draft", "answer": "expert_answer", "refer": "referred"}[action],
            expert_answer=state.get("answer") if action != "refer" else (state.get("note") or None),
            farmer_reply=state["farmer_reply"],
            checks=state["checks"],
            reusable=state.get("reusable", False),
        )
        return {"result": result}
    return persist


def _default_translator(text: str, target: str) -> str:
    return translate_text(text, target, max_tokens=900)


def build_review_graph(store: SessionStore, translator: Translator | None = None):
    translator = translator or _default_translator
    graph = StateGraph(ReviewState)
    graph.add_node("validate", _validate)
    graph.add_node("annotate", _annotate)
    graph.add_node("localize", _make_localize(translator))
    graph.add_node("compose", _compose)
    graph.add_node("refer_reply", _make_refer_reply(translator))
    graph.add_node("persist", _make_persist(store))

    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", _after_validate,
                                {"error": END, "refer": "refer_reply", "answer": "annotate"})
    graph.add_conditional_edges("annotate", _needs_translation, {"localize": "localize", "compose": "compose"})
    graph.add_edge("localize", "compose")
    graph.add_edge("compose", "persist")
    graph.add_edge("refer_reply", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def resolve_case(store: SessionStore, case_id: str, *, action: str, expert: str, answer: str = "",
                 note: str = "", translator: Translator | None = None, graph=None) -> dict:
    """Run the review graph for one submission; returns the updated case."""
    case = store.get_expert_case(case_id)
    if case is None:
        raise KeyError(case_id)
    graph = graph or build_review_graph(store, translator)
    final = graph.invoke({"case": case, "action": action, "expert": (expert or "").strip(),
                          "answer": answer, "note": note})
    if final.get("error"):
        raise ReviewError(final["error"])
    return final["result"]
