# KCC Stage 2 - Triage Core (text)

Builds on the Stage 1 clean master (`data/clean/kcc_mh_clean.parquet`) and turns it
into a working, measured triage system: a farmer's question in Marathi, Hindi or
English goes in; one of the six gate routes from the source of truth (section 7)
comes out, with reasons and sources.

**In this stage:** content policy, dataset views and leakage-aware split, query-type
and crop classifiers, multilingual retrieval, the routing gate, calibration and
evaluation, a FastAPI service and an operator console.

**Not in this stage:** speech in/out, LLM reply writing, LangGraph expert queue with
pause/resume, Postgres/pgvector, Docker. The gate's interfaces were designed for
them (see "Next stage hooks").

Numbers live in the generated reports, not here:
[`views_report.md`](../reports/stage2/views_report.md),
[`embedding_model_probe.md`](../reports/stage2/embedding_model_probe.md),
[`classifier_report.md`](../reports/stage2/classifier_report.md),
[`gate_report.md`](../reports/stage2/gate_report.md).

---

## 1. Runtime flow

```text
question text + caller profile (district, month, optional crop)
   │
   ├─ policy.question_signals ── live-market / live-weather / scheme / dose words (en, mr, hi)
   ├─ crops.detect_crops ─────── crop named in the question (config/crop_lexicon.yaml)
   ├─ embeddings.embed_texts ─── multilingual-e5-base vector (one per call)
   ├─ classifier.predict ─────── query type (13) + crop (30), from the same vector + TF-IDF
   ├─ retrieval.search ───────── FAISS over distinct KB questions, then best answer per
   │                             question with crop/district/season boosts
   └─ gate.decide ────────────── one route + reason codes + reply (+ expert draft)
```

`src/triage/engine.py` wires these together; `src/api/app.py` serves it.

## 2. Content policy (`src/triage/policy.py`)

Stage 1 flags dated content only when the question is one of two exact templates.
In practice many dated answers sit behind free text ("MARKET RATE OF ONION ?"),
and most agronomic answers contain chemical doses. The policy layer reads both the
question and the Marathi answer.

| Signal | Where | Used for |
|---|---|---|
| live market / weather intent | question | LIVE_DATA_POINTER route; KB exclusion |
| scheme intent | question | SCHEME_POINTER route |
| dose / chemical intent | question | EXPERT_REVIEW route (always) |
| dated weather forecast, mandi price, instalment-date claim | answer | KB exclusion |
| dose advice (ml/g/ppm amount; kg/litre/bag with a fertiliser or chemical word; NPK ratio; formulation code) | answer | never auto-answered |
| agrochemical mention (pesticide class, spray, active ingredient) | answer | never auto-answered |

Design notes:
- **Token matching, not `\b`.** Python's `\b` splits Devanagari words at vowel signs.
  The `Lexicon` class matches whole tokens, phrases, and `stem*` prefixes (Marathi
  inflection: `कापसावर` from `कापस*`).
- **Structural dose rule.** Active-ingredient spellings vary endlessly
  (`टेबुकोनाझोल`, `टेब्युकोनाझोल`). A millilitre/gram/ppm quantity is treated as a dose on
  its own; kilogram/litre/bag needs chemical context, so seed rates stay low-risk.
- **Quantities written as words** (`चाळीस मिली`, forty ml) are matched.
- **Forecast phrasing only.** A crop's temperature *requirement* is stable agronomy, so
  the weather detector looks for forecast phrases, not the word "temperature".

Every rule above came from reading sampled rows; the misses that motivated each
one are covered by `tests/test_policy.py`.

## 3. Dataset views and split (`src/triage/views.py`)

- `corpus_tagged.parquet`: all 361,181 master rows, slim columns, `pol_*` tags, `split`.
- `kb_candidates.parquet`: `is_valid_qa & ~pol_time_sensitive` - the only rows retrieval reads.
  Chemical answers *stay* in the KB: they are the expert's draft.
- **Chronological split:** train 2023-11..2024-10 (one full season cycle), valid
  2024-11..12 (calibration only), test 2025-01..07.
- **Realistic vs hard:** hard = questions whose normalised text (`q_key`) never
  appeared earlier. Most test rows are repeats, so both are always reported.
- The retriever takes a `cutoff`; evaluation never lets the KB see the future
  (`tests/test_triage_artifacts.py`).

## 4. Embeddings (`src/triage/embeddings.py`)

`intfloat/multilingual-e5-base`, chosen by a cross-lingual probe over four models
([report](../reports/stage2/embedding_model_probe.md)). Each distinct `q_core` is
embedded once (95,804 texts, ~14 min on CPU) and cached in `data/artifacts/`.
Its similarities sit in a narrow band, which is why thresholds are calibrated.

## 5. Classifiers (`src/triage/classifier.py`)

Per task (query type, crop): TF-IDF + logistic regression (the source-of-truth
baseline), logistic regression on the e5 vector, and their probability average.
The runtime variant and C are picked on *hard* validation macro-F1.

- Training rows are distinct `(q_key, label)` pairs, so the 94k identical weather
  template calls do not drown everything else.
- TF-IDF has no Marathi/Hindi vocabulary; when a question shares no n-gram with the
  training text, the ensemble uses the embedding alone.
- Scores are agreement with noisy dataset labels. The report also measures the
  **label-noise ceiling**: the best agreement any model could reach, because the
  same question text was labelled differently on different calls.

## 6. Retrieval (`src/triage/retrieval.py`)

- FAISS `IndexFlatIP` over distinct KB question texts (exact search; small enough).
- A hit expands to the historical Q&A pairs behind it; per normalised question the
  best answer is chosen by similarity + crop (+0.02) / district / season (+0.005)
  boosts + a tiny popularity term.
- Each hit reports how often the question was asked and how many distinct answers
  it received, so an expert can see when advisors disagreed.

## 7. Gate (`src/triage/gate.py`)

A pure function of (signals, crops, classifier output, hits, profile), so it is
unit-tested with fakes and replayed in batch for evaluation. Order:

1. **LIVE_DATA_POINTER** - live market/weather words, or a confident Market/Weather
   prediction (ignored for dose questions: noisy labels put some dose questions under Weather).
2. **SCHEME_POINTER** - scheme words or a confident scheme prediction; reply points to
   the PM-Kisan (155261) or crop-insurance (14447) helplines, the numbers KCC advisors
   gave most often in the data.
3. **CLARIFY (VAGUE)** - no topic, crop or intent at all.
4. **OUT_OF_SCOPE** - best match below the out-of-scope threshold *and* no farm word,
   crop or dose word in the question (multilingual `AGRI` lexicon). Marathi/Hindi
   questions score lower against the English KB, so similarity alone would wrongly
   reject them.
5. **EXPERT_REVIEW (DOSE_QUESTION)** - always, by team decision.
6. **CLARIFY (CROP_MISSING)** - crop-dependent query type and no crop from profile,
   question, or a confident classifier.
7. **EXPERT_REVIEW**
   - `HIGH_RISK_TOPIC`: confident Plant Protection / Nutrient / Fertiliser / Weed
     prediction. Defence in depth: these topics are chemical 87-94% of the time, and
     some doses are written in ways the answer detector misses (e.g. "झिरो बावन चौतीस"
     for 0:52:34, found while reviewing evaluation pairs).
   - `CHEMICAL_ANSWER`, `CROP_MISMATCH`, `LOW_CONFIDENCE` (below the answer threshold).
8. **ANSWER** - the historical answer verbatim, with KCC call id, date and district.

Invariant (tested exhaustively over an input grid): ANSWER never serves a chemical
answer and never serves below the threshold. A numbers-grounding check
(`policy.ungrounded_numbers`) is already applied, ready for when an LLM rewrites replies.

## 8. Calibration and evaluation (`src/triage/evaluate.py`)

- **"Close" proxy:** character n-gram cosine >= 0.5 between a served answer and the
  real answer on that call. A **proxy** until the golden set exists.
- **Why the target is relative.** The first calibration run aimed for an absolute 80%
  close rate and could not reach it at any threshold: even identical questions got a
  close answer only ~38% of the time. Reading the pairs showed why. Advisors word valid
  answers very differently (one lists wheat varieties, another gives a full cultivation
  sheet). Measured directly, **two real advisors answering the same question are close
  only ~38% of the time**. So the target is now relative: answered cases must be close
  at least 80% as often as two advisors agree with each other.
- **Fail closed.** If no threshold reaches the target, calibration disables the ANSWER
  route (threshold above 1) and says so, instead of silently keeping a default.
- **Out-of-scope threshold:** 1st percentile of best-match similarity over real
  validation questions *without farm words*, the only questions the rule applies to.
- **Baseline:** the same low-risk pool answered with no threshold, so both numbers
  describe the same population.
- **Test:** 40,000 random test-month rows, KB frozen at 2024-12, profile = district +
  month, crop only from the question. Reports route mix, auto-answer coverage, close
  rate vs a no-gate baseline, and safety counts (chemical answers served, time-sensitive
  questions answered from history).
- **Probes:** `config/gate_probes.csv`, 37 hand-written questions across all routes
  and three languages, run through the full engine.

## 9. API and console

```bash
uvicorn src.api.app:app --port 8000      # then open http://localhost:8000
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | operator console (single HTML file, no external assets) |
| GET | `/api/health` | liveness + KB size |
| GET | `/api/meta` | districts, crops, thresholds, example questions |
| POST | `/api/triage` | `{text, district?, crop?, month?}` -> decision |

The console has no CDN or web-font dependencies, so it works offline on demo day.

## 10. Known limitations

- All quality numbers are against historical labels/answers, not a hand-checked
  golden set. The golden corpus remains the biggest credibility item.
- Cross-lingual classification of Marathi/Hindi is weaker than English (see the
  probe table in the classifier report). Translating to English first, or Whisper's
  translate mode, should be compared once speech is added.
- The policy lexicons are hand-built; precision was checked by reading samples,
  recall on rare phrasings is not measured.
- **Threshold sensitivity.** The close-rate curve crosses its target in a flat region, so
  small knowledge-base changes moved the calibrated answer threshold between 0.980 and
  0.9825 during development (enough to flip "Varieties of wheat", best match 0.980). A
  bootstrapped or smoothed choice is a Stage 3 improvement; the threshold is never
  hand-tuned to make an example pass.
- **Detector recall.** Time-sensitive and chemical content is found by hand-built rules.
  Three leaks were found by reading console output and served answers (per-piece mandi
  prices, instalment-date phrasings, deadline phrasings) and fixed; the structural rule
  "a scheme question about a date/status/instalment is time-sensitive" now removes 33k
  rows regardless of how the answer is worded. A golden-set review should look for more.
- Historical answers can be out of date (e.g. a pesticide since banned). Only
  low-risk, non-chemical answers are ever served automatically, and always with
  their date.

## 11. Next stage hooks

- **Expert queue:** `Decision.draft_for_expert`, `answer_source` and `reasons` are the
  payload a LangGraph interrupt needs.
- **LLM replies:** replace `Decision.reply` for ANSWER with a model rewrite of
  `answer_source.answer`, then require `ungrounded_numbers(...) == set()`.
- **Speech:** the API takes text; a Whisper step in front of `/api/triage` is all that
  is needed.
- **pgvector:** `Retriever` only needs `search_batch`; the FAISS index can be swapped.
