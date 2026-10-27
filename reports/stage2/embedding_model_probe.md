# Stage 2 - Embedding model choice

**Question.** Farmers will ask in Marathi or Hindi, but every question in the KCC
data is an English call-taker summary. Retrieval therefore has to be
*cross-lingual*. Which pretrained multilingual model ranks the right English
summary first?

**Probe.** 15 real KCC English summaries, 17 farmer-style questions (12 Marathi,
3 Hindi, 2 English), each with one correct summary. Script:
`python -m src.triage.embedding_probe <model> ...` (`src/triage/embedding_probe.py`).
CPU only, measured 2026-10-27.

| Model | Top-1 | MRR | Mean margin* | Speed (texts/s, CPU) |
|---|---:|---:|---:|---:|
| **intfloat/multilingual-e5-base** (chosen) | **0.82** | **0.87** | 0.027 | 177 |
| sentence-transformers/LaBSE | 0.76 | 0.85 | 0.072 | 207 |
| sentence-transformers/paraphrase-multilingual-mpnet-base-v2 | 0.47 | 0.62 | -0.018 | 212 |
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.41 | 0.56 | -0.013 | 657 |

\* Margin = similarity of the correct summary minus the best wrong one, averaged.

**Decision.** `multilingual-e5-base`: best top-1 and MRR. Its weakness is the small
margin: similarity scores sit in a narrow band (about 0.75-0.95), so **gate
thresholds must be calibrated on data, never guessed**. That calibration is in
`gate_report.md`. LaBSE is the fallback if a later, larger probe disagrees.

**Limits.** 17 queries is a smoke test, not a benchmark. The recorded voice set
(source of truth, section 10) should repeat this with Whisper transcripts, and
compare against translating to English before retrieval.
