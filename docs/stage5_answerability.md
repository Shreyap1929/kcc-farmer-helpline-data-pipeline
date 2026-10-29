# Stage 5 - Answerability model

Source of truth, section 8B: "predict the probability that the best retrieved answer is
actually good ... must beat a simple confidence-threshold rule; if it does not, report
that honestly." Results: [reports/stage5/answerability_report.md](../reports/stage5/answerability_report.md).

## 1. Why

The Stage 2 gate answers a low-risk question when the closest past question is at least
0.9825 similar. That one number was calibrated on English call-taker summaries. Marathi
and Hindi farmer questions reach the right record at 0.86-0.91, so they were never
answered (Stage 4 parity: 0/80 each). The model replaces that comparison and nothing
else: it is consulted only after every safety rule (live data, schemes, doses, high-risk
topics, crop checks, chemical answers) has passed the question through.

## 2. What was built

| Piece | Where |
|---|---|
| Features + runtime policy (`model`, `per_script` or `none`) | `src/triage/answerability.py` |
| Gate hook: policy replaces the similarity check; refusals keep `LOW_CONFIDENCE` so expert-answer reuse is unchanged | `src/triage/gate.py` |
| Training, evaluation, pre-registered decision, report | `src/triage/answerability_train.py` |
| Engine loads the adopted policy (`gate.use_answer_policy` in `config/triage.yaml`) | `src/triage/engine.py` |
| Console: "answer fit" bar when a model policy is active | `src/api/static/index.html` |
| Tests (features, policy, gate safety order, operating-point selection) | `tests/test_answerability.py` (19) |

Features (15): best similarity (and a Devanagari-only copy), gap to the second match,
mean similarity, **answer consensus** (char n-gram closeness of the other retrieved
answers to the best one), popularity and answer share of the best question, crop and
query-type agreement, classifier confidence, script, length.

Data: the low-risk pool, i.e. questions that reach this one decision when the gate runs
with the answer threshold open. English: real validation-month questions (train-only
KB) for training, the Stage 2 test sample for testing. Marathi/Hindi: 600 + 400 pool
questions per language rephrased as a farmer would ask (Groq gpt-oss, cached in
`data/runtime/answerability_rephrasings.json`) and run through the production
Devanagari path. Label everywhere: the served answer is close to the real answer on that
call (Stage 2 proxy). Folds are grouped by question, so a question and its rephrasings
never sit on both sides.

## 3. Result

| Test months | Stage 2 rule | Logistic model |
|---|---:|---:|
| English answered / close rate | 1,112 / **27.2%** | 684 / **40.1%** |
| English *hard* (never seen before 2025) close rate | 13.1% | 23.8% |
| Marathi + Hindi answered / close rate | 0 / - | 59 / 32.2% |
| Close answers, all languages | **302** | 293 |
| Stage 4 parity set answered (mr, hi), same as English | 0, 0 | 6 (4 same), 13 (7 same) |
| Dose questions answered | 0 | 0 |

Validation AUC: model 0.82 (Devanagari 0.74-0.76) vs similarity alone 0.71 (0.66).

**Decision by the pre-registered rule: keep the Stage 2 rule**, because the model gives
9 fewer close answers in total (criterion b). The artifact is saved with `mode: none`, so
production behaves exactly as before.

## 4. Reading the result

- The model is a much better judge of answer quality: at every coverage level it
  answers more accurately (figure in the report), and it is the only policy that
  answers any Marathi/Hindi question at the target rate.
- The Stage 2 rule misses its own target on the test months (27.2% close vs 30.3%).
  The rule written for this stage compared close-answer counts without checking that,
  which favours a baseline that answers more, less accurately. The rule was fixed
  before the run, so it was not changed after seeing the numbers.
- Adopting the model is therefore a product choice, not a statistical one: about 40%
  fewer English auto-answers, each much more likely to match an advisor, plus the
  first Marathi/Hindi auto-answers. 8 of the 19 parity-set answers differ from the
  English answer, so Devanagari answers are still the weakest part.
- Caveats: the "close" label is a proxy (no golden set yet); Devanagari questions are
  machine-written; Devanagari test numbers rest on 59 answered cases (CI 20-44%).

## 5. Next

1. Team decision: adopt the model (needs a criterion that requires the target, then a
   rerun) or keep the Stage 2 rule.
2. Golden set: hand-check a few hundred answered cases so the label stops being a proxy.
3. Real farmer recordings to replace the machine rephrasings.
