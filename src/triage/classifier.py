"""
Query-type and crop classifiers.

Three variants per task, selected on the validation months:
- tfidf      TF-IDF word+char n-grams -> logistic regression (source-of-truth baseline)
- embedding  multilingual-e5 sentence vector -> logistic regression
- ensemble   mean of the two probability vectors

TF-IDF only knows the English call-taker vocabulary; the embedding variant is
what lets a Marathi or Hindi question be classified at all.

Training rows are distinct (q_key, label) pairs from the train months, so the
94k identical "weather" template calls do not drown everything else. Scores
are against the dataset's own noisy labels, never called ground truth.

    python -m src.triage.classifier
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from src.triage.config import path
from src.triage.embeddings import embed_texts, load_question_embeddings

MODEL_FILE = "classifiers.joblib"
VARIANTS = ["tfidf", "embedding", "ensemble"]


class TfidfFeatures:
    def __init__(self):
        self.word = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, lowercase=True)
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True)

    def fit_transform(self, texts):
        return hstack([self.word.fit_transform(texts), self.char.fit_transform(texts)]).tocsr()

    def transform(self, texts):
        return hstack([self.word.transform(texts), self.char.transform(texts)]).tocsr()


class TaskModel:
    """One prediction task (query type or crop) with both feature views."""

    def __init__(self, name: str, c_tfidf: float = 4.0, c_emb: float = 4.0):
        self.name = name
        self.features = TfidfFeatures()
        self.lr_tfidf = LogisticRegression(C=c_tfidf, max_iter=2000, class_weight="balanced")
        self.lr_emb = LogisticRegression(C=c_emb, max_iter=2000, class_weight="balanced")
        self.variant = "ensemble"

    @property
    def classes(self) -> list[str]:
        return list(self.lr_tfidf.classes_)

    def fit(self, texts: list[str], emb: np.ndarray, y: np.ndarray) -> "TaskModel":
        self.lr_tfidf.fit(self.features.fit_transform(texts), y)
        self.lr_emb.fit(emb, y)
        assert list(self.lr_emb.classes_) == self.classes
        return self

    def proba(self, texts: list[str], emb: np.ndarray, variant: str | None = None) -> np.ndarray:
        variant = variant or self.variant
        if variant == "tfidf":
            return self.lr_tfidf.predict_proba(self.features.transform(texts))
        if variant == "embedding":
            return self.lr_emb.predict_proba(emb)
        x = self.features.transform(texts)
        p_emb = self.lr_emb.predict_proba(emb)
        p_ens = 0.5 * (self.lr_tfidf.predict_proba(x) + p_emb)
        # A Marathi/Hindi question shares no n-grams with the English training
        # text; TF-IDF then only returns its class prior, so trust the embedding.
        no_vocab = np.asarray(x.getnnz(axis=1) == 0)
        p_ens[no_vocab] = p_emb[no_vocab]
        return p_ens

    def predict(self, texts: list[str], emb: np.ndarray, variant: str | None = None) -> np.ndarray:
        return np.array(self.classes)[self.proba(texts, emb, variant).argmax(axis=1)]


class QueryClassifier:
    """Runtime wrapper: both tasks, top label + probability + runner-up."""

    def __init__(self, query_type: TaskModel, crop: TaskModel):
        self.query_type = query_type
        self.crop = crop

    def predict_batch(self, texts: list[str], emb: np.ndarray) -> list[dict]:
        out: list[dict] = [{} for _ in texts]
        for key, task in [("query_type", self.query_type), ("crop", self.crop)]:
            probs = task.proba(texts, emb)
            for row, p in zip(out, probs):
                order = np.argsort(-p)
                row[key] = {
                    "label": task.classes[order[0]],
                    "confidence": float(p[order[0]]),
                    "alternatives": [
                        {"label": task.classes[i], "confidence": float(p[i])} for i in order[1:3]
                    ],
                }
        return out

    def predict_one(self, text: str, emb: np.ndarray) -> dict:
        return self.predict_batch([text], emb.reshape(1, -1))[0]

    def save(self) -> None:
        joblib.dump(self, path("artifacts") / MODEL_FILE, compress=3)

    @staticmethod
    def load() -> "QueryClassifier":
        return joblib.load(path("artifacts") / MODEL_FILE)


# ---------------------------------------------------------------------------
# Training and evaluation
# ---------------------------------------------------------------------------

def _classifier_rows() -> pd.DataFrame:
    cols = ["q_core", "q_key", "split", "query_type_model", "crop_model", "flag_incomplete_call", "flag_q_empty"]
    df = pd.read_parquet(path("views") / "corpus_tagged.parquet", columns=cols)
    return df[(df["q_core"].str.len() >= 3) & ~df["flag_incomplete_call"] & ~df["flag_q_empty"]]


def _embeddings_for(texts: pd.Series, index: pd.Series, emb: np.ndarray) -> np.ndarray:
    return np.asarray(emb[index.loc[texts.values].values])


def label_ceiling(part: pd.DataFrame, label_col: str) -> float:
    """
    Best accuracy any model could reach: the same question text often carries
    different labels on different calls, so predict its most common label.
    """
    best = part.groupby(["q_key", label_col]).size().groupby(level=0).max().sum()
    return round(float(best / max(len(part), 1)), 4)


def _scores(y_true, y_pred) -> dict:
    return {
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4),
        "weighted_f1": round(float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "n": int(len(y_true)),
    }


def train_task(df: pd.DataFrame, label_col: str, index: pd.Series, emb: np.ndarray) -> tuple[TaskModel, dict]:
    labelled = df[df[label_col] != ""]
    # Distinct (question, label) pairs: repeats of a template add no information.
    train = labelled[labelled["split"] == "train"].drop_duplicates(["q_key", label_col])
    valid = labelled[labelled["split"] == "valid"]
    test = labelled[labelled["split"] == "test"]
    seen = set(labelled.loc[labelled["split"].isin(["train", "valid"]), "q_key"])
    test_hard = test[~test["q_key"].isin(seen)]
    valid_hard = valid[~valid["q_key"].isin(set(train["q_key"]))]

    print(f"[{label_col}] train pairs {len(train):,} | valid {len(valid):,} | test {len(test):,} (hard {len(test_hard):,})")
    x_train = train["q_core"].tolist()
    e_train = _embeddings_for(train["q_core"], index, emb)

    # Small C grid, chosen on hard validation macro-F1 (unseen questions).
    best, best_f1 = None, -1.0
    e_valid = _embeddings_for(valid_hard["q_core"], index, emb)
    for c in [0.25, 1.0, 4.0, 16.0, 64.0]:
        model = TaskModel(label_col, c_tfidf=c, c_emb=c).fit(x_train, e_train, train[label_col].values)
        f1 = f1_score(valid_hard[label_col], model.predict(valid_hard["q_core"].tolist(), e_valid), average="macro")
        print(f"  C={c:<5} hard-valid macro-F1 (ensemble) = {f1:.4f}")
        if f1 > best_f1:
            best, best_f1 = model, f1

    metrics: dict = {
        "label": label_col, "classes": best.classes, "C": best.lr_tfidf.C, "variants": {},
        "label_ceiling_accuracy": {"test": label_ceiling(test, label_col), "test_hard": label_ceiling(test_hard, label_col)},
        "test_rows_in_conflicting_label_groups": round(float(
            test.groupby("q_key")[label_col].transform("nunique").gt(1).mean()), 4),
    }
    majority = train[label_col].value_counts().idxmax()
    for split_name, part in [("valid", valid), ("valid_hard", valid_hard), ("test", test), ("test_hard", test_hard)]:
        e_part = _embeddings_for(part["q_core"], index, emb)
        texts = part["q_core"].tolist()
        metrics["variants"].setdefault("majority_class", {})[split_name] = _scores(
            part[label_col], np.full(len(part), majority)
        )
        for v in VARIANTS:
            metrics["variants"].setdefault(v, {})[split_name] = _scores(part[label_col], best.predict(texts, e_part, v))

    # Runtime variant: best hard-validation macro-F1.
    best.variant = max(VARIANTS, key=lambda v: metrics["variants"][v]["valid_hard"]["macro_f1"])
    metrics["selected_variant"] = best.variant

    e_test = _embeddings_for(test_hard["q_core"], index, emb)
    pred = best.predict(test_hard["q_core"].tolist(), e_test)
    metrics["per_class_test_hard"] = classification_report(
        test_hard[label_col], pred, output_dict=True, zero_division=0
    )
    metrics["confusion_test_hard"] = {
        "labels": best.classes,
        "matrix": confusion_matrix(test_hard[label_col], pred, labels=best.classes).tolist(),
    }
    return best, metrics


def plot_confusion(metrics: dict, out_file) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = metrics["confusion_test_hard"]["labels"]
    m = np.array(metrics["confusion_test_hard"]["matrix"], dtype=float)
    norm = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(9, 7.5), dpi=130)
    im = ax.imshow(norm, cmap="Greens", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=55, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    for i in range(len(labels)):
        for j in range(len(labels)):
            if norm[i, j] >= 0.05:
                ax.text(j, i, f"{norm[i, j]:.2f}", ha="center", va="center", fontsize=6.5,
                        color="white" if norm[i, j] > 0.6 else "#1d2b1f")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Dataset label (noisy)")
    ax.set_title(f"Query type - hard test months, row-normalised ({metrics['selected_variant']})", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    fig.savefig(out_file)
    plt.close(fig)


def classifier_report(type_metrics: dict, crop_metrics: dict, probe_rows: list[dict]) -> str:
    def table(metrics: dict) -> list[str]:
        rows = [
            "| Variant | Valid macro-F1 | Valid-hard macro-F1 | Test macro-F1 | **Test-hard macro-F1** | Test-hard accuracy |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for v in ["majority_class", *VARIANTS]:
            s = metrics["variants"][v]
            mark = " (selected)" if v == metrics["selected_variant"] else ""
            rows.append(
                f"| {v}{mark} | {s['valid']['macro_f1']:.3f} | {s['valid_hard']['macro_f1']:.3f} | "
                f"{s['test']['macro_f1']:.3f} | **{s['test_hard']['macro_f1']:.3f}** | {s['test_hard']['accuracy']:.3f} |"
            )
        n = metrics["variants"]["tfidf"]
        ceil = metrics["label_ceiling_accuracy"]
        rows.append("")
        rows.append(
            f"Rows: valid {n['valid']['n']:,} (hard {n['valid_hard']['n']:,}), "
            f"test {n['test']['n']:,} (hard {n['test_hard']['n']:,}). Chosen C = {metrics['C']}."
        )
        rows.append("")
        rows.append(
            f"**Label-noise ceiling.** {metrics['test_rows_in_conflicting_label_groups']:.1%} of test rows "
            "belong to a question text that was given different labels on different calls, so even a "
            f"perfect lookup could agree with the labels at most **{ceil['test']:.1%}** of the time "
            f"(realistic) and {ceil['test_hard']:.1%} (hard). This is why realistic scores sit *below* hard ones."
        )
        return rows

    def per_class(metrics: dict, top: int = 14) -> list[str]:
        rep = metrics["per_class_test_hard"]
        items = [(k, v) for k, v in rep.items() if isinstance(v, dict) and k not in ("macro avg", "weighted avg")]
        items.sort(key=lambda kv: -kv[1]["support"])
        rows = ["| Class | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"]
        for k, v in items[:top]:
            rows.append(f"| {k} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1-score']:.2f} | {int(v['support']):,} |")
        return rows

    lines = [
        "# Stage 2 - Query classifiers",
        "",
        "Generated by `python -m src.triage.classifier`.",
        "",
        "> **Read this first.** Every score below is measured against the dataset's own",
        "> `QueryType`/`Crop` labels, which the source of truth documents as noisy. These are",
        "> *agreement with historical call-taker labels*, not accuracy. The golden-set",
        "> evaluation (hand-checked labels) is still to be built.",
        "",
        "**Protocol.** Train on distinct (question, label) pairs from 2023-11..2024-10; pick C and",
        "the runtime variant on the validation months (2024-11..12); report on the untouched",
        "test months (2025-01..07). *Hard* = questions whose normalised text (`q_key`) never",
        "appeared in train or valid. Realistic (all rows) numbers are inflated by repeat",
        "template calls and are shown for completeness only.",
        "",
        "## Query type (13 classes)",
        "",
        *table(type_metrics),
        "",
        "Per class, hard test months, selected variant:",
        "",
        *per_class(type_metrics),
        "",
        "![Confusion matrix](figures/confusion_query_type.png)",
        "",
        f"## Crop ({len(crop_metrics['classes'])} specific crops)",
        "",
        "Rows labelled `Others`, blank or too rare are excluded. At runtime a crop named in",
        "the question (lexicon) wins; the classifier is only a fallback and is ignored below",
        "the configured confidence.",
        "",
        *table(crop_metrics),
        "",
        "## Cross-lingual probes (Marathi / Hindi / romanised)",
        "",
        "The training text is English; farmers will not be. Hand-written probe questions with",
        "the expected query type (`config/gate_probes.csv`, `lang != en`):",
        "",
        "| Variant | Correct | Share |",
        "|---|---:|---:|",
    ]
    for row in probe_rows:
        lines.append(f"| {row['variant']} | {row['correct']}/{row['n']} | {row['share']:.0%} |")
    lines += [
        "",
        "## Notes",
        "",
        "- XGBoost on embeddings (source-of-truth comparison) is not run here: XGBoost is not",
        "  yet a project dependency. Logistic regression on the same embeddings is the",
        "  stand-in; swapping the estimator is a one-line change in `TaskModel`.",
        "- `Other` folds 60 rare labels together, so its F1 is expected to be weak.",
        "",
    ]
    return "\n".join(lines)


def probe_accuracy(clf: QueryClassifier) -> list[dict]:
    from src.triage.config import CONFIG_DIR

    probes = pd.read_csv(CONFIG_DIR / "gate_probes.csv", dtype=str, keep_default_na=False)
    probes = probes[(probes["lang"] != "en") & (probes["expected_query_type"] != "")]
    emb = embed_texts(probes["text"].tolist())
    rows = []
    for v in VARIANTS:
        pred = clf.query_type.predict(probes["text"].tolist(), emb, v)
        correct = int((pred == probes["expected_query_type"].values).sum())
        rows.append({"variant": v, "correct": correct, "n": len(probes), "share": correct / max(len(probes), 1)})
    return rows


def main() -> None:
    df = _classifier_rows()
    index, emb = load_question_embeddings()
    type_model, type_metrics = train_task(df, "query_type_model", index, emb)
    crop_model, crop_metrics = train_task(df, "crop_model", index, emb)
    clf = QueryClassifier(type_model, crop_model)
    clf.save()

    rep = path("reports")
    (rep / "figures").mkdir(parents=True, exist_ok=True)
    plot_confusion(type_metrics, rep / "figures" / "confusion_query_type.png")
    metrics = {"query_type": type_metrics, "crop": crop_metrics, "probes": probe_accuracy(clf)}
    (rep / "classifier_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (rep / "classifier_report.md").write_text(
        classifier_report(type_metrics, crop_metrics, metrics["probes"]), encoding="utf-8"
    )
    print(f"Selected: query_type={type_model.variant}, crop={crop_model.variant}")
    print(f"Wrote {rep / 'classifier_report.md'}")


if __name__ == "__main__":
    # Run through the importable module so pickled models reference
    # src.triage.classifier.TaskModel, not __main__.TaskModel.
    from src.triage.classifier import main as _main

    _main()
