# KCC Farmer Helpline Assistant - Final Report

Amir and Shreya, final-year AI & Data Science project, 2026-10-29.
Code: this repository. Every number below comes from a generated report in `reports/`
(linked); none are typed by hand.

## 1. The problem

India's Kisan Call Centre (KCC) answers farmers' questions by phone. The same questions
come in again and again (varieties, sowing time, schemes, prices), while risky ones
(pesticide doses, disease outbreaks) need an expert. This project is a **triage and
decision-support assistant** for such a helpline: a farmer asks by voice or text in
Marathi, Hindi or English, and the system either answers from a past expert answer (and
shows its source), asks a follow-up, points to a live official source, or hands the case
to a human expert with a ready summary. It never gives chemical-dose advice on its own
and never claims agronomic verification.

## 2. Data

361,181 cleaned Maharashtra KCC records, Nov 2023 to Jul 2025, from data.gov.in
(GODL-India licence, [attribution](data_licence.md)). Findings that shaped the design:

- The question text is the call-taker's English summary, not the farmer's words, while
  answers are mostly Marathi. Runtime questions arrive in Marathi/Hindi speech.
- One upstream file (Feb 2024) is a byte-identical copy of Jan 2024 and was excluded.
- 46,450 rows carry dated content (mandi prices, forecasts, instalment dates) that the
  Stage 1 flags missed; they are kept out of the answer base.
- Labels are noisy: 62.7% of test rows share a question text labelled differently on
  other calls, and two real advisors give a "close" answer to the same question only
  ~38% of the time. Every quality target is set relative to that.

## 3. System

```text
voice note ─► Groq Whisper ─► language detection ─┐
typed text ───────────────────────────────────────┤
                                                  ▼
   policy signals (live / scheme / dose words, en mr hi)  +  crop detection
   e5 embedding ─► query-type & crop classifiers
               ─► FAISS retrieval over 126k past Q&A (crop/district/season boosts)
                                                  ▼
   GATE: LIVE_DATA_POINTER · SCHEME_POINTER · CLARIFY · OUT_OF_SCOPE
         EXPERT_REVIEW (doses, high-risk topics, chemical answers, crop mismatch)
         ANSWER only if the answerability model says the past answer fits
                                                  ▼
   reply composer (grounded LLM rewrite: numbers and crop must survive) ─► TTS
   expert case ─► expert desk ─► LangGraph resolution ─► reply back to the farmer
   safe expert answers ─► reused for the same question in the same language
```

| Layer | Choice | Why (vs the original plan) |
|---|---|---|
| STT | Groq Whisper large-v3 | Planned; transcript translated as text (audio translation mistranslated crops) |
| Embeddings | multilingual-e5-base | Won a measured 4-model cross-lingual probe |
| Retrieval | FAISS (exact inner product) | 126k vectors fit in memory; pgvector added nothing for a single-node demo |
| Classic ML | scikit-learn: TF-IDF / embedding / ensemble classifiers, logistic regression and gradient-boosted trees | XGBoost planned; sklearn's histogram boosting is the same model family without a new dependency |
| LLM | Groq qwen3.8-27b | llama-3.1-8b was retired by Groq; chosen by a measured comparison |
| TTS | Edge TTS, gTTS fallback | Measured on synthetic Marathi/Hindi |
| Agent | LangGraph | Expert resolution graph; case state lives in SQLite (one source of truth) |
| Storage | SQLite | Postgres planned; one file is enough for a demo and is migrated in place |
| Frontend | Plain HTML/JS served by FastAPI | Next.js planned; three small pages did not justify a build chain |
| Ops | Docker Compose, GitHub Actions (pytest), 240 tests | As planned |

## 4. What was built, by stage

| Stage | Who | What |
|---|---|---|
| 1 Data cleaning | Shreya | Ingest, dedupe, Unicode cleanup, PII redaction, quality flags, 11 acceptance tests |
| 2 Triage core | Amir | Content policy (en/mr/hi), crop lexicon, classifiers, retrieval, gate, calibration, API + operator console |
| 3 Chat and voice | Shreya (built), Amir (16 fixes) | Farmer chat page, voice notes, STT, grounded rewriting, TTS, sessions |
| 4 Expert review | Amir | Case queue, LangGraph workflow, expert desk, delivery to the farmer, answer reuse, personal expert accounts |
| 5 Answerability | Amir | Learned answer gate, Marathi/Hindi training data, LLM-judge check, Docker, CI |

## 5. Results

### Safety (test months Jan-Jul 2025, knowledge base frozen at Dec 2024)

| Measure | Result | Source |
|---|---:|---|
| Chemical answers served automatically | **0** | [gate report](../reports/stage2/gate_report.md) |
| Time-sensitive questions answered from history | **0.0%** (99.8% sent to a live/scheme pointer) | gate report |
| Dose questions answered, Marathi + Hindi rephrasings | **0/160** (Stage 4), **0/80** with the Stage 5 model | [parity](../reports/stage4/crosslingual_parity_report.md), [Stage 5](../reports/stage5/answerability_report.md) |
| Real farm questions called out of scope | 0.0% | gate report |

### Classifiers and retrieval

| Measure | Result |
|---|---:|
| Query type (13 classes), unseen questions, macro-F1 | 0.676 (majority baseline 0.024; label-noise ceiling 76.5% accuracy) |
| Crop (30 classes), macro-F1 | 0.915 |
| Marathi/Hindi held-out retrieval on topic | 3/12 plain -> 10/12 with glossary expansion |

### Answering (the core trade-off)

| Test months | Stage 2 similarity rule | Stage 5 answerability model (adopted) |
|---|---:|---:|
| English questions answered | 1,112 (2.8% of all calls) | 684 (1.7%) |
| ... close to the real advisor's answer (proxy) | 27.2% | **40.1%** |
| ... English questions never seen before 2025 | 13.1% | **23.8%** |
| Marathi + Hindi answered / close (proxy) | 0 / - | **59 / 32.2%** |
| Validation AUC, "will this answer fit?" | 0.71 (similarity alone) | **0.82** |

**Independent check** ([LLM judge](../reports/stage5/answer_judge_report.md), qwen3.8-27b
for every case, 418 judged test-month answers): "same advice as the real advisor" for
**25%** of the model's English answers vs **20%** for the Stage 2 rule (intervals
overlap), and **27%** for Marathi/Hindi. The answers the Stage 2 rule gives but the model
withholds are judged right only **6%** of the time, which is where the model's gain comes
from. The judge and the n-gram proxy agree on 82% of cases. Most of the rest are "partly"
the same advice, so both numbers are conservative readings of a hard task: advisors
themselves often disagree.

### Expert loop and reuse

| Measure | Result |
|---|---:|
| Expert answer reused for the same question reworded (same language) | 66/80 (82%) |
| Expert answer reused for a different question | **0/1,963** |
| Marathi question -> English for the expert -> answer back in Marathi with every number kept | verified live |

### Voice (synthetic speech only)

Marathi CER 0.290, route agreement 8/8; Hindi CER 0.154, 7/8 ([voice report](../reports/stage3/voice_eval_report.md)).
Real farmer recordings were collected by the team; they are not in the repository, so no
measured real-speech number is reported here.

## 6. Decisions worth defending in an interview

1. **Refusing is cheaper than being wrong.** Auto-answer coverage is deliberately small
   (1.7%). Each wrong answer costs a farmer's crop; each refusal costs an expert a minute.
2. **Thresholds are relative to human agreement**, because advisors themselves agree only
   ~38% of the time; an absolute 80% target would be unreachable by construction.
3. **Pre-registered decision rules, reported even when they went against us.**
   Translate-first was rejected by its rule (Stage 4). The answerability model was first
   *rejected* by its rule (293 vs 302 close answers); the rule was then found to reward a
   baseline that misses its own quality target (27.2% vs 30.3%). It was revised (rule v2:
   every policy must meet the target) and the revision is documented as made after
   seeing the numbers, with both verdicts in the report.
4. **Safety rules are code, not model output.** The learned model only replaces one
   comparison, after every dose / chemical / live-data / scheme / crop rule; tests prove
   it is never consulted for those questions.
5. **Same-language reuse instead of cross-lingual guessing.** Marathi questions are
   matched against Marathi expert answers, which the English-summary knowledge base
   never allowed.

## 7. "Isn't this KrishiVani?"

KrishiVani-style systems retrieve KCC answers and let an LLM respond. This project
differs where it matters for a helpline: trained classifiers and a learned answerability
model with a measured gate; hard routing for doses, chemicals, live prices and schemes;
an expert queue that closes the loop back to the farmer and feeds reviewed answers back
in; and evaluation against held-out months with human-agreement baselines, an LLM-judge
check, and published failures.

## 8. Limitations (honest)

- "Close" is a proxy (char n-gram overlap); the LLM judge is a second, independent proxy,
  not an agronomist. No hand-labelled golden set was built.
- Marathi/Hindi questions in the evaluation are machine rephrasings of real call notes;
  real speech will be noisier. Devanagari numbers rest on 59 answered test cases.
- Groq's free tier (30 requests/min per model) cannot carry real traffic; a deployment
  needs a paid tier. Everything fails safe when Groq is down (typed chat still triages).
- The expert desk polls every 15 s rather than receiving pushes; adequate for a desk of a
  few experts.
- Experts in demos are played by the team (simulated).
- Out of scope by design: live phone calls, field dispatch, other states, live price and
  weather lookups.

## 9. Reproduce

See the README "Run it" section: clean -> `python -m src.triage.build` ->
`python -m src.triage.answerability_train` -> `docker compose up --build`. Tests:
`pytest -q` (240 tests).
