"""Compose safe farmer-facing replies from gate decisions."""
from __future__ import annotations

import yaml

from src.assistant.config import CONFIG_PATH, get_config, get_groq_client, REPO_ROOT
from src.triage.policy import ungrounded_numbers

TEMPLATE_PATH = REPO_ROOT / "config" / "reply_templates.yaml"


def _templates() -> dict:
    with TEMPLATE_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _value(item, key, default=None):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _source_line(source) -> str:
    call_id = _value(source, "kcc_call_id", "unknown")
    call_date = str(_value(source, "created_on", "date not available"))[:10]
    district = _value(source, "district", "district not available") or "district not available"
    return f"Source: KCC call {call_id}, {call_date}, {district}."


def _rewrite(answer: str, language: str, client) -> str:
    cfg = get_config()["groq"]
    language_names = {"en": "English", "mr": "Marathi", "hi": "Hindi"}
    result = client.chat.completions.create(
        model=cfg["chat_model"],
        temperature=0,
        max_completion_tokens=384,
        messages=[
            {"role": "system", "content": (
                f"Rewrite the supplied historical farmer-help answer in simple {language_names[language]}. "
                "Use only facts present in that answer. Do not add advice, products, quantities, or dates. "
                "Return only the rewritten answer."
            )},
            {"role": "user", "content": answer},
        ],
    )
    return (result.choices[0].message.content or "").strip()


def compose_reply(decision: dict, language: str, *, client=None, case_id: str | None = None) -> str:
    """Rewrite only ANSWER sources; all other routes use fixed reviewed templates."""
    language = language if language in {"en", "mr", "hi"} else "en"
    route = decision.get("route", "EXPERT_REVIEW")
    reasons = decision.get("reasons") or []
    reason_codes = {_value(r, "code") for r in reasons}

    if route == "ANSWER":
        source = decision.get("answer_source")
        historical = _value(source, "answer") or decision.get("reply", "")
        client = client if client is not None else get_groq_client()
        reply = historical
        if client is not None and historical:
            try:
                candidate = _rewrite(historical, language, client)
                if candidate and not ungrounded_numbers(candidate, [historical]):
                    reply = candidate
            except Exception:
                reply = historical
        return f"{reply}\n\n{_source_line(source)}"

    templates = _templates()
    if route == "CLARIFY":
        key = "CLARIFY_CROP_MISSING" if "CROP_MISSING" in reason_codes else "CLARIFY_VAGUE"
    else:
        key = route
    template = templates["templates"].get(key, templates["templates"]["EXPERT_REVIEW"])
    values = {"case_id": case_id or "pending"}
    return template[language].format(**values)

