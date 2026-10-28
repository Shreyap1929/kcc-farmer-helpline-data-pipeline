"""Assistant configuration and lazy Groq client construction.

Secrets are loaded only when a Groq operation is requested; importing the package
or running local tests never reads the project's .env file.
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "assistant.yaml"


@lru_cache(maxsize=1)
def get_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def get_groq_client():
    """Return a Groq client when configured, otherwise None; never log the key."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
        api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    from groq import Groq

    return Groq(api_key=api_key, timeout=get_config()["groq"]["timeout_seconds"], max_retries=0)
