"""
Invariant tests over the built Stage 2 artifacts. Skipped when the views or
models have not been built (`python -m src.triage.build`).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.triage.config import load_config, path

VIEWS = path("views")
ART = path("artifacts")
needs_views = pytest.mark.skipif(not (VIEWS / "corpus_tagged.parquet").exists(), reason="views not built")
needs_models = pytest.mark.skipif(
    not (ART / "classifiers.joblib").exists() or not (ART / "question_embeddings.npy").exists(),
    reason="models not built",
)


@pytest.fixture(scope="module")
def corpus():
    return pd.read_parquet(VIEWS / "corpus_tagged.parquet",
                           columns=["KCCCallID", "year_month", "split", "q_key", "is_valid_qa",
                                    "flag_dated_answer", "pol_time_sensitive", "pol_risk"])


@pytest.fixture(scope="module")
def kb():
    return pd.read_parquet(VIEWS / "kb_candidates.parquet",
                           columns=["KCCCallID", "year_month", "is_valid_qa", "pol_time_sensitive", "q_core"])


@needs_views
def test_corpus_keeps_every_master_row(corpus):
    assert len(corpus) == 361181
    assert corpus["KCCCallID"].is_unique


@needs_views
def test_split_is_chronological(corpus):
    cfg = load_config()["split"]
    by = corpus.groupby("split")["year_month"].agg(["min", "max"])
    assert by.loc["train", "max"] <= cfg["train_end"]
    assert cfg["train_end"] < by.loc["valid", "min"] and by.loc["valid", "max"] <= cfg["valid_end"]
    assert by.loc["test", "min"] > cfg["valid_end"]


@needs_views
def test_policy_is_a_superset_of_stage1_dated_flag(corpus):
    assert not (corpus["flag_dated_answer"] & ~corpus["pol_time_sensitive"]).any()


@needs_views
def test_kb_excludes_invalid_and_time_sensitive_rows(kb):
    assert kb["is_valid_qa"].all()
    assert not kb["pol_time_sensitive"].any()
    assert (kb["q_core"].str.len() >= 3).all()


@needs_views
@needs_models
def test_retriever_cutoff_never_reads_the_future():
    from src.triage.retrieval import Retriever

    cutoff = load_config()["split"]["train_end"]
    r = Retriever.from_views(cutoff=cutoff)
    assert r.records["year_month"].max() <= cutoff
    assert r.records["qa_key"].is_unique


@needs_views
@needs_models
def test_every_kb_question_has_an_embedding(kb):
    from src.triage.embeddings import load_question_embeddings

    index, emb = load_question_embeddings()
    assert kb["q_core"].isin(index.index).all()
    norms = np.linalg.norm(np.asarray(emb[:1000]), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)
