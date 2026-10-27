"""
Configuration loading for the triage core. Paths in config/triage.yaml are
relative to the repository root, so every module works from any cwd.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_DIR / "triage.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(key: str) -> Path:
    """Resolve a path from the `paths:` section, honouring KCC_<KEY>_DIR overrides."""
    override = os.environ.get(f"KCC_{key.upper()}_DIR")
    return Path(override) if override else REPO_ROOT / load_config()["paths"][key]


@lru_cache(maxsize=1)
def load_crop_lexicon() -> dict[str, list[str]]:
    """Canonical crop label (as in crop_clean) -> spoken/written variants."""
    with open(CONFIG_DIR / "crop_lexicon.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["crops"]


def gate_thresholds() -> dict:
    """Calibrated thresholds if the build has run, else the config fallbacks."""
    cfg = dict(load_config()["gate"])
    calibrated = path("artifacts") / "gate_thresholds.json"
    if calibrated.exists():
        cfg.update(json.loads(calibrated.read_text(encoding="utf-8")))
    return cfg
