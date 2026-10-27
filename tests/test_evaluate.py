"""
Unit tests for the calibration helpers (no data needed).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.triage.evaluate import choose_answer_threshold


def test_picks_lowest_threshold_meeting_target():
    rng = np.random.default_rng(0)
    sim = rng.uniform(0.8, 1.0, 5000)
    # Closeness probability rises with similarity.
    close = rng.uniform(0, 1, 5000) < (sim - 0.8) * 3
    t, curve = choose_answer_threshold(sim, close, target=0.45)
    assert t is not None
    assert curve.loc[curve["threshold"] == t, "close_rate"].item() >= 0.45
    below = curve[curve["threshold"] < t]
    assert (below["close_rate"] < 0.45).all()


def test_returns_none_when_target_is_unreachable():
    sim = np.linspace(0.8, 1.0, 1000)
    close = np.zeros(1000, dtype=bool)
    t, _ = choose_answer_threshold(sim, close, target=0.3)
    assert t is None


def test_requires_minimum_support():
    sim = np.r_[np.full(950, 0.85), np.full(50, 0.999)]
    close = np.r_[np.zeros(950, dtype=bool), np.ones(50, dtype=bool)]
    t, _ = choose_answer_threshold(sim, close, target=0.9, min_answered=200)
    assert t is None
