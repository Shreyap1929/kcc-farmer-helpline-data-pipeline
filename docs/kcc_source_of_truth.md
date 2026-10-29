# KCC Farmer Helpline Assistant - Source of Truth

Last updated: 2026-10-25
Owner: final-year AI & Data Science team (2 people)

This file is the single reference for what we are building and why. If a chat, a note or this file disagree, this file wins until someone edits it on purpose.

Status tags used below:
- **[DECIDED]** the team chose this.
- **[PROPOSED]** suggested during planning, not yet confirmed by the team.
- **[OPEN]** needs a decision or a measurement.
- **[VERIFIED]** seen in real data or an official page.
- **[UNVERIFIED]** believed true, not checked yet.

---

## 1. One-paragraph summary

A voice-first assistant for the Kisan Call Centre (KCC) style helpline. A farmer speaks a question; the system transcribes it, predicts the query type and crop, retrieves similar past expert answers, decides through a gate whether to answer, ask a follow-up, point to a source, or hand over to a human expert, and replies by voice and text. Expert answers approved in a review queue flow back into the knowledge base. It is built on real KCC records from data.gov.in. [DECIDED]

The project is a decision-support and triage system for a helpline. It does not replace an agronomist, and it never gives chemical dose advice on its own.

## 2. Why this project (and what we rejected)

Test used to pick ideas: *would a real person already do this by voice instead of typing or walking in, and is there real public data with real labels?*

Rejected, with the reason:
- **NHTSA vehicle complaint desk.** Owners just drive to the service centre and decide after the quote; nobody would use an AI intake step.
- **Government scheme eligibility navigator** (from the classmates' "AI Bureaucracy Navigator" proposal). Real problem, but eligibility is rules not prediction, so classic ML is weak; myScheme already offers an eligibility check; no public outcome data.
- **Teammate's five "desk" ideas** (FOIA, transit outage, wage complaint, aviation incident, parking/towing). Same complaint-desk shape, mostly US data, weak voice fit.
- **NYC 311 city helpline.** Kept as the backup idea only. Data has no real caller sentences, so speech-to-category cannot be trained on real utterances.
- **Field-reviewer dispatch.** KCC escalates by phone to subject-matter specialists, not by sending people to the farm. Adding dispatch would look forced.

## 3. Users and the problem

- **Farmer (primary).** Calls with crop, pest, input, scheme or price questions, in their own language. Does not type or browse websites.
- **Expert / advisor (secondary).** Reviews cases the system should not answer alone, and approves or edits drafted replies.

Problem: the same questions are answered again and again by humans, while risky or unusual cases need an expert. The system handles the repeatable ones safely and escalates the rest with a ready summary.

## 4. Scope

**In scope for v1**
- State: **Maharashtra only.** [DECIDED]
- Time range: target **2024 and 2025**; start with Jan and Feb 2025 already downloaded. [PROPOSED]
- Seasonal coverage: pull June to September 2025 early, since months so far are all winter/rabi. [PROPOSED]
- Input: push-to-talk voice plus a typed fallback. [PROPOSED]
- Languages: decided after the language audit (see section 9). [OPEN]
- Expert review queue with pause and resume (human in the loop). [DECIDED in principle]

**Out of scope for v1**
- Field dispatch or on-site visits.
- Real-time phone calls (possible later upgrade).
- Other states.
- Live prices and weather lookups: v1 only says it cannot give today's figure and points to where to check. A real lookup is optional later. [PROPOSED]
- Filing anything in any real government system.
- Any claim that the system is agronomically verified.

## 5. Tech stack

| Layer | Tool | Notes |
|---|---|---|
| Speech to text | Groq Whisper | Free tier. Hindi/Marathi quality must be tested in week 1. |
| Speech out | Browser speech or an open-source engine | Free; choose after testing Hindi/Marathi. [OPEN] |
| Backend | FastAPI | One API for farmer page, agent, expert dashboard |
| Agent | LangGraph | Uses interrupt/resume for expert review |
| LLM | Groq Llama | Writes the reply only from retrieved text |
| Database | Postgres + pgvector | Cases, answers, logs, vectors |
| Embeddings | Multilingual sentence-transformers, run locally | Pretrained, not trained by us |
| Classic ML | scikit-learn, XGBoost | Query classifier, answerability model |
| Frontend | Next.js (farmer page + expert dashboard) | Streamlit is the fallback if time is short. [OPEN] |
| Engineering | Docker Compose, pytest, GitHub Actions, structured logs | |

## 6. Runtime flow (one call)

1. Farmer speaks (push-to-talk).
2. Speech to text; also record the detected language.
3. Classifier predicts query type and crop; district and month come from the profile.
4. Retrieve similar past questions and expert answers (same crop, state, season where possible).
5. Gate picks a route (section 7).
6. LLM writes the reply only from retrieved text, shows the source, and abstains if nothing close exists. Automatic check: every number and product name in the reply must appear in the source answer; otherwise escalate.
7. If escalated, the graph pauses and the case enters the expert queue with transcript, predicted type, retrieved answers and draft reply.
8. Expert approves, edits or rejects; the graph resumes and the farmer gets the answer back. Only expert-approved answers are added to the knowledge base. Unreviewed AI output never goes back in.

## 7. The gate (routes)

1. Answer from retrieved expert answers (with source).
2. Ask a clarifying question (for example, which crop or growth stage).
3. Scheme pointer (scheme answers in the data are mostly "contact the district agriculture office" or a helpline number).
4. Live-data pointer for prices and weather. [PROPOSED] Reason: sample rows show dated mandi prices and a weather forecast, which are only true on the day given.
5. Expert review for risky or low-confidence cases. All pesticide, herbicide and fertiliser dose questions go here. [DECIDED]
6. Out of scope.

## 8. Machine learning

Retrieval uses a pretrained multilingual embedding model. Two models are trained by us:

**A. Query classifier**
- Input: transcribed question, district, month.
- Predicts: query type and crop.
- Labels: the QueryType and Crop columns. QueryType is **noisy** (e.g. a weather query labelled Post Harvest Preservation; tomato virus control labelled Fertilizer Use), so we train on dataset labels but **score on our hand-checked golden set** and report the gap.
- Compare a simple baseline (TF-IDF + logistic regression) against XGBoost on embeddings.
- Known mismatch: the text it trains on is an English summary written by the call-taker, but at runtime it sees Marathi speech. Measure on the recorded voice set and compare with translating to English first.

**B. Answerability model**
- Input: similarity of top retrieved answers, gap between first and second match, predicted type and crop, language, dose-question flag.
- Predicts: probability that the best retrieved answer is actually good.
- Label: for each old question, retrieve without that row and compare the retrieved answer with the real KccAns; "close enough" becomes the label. The threshold is a known weak point and must be justified in the report. [OPEN]
- Must beat a simple confidence-threshold rule; if it does not, report that honestly.

## 9. Data

**Source:** data.gov.in resource "Kisan Call Centre (KCC) - Transcripts of farmers queries & answers" (Ministry of Agriculture and Farmers Welfare). [VERIFIED]

**Columns:** BlockName, Category, CreatedOn, Crop, DistrictName, KCCCallID, KccAns, QueryText, QueryType, Season, Sector, StateName, day, month, year.

**What we have**
- Ingested 21 raw CSV files across `DATASETS.zip` and `2025-dataset.zip` totaling 370,702 raw rows.
- `mh-2024-2.csv` (9,521 rows, MD5 `9b2d54ddedee588ffa3df4b34c6786da`) is a byte-identical copy of `mh-2024-1.csv` containing January 2024 data. **February 2024 (`2024-02`) is missing** from data.gov.in downloads and excluded as duplicate.
- Master clean dataset (`kcc_mh_clean.parquet` / `kcc_mh_clean.csv`): **361,181 rows** with 100% unique `KCCCallID`s (0 duplicates across files).
- Coverage: 20 monthly files spanning November 2023 (`2023-11`) through July 2025 (`2025-07`, partial month ending 29 July 2025).
- Per-month verified row counts:
  - 2023-11: 13,178 | 2023-12: 13,633 | 2024-01: 9,521
  - 2024-02: *missing*
  - 2024-03: 9,161 | 2024-04: 10,219 | 2024-05: 10,447 | 2024-06: 27,694
  - 2024-07: 27,864 | 2024-08: 32,163 | 2024-09: 24,210 | 2024-10: 26,379
  - 2024-11: 12,725 | 2024-12: 17,093 | 2025-01: 12,065 | 2025-02: 14,685
  - 2025-03: 15,146 | 2025-04: 12,370 | 2025-05: 14,804 | 2025-06: 30,413
  - 2025-07: 27,411 (to 29 Jul)
- The portal API exists (resource total about 47.9 million rows; State Name and Year are mandatory filters). We are using CSV downloads for now and avoiding the API. [DECIDED]
- Licence and terms of use: not yet read. [OPEN]

**Known data issues** (seen in sample rows)
- QueryText is the call-taker's English summary, not the farmer's words, and is sometimes garbled.
- QueryType labels are noisy.
- Season is "NA" in sampled rows; derive it from the month.
- Many answers are template-like, so near-duplicates are common (leakage risk).
- Answers include dated mandi prices and weather forecasts (not reusable later).
- Scheme answers are mostly pointers.
- Dose answers (pesticide/herbicide/fertiliser quantities) are common.
- Stray whitespace and newlines in text; all API fields are strings.
- **Answer language varies by district inside Maharashtra** (team observation). Marathi and Hindi are both Devanagari, so script alone cannot separate them.

**Language handling**
- Add `answer_lang` (marathi / hindi / english / unclear) and `lang_confidence` to a cleaned copy. Never overwrite raw files.
- First pass uses a word-list heuristic; verify by reading about 50 rows per language before trusting it.
- The farmer's language at runtime comes from speech detection, not from the dataset. District to usual language is only a hint/prior.
- Report all results per language group.

**Excluded sources**
- The Andhra Pradesh 2025 copy (Telugu answers; different state).
- A separate question/answer pairs file of unknown origin and licence (no state, date or crop columns). Not used in the golden corpus.

**Data rules**
- Raw files are read-only and kept out of Git; share through a drive link or private dataset. Record source, licence and download date per file.
- One file per month, named like `kcc_mh_2025_03.csv`.
- Do not open and re-save CSVs in Excel (it can corrupt Marathi text); read with pandas.
- Check each month's row count for suspiciously round numbers (possible download cap) and for repeated KCCCallIDs across files.
- Redact any names or phone numbers found in text.
- API keys live in `.env`, which is in `.gitignore`. Any key pasted in chat or code is rotated.

## 10. Evaluation and the golden corpus

The golden corpus is hand-checked and frozen. We never train on it and retrieval never reads from it.

Contents (sizes are suggestions, not a standard):
- Classifier set: a few hundred queries with type and crop checked by both of us.
- Answer set: 100 to 150 later-dated queries with their real expert answers.
- Hard cases: dose questions, vague questions with no crop, scheme-status questions, out-of-scope questions, ones that should be escalated.
- Voice set: 50 to 100 recorded Marathi and Hindi sentences from several speakers, including a noisy one.
- A short labelling guide, two labellers on a sample, and an agreement check.

Rules:
- Remove from the knowledge base anything near-identical to a test question.
- Expert answers are what an advisor said, not agronomic ground truth. State this in the report; ask an agriculture student to review a sample if possible.

Tests and metrics:
- Chronological split (earlier months train, later months test). Jan to Feb 2025 is the first experiment; the final split should use a full cycle of seasons.
- Report two modes: **realistic** (repeat questions allowed) and **hard** (test questions with a near-duplicate in the knowledge base removed). Report the gap.
- Classifier macro-F1 against the hand-checked labels; retrieval hit rate against held-out expert answers; abstention quality (answered when it should have escalated); speech accuracy on the voice set; expert acceptance rate in the review queue.

## 11. Failure points and checkpoints

Risks: licence or access stalls; outdated advice in old records (pesticides may be banned now); free-tier speech quality in Marathi/Hindi and rate limits; answerability model not beating a simple rule; train/test leakage from duplicates; hallucinated replies; scope creep (real-time calls, field dispatch, more states); two-person integration; demo-day failures (keep a recorded backup and cached runs); the question "isn't this KrishiVani?".

Our answer to the last one: the classic-ML classifiers, the gate with human escalation, the expert loop and the measured evaluation.

Go / no-go checkpoints:
- **End of week 1:** data usable; speech good enough in Marathi or Hindi. If not, switch to one language or typed input.
- **After the baseline:** retrieval finds a good answer often enough to build on (set the bar after the first numbers).
- **Before the expert queue:** the gate works on its own.

## 12. Build order and split (suggested)

- Person A: data cleaning, language column, classifier, answerability model, golden corpus, evaluation.
- Person B: speech in/out, FastAPI, LangGraph agent, pgvector retrieval, frontend and expert dashboard.
- Agree API shapes early and work from mocks until the pieces connect. Then integrate, add the expert queue, run evaluation, and finish with Docker.
[PROPOSED]

## 13. Related work (seen via search; code not reviewed)

- KrishiVani: cross-lingual RAG over 73,000+ KCC answers with FastAPI, FAISS and Groq (author's GitHub link not found).
- KisaanBot (RASA chatbot): github.com/rhazra-003/KisaanBot_Farmer_Assistant
- KrishokBondhu (paper, Bengali voice advisory): arxiv.org/html/2510.18355v1
- Farmer-Bot (paper): arxiv.org/abs/2204.07032
- LiveKit RAG voice agent (toolkit): github.com/Arjunheregeek/livekit-rag-voice-agent

## 14. Open items checklist

Closed on 2026-10-29 (final status in [final_report.md](final_report.md)).

- [x] Read the licence and terms of use of the KCC resource -> GODL-India, attribution statement in [data_licence.md](data_licence.md).
- [x] Download remaining 2025 months and 2024; verify per-month row counts -> 2023-11 to 2025-07 (Feb 2024 missing upstream; its file is a copy of Jan 2024), counts tested in `tests/test_clean.py`.
- [x] Run the audit -> [reports/cleaning_report.md](../reports/cleaning_report.md), `reports/value_counts/`.
- [x] Test Groq Whisper on recorded Marathi and Hindi sentences -> synthetic clips measured ([voice report](../reports/stage3/voice_eval_report.md)); real recordings reported done by Amir and Shreya.
- [x] Choose v1 languages from the audit -> Marathi, Hindi and English.
- [x] Decide the "close enough" threshold for the answerability label -> char n-gram cosine >= 0.5, target = 80% of advisor agreement ([gate report](../reports/stage2/gate_report.md)); checked against an LLM judge in Stage 5.
- [x] Confirm the live-data pointer route -> built; time-sensitive questions answered from history 0.0%.
- [x] Choose text-to-speech and frontend -> Edge TTS with gTTS fallback; plain HTML pages served by FastAPI instead of Next.js/Streamlit.
- [x] Agree who plays the expert in demos -> simulated by the team; stated in the final report.
