"""Compose safe farmer-facing replies from gate decisions."""
from __future__ import annotations

import yaml

from src.assistant.config import REPO_ROOT, chat_options, get_groq_client
from src.triage.config import load_config
from src.triage.crops import detect_crops
from src.triage.policy import numbers_in, ungrounded_numbers

TEMPLATE_PATH = REPO_ROOT / "config" / "reply_templates.yaml"


def _templates() -> dict:
    with TEMPLATE_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def template_text(key: str, language: str, **values) -> str:
    """A fixed reply in the farmer's language, with helpline numbers filled in."""
    language = language if language in LANGUAGE_NAMES else "en"
    templates = _templates()["templates"]
    template = templates.get(key, templates["EXPERT_REVIEW"])
    return template[language].format(**{**load_config()["pointers"], **values})


def _value(item, key, default=None):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


_SOURCE_LABELS = {
    "en": ("Source: KCC call", "date not available", "district not available"),
    "mr": ("स्रोत: KCC कॉल", "तारीख उपलब्ध नाही", "जिल्हा उपलब्ध नाही"),
    "hi": ("स्रोत: KCC कॉल", "तारीख उपलब्ध नहीं", "जिला उपलब्ध नहीं"),
}
LANGUAGE_NAMES = {"en": "English", "mr": "Marathi", "hi": "Hindi"}


def _source_line(source, language: str = "en") -> str:
    label, no_date, no_district = _SOURCE_LABELS.get(language, _SOURCE_LABELS["en"])
    call_id = _value(source, "kcc_call_id", "unknown")
    call_date = str(_value(source, "created_on", None) or no_date)[:10]
    district = _value(source, "district", None) or no_district
    return f"{label} {call_id}, {call_date}, {district}."


def _rewrite(answer: str, language: str, client, *, question: str = "", crop: str = "") -> str:
    context = [f"Farmer's question: {question}"] if question else []
    if crop:
        context.append(f"Crop: {crop}")
    result = client.chat.completions.create(
        **chat_options(),
        max_completion_tokens=384,
        messages=[
            {"role": "system", "content": (
                f"Rewrite the supplied historical farmer-help answer in simple {LANGUAGE_NAMES[language]}. "
                "Use only facts present in that answer. Do not add advice, products, quantities, or dates. "
                "Keep every number, variety name and crop name exactly as given; name the crop from the "
                "question when the answer leaves it implicit. Return only the rewritten answer."
            )},
            {"role": "user", "content": "\n".join(context + [f"Historical answer: {answer}"])},
        ],
    )
    return (result.choices[0].message.content or "").strip()


def rewrite_problems(candidate: str, historical: str, context: str = "") -> list[str]:
    """
    Reasons to reject an LLM rewrite. The historical answer is always a safe fallback,
    so any doubt rejects: an added or dropped number, or a crop the source never names
    (a live run turned groundnut into "black gram" with every number intact).
    """
    problems = []
    if not candidate:
        return ["empty"]
    if ungrounded_numbers(candidate, [historical]):
        problems.append("added_number")
    if numbers_in(historical) - numbers_in(candidate):
        problems.append("dropped_number")
    if set(detect_crops(candidate)) - set(detect_crops(f"{historical} {context}")):
        problems.append("changed_crop")
    if len(candidate) < 0.25 * len(historical):
        problems.append("too_short")
    return problems


def compose_reply(decision: dict, language: str, *, client=None, case_id: str | None = None) -> str:
    """Rewrite only ANSWER sources; all other routes use fixed reviewed templates."""
    language = language if language in {"en", "mr", "hi"} else "en"
    route = decision.get("route", "EXPERT_REVIEW")
    reasons = decision.get("reasons") or []
    reason_codes = {_value(r, "code") for r in reasons}

    if route == "ANSWER":
        source = decision.get("answer_source")
        historical = _value(source, "answer") or decision.get("reply", "")
        question = (decision.get("query") or {}).get("text") or _value(source, "question", "") or ""
        # "Soybean (bhat)" -> "Soybean": the local alias misleads the model (bhat is rice in Marathi).
        crop = (decision.get("crop") or _value(source, "crop", "") or "").split("(")[0].strip()
        client = client if client is not None else get_groq_client()
        reply = historical
        if client is not None and historical:
            try:
                candidate = _rewrite(historical, language, client, question=question, crop=crop)
                if not rewrite_problems(candidate, historical, f"{question} {crop}"):
                    reply = candidate
            except Exception:
                reply = historical
        return f"{reply}\n\n{_source_line(source, language)}"

    if route == "CLARIFY":
        key = "CLARIFY_CROP_MISSING" if "CROP_MISSING" in reason_codes else "CLARIFY_VAGUE"
    else:
        key = route
    return template_text(key, language, case_id=case_id or "pending")

