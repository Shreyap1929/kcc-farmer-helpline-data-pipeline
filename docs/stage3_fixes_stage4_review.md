# Stage 3 fixes and Stage 4 expert review

Done by Amir, 2026-10-28 (IST). Stage 3 was built by Shreya on a machine without the
Stage 2 models, so it had never run end to end. This document records what broke when
it did, how each defect was fixed, the measurements that were blocked, and the Stage 4
expert review loop built on top.

## 1. What was wrong with Stage 3

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Chat page shows "The service is unavailable right now" in every language | The page was opened from disk (`file://`), so every `fetch("/api/...")` failed; the backend was never started | Page detects `file://` and says how to start the server; connection retries with back-off while models load; README warns |
| 2 | Every auto-answer came back in raw Marathi, even for English/Hindi farmers; every expert case had an untranslated question | `llama-3.1-8b-instant` was retired by Groq (404 `model_not_found`); the exception was swallowed and the original text used | Switched to `qwen/qwen3.8-27b` after a measured comparison (below); shared `chat_options()` |
| 3 | A rewrite could change the crop and still pass | The only check was "no new numbers". Live run: `gpt-oss-120b` turned groundnut into "black gram" with every number intact | `rewrite_problems()` rejects added numbers, dropped numbers, a crop the source never names, and suspiciously short output; question and crop are given to the model as context |
| 4 | "Soybean" rewrites were rejected as a crop change | The crop label "Soybean (bhat)" made the model write भात (rice in Marathi) | The local alias is stripped before prompting |
| 5 | A new question after "which crop?" was silently replaced | Any message naming a crop was taken as the crop answer and the *old* question replayed ("How to control pink bollworm in cotton" became "leaves turning yellow" + cotton) | Only short replies (<= 5 words) complete a crop clarification |
| 6 | Marathi typed into an English session got English back | The dropdown always beat the text | `reply_language()`: Devanagari text decides (majority of Marathi vs Hindi question words); Latin text keeps the chosen language because romanized Marathi is common |
| 7 | Every voice reply was "voice unavailable" on a fresh install | Edge TTS rejected edge-tts 7.2.8 with HTTP 403 | Pinned 7.3.1 installed; automatic gTTS fallback when Edge fails |
| 8 | Whisper's language name could be "Marathi" (capitalised) and fall through to English | Case-sensitive mapping | Lower-cased; the transcript's own words decide and Whisper's label only breaks ties |
| 9 | Spoken Hindi "गेहुं" (wheat) was asked "which crop?" | The lexicon lacked the short-u spellings Whisper writes | Added "गेहुं", "गेहुँ" |
| 10 | Pointer replies lost the helpline numbers the gate gives | Fixed templates replaced the gate's text with generic wording | Templates now carry `{kcc_helpline}`, `{pm_kisan_helpline}`, `{crop_insurance_helpline}`; rewritten as readable UTF-8 |
| 11 | Expert cases could never be resolved | `expert_cases.status` had `CHECK (status = 'pending')` | v2 schema with an in-place migration that keeps existing cases |
| 12 | Every non-English message paid for an LLM translation | Translation ran before triage | Only expert cases are translated (the expert is the only reader) |
| 13 | The 10 MB oversize-audio test errored on Windows | pytest put the 10 MB byte string in the test ID | Explicit `ids=` |
| 15 | Expert saw "I have got a Pannari fish on my plate" for a spoken whitefly question | Voice cases used Whisper's audio-to-English translation, which misheard the Marathi | The transcript is translated as text (which gave "Whitefly has appeared on the cotton"); Whisper translation is only the fallback, saving one Whisper call per voice note |
| 16 | Typing a name on the expert desk, then clicking a case, did nothing | The name field's `change` fires on the click's mousedown and rebuilt the list under the pointer | The list is no longer rebuilt on a name change |
| 14 | The translate-first comparison was unfair to the baseline | The "expanded" variant also received the translation's safety signals | Only the translate variant sees the translation |

### Model choice (measured on the key's available models)

Same prompt, two real KCC answers (groundnut sowing time, soybean varieties), English and Hindi targets:

| Model | Latency | Result |
|---|---:|---|
| `openai/gpt-oss-120b` | 0.5-1.3 s | Groundnut -> "black gram"; refused one Hindi rewrite |
| `openai/gpt-oss-20b` | 0.4-0.6 s | Left "bhuiimug" untranslated in English; one Hindi answer only re-listed the Marathi |
| `qwen/qwen3.8-27b` (chosen) | 0.15-0.35 s | Crop and every number kept in all four |

The free Groq tier allows 30 requests per minute per model. The composer and translator
fail safe (historical answer / original text) when the limit is hit, but a real
deployment needs a paid tier.

## 2. Measurements that were blocked, now run

| Measure | Result | Report |
|---|---|---|
| Full test suite | see STATUS.md | `pytest` |
| Translate-first vs glossary expansion (held-out retrieval, 12 phrases) | plain 3/12, expanded **10/12**, translate 9/12; routes 13/14 for all three | `reports/stage3/translate_first_report.md` |
| Voice route agreement (16 synthetic clips, Edge + gTTS, mr/hi) | mr 8/8, hi 7/8; expected route matched 12/12 labelled clips; mean CER mr 0.290, hi 0.154 | `reports/stage3/voice_eval_report.md` |
| Cross-lingual answer parity (80 English questions the engine answers, rephrased in mr/hi) | Answered with the English answer: **mr 0/80, hi 0/80** (glossary expansion); translate-first answers 3/80 per language but 5 of 6 answers differ from the English one. Dose questions answered: 0/160. Decision: keep expansion | `reports/stage4/crosslingual_parity_report.md` |

**The parity result is the most important finding of this session.** Auto-answering is in
practice English-only: the 0.98 threshold was calibrated on English questions, and
Marathi/Hindi questions reach the right record at 0.86-0.91 similarity. Translating first
does not fix it (translation noise, e.g. guava -> mango, picks different records). So
for Marathi and Hindi farmers the expert desk is the main path, not a fallback, which is
why Stage 4 was the right next step. Fixing auto-answers for them needs a threshold
calibrated on Devanagari questions, or a reviewed answer base built from expert answers
(section 4), not a different query transform.

The synthetic clips are machine speech; they show the pipeline works, not how it copes
with farmers on a phone line. Real recordings are still the open item.

## 3. Stage 4: expert review

```text
farmer chat --EXPERT_REVIEW--> expert_cases (pending)
                                   |  /expert: claim (in_review, one expert at a time)
                                   v
                     LangGraph review workflow (src/review/workflow.py)
   validate --error--> refused (422/409)
       |--refer------------------------------------> referral template (+ translated note)
       `--approve past answer / write answer --> annotate (Stage 2 answer policy:
                                                   chemical? time-sensitive? reusable?)
                                  --other language--> localize (LLM, then the same
                                                      number/crop checks as the composer;
                                                      on doubt the expert's own words go)
                                  --same language--> compose
                                                    --> persist (answered / referred, audit event)
farmer chat polls /api/chat/session/{id}/updates --> "KCC expert" message + audio, delivered once
```

Design choices:

- **The expert is the authority on content.** The workflow never blocks a chemical
  answer; it blocks the step the expert cannot see, the translation into the farmer's
  language. A translation that adds or drops a number or names a different crop is
  discarded and the expert's own text is sent, with the reason stored on the case.
- **Reuse is opt-in by policy, not by default.** Every answer is tagged with the Stage 2
  answer policy; only answers that are neither chemical nor time-sensitive are marked
  `reusable`. Nothing reuses them yet; that is the next step (section 4).
- **Concurrency is enforced in SQL, not the UI.** Claim and resolve are conditional
  `UPDATE`s, so two experts cannot answer the same case and a resolved case cannot be
  resolved again (HTTP 409).
- **Audit trail.** `case_events` records created / claimed / released / answered /
  referred / delivered with actor and checks.
- **Access.** Set `EXPERT_TOKEN` to require `X-Expert-Token` on `/api/expert/*`; without
  it the desk is open, which is acceptable only on a local machine. There are no user
  accounts yet.
- **Why LangGraph here.** The resolution has real branches (refer vs answer, translate
  vs not, fallback on a failed check) and each node is a pure function of the state, so
  it is testable node by node with a fake translator. The case lifecycle itself lives in
  SQLite, not in a LangGraph checkpointer, so there is one source of truth.

API (all under `/api/expert`): `GET /cases?status=&language=`, `GET /cases/{id}` (with
draft, similar past calls, conversation and events), `POST /cases/{id}/claim`,
`/release`, `/resolve` (`approve_draft` | `answer` | `refer`), `GET /stats`.

## 3b. Reusing expert answers (feedback loop)

`src/review/reviewed_answers.py`. Because the historical KB cannot answer Marathi/Hindi
questions (parity 0/80), the expert desk is their main path, and the same questions keep
arriving. Expert cases keep the farmer's own words, so a new question can be matched
against them like for like (Marathi to Marathi), which the English KB never allowed.

A reviewed answer is served instead of opening a new case only if **all** hold:

1. The expert's answer was tagged `reusable` by the Stage 2 answer policy (no chemical,
   no dose, nothing time-sensitive). Chemical answers are never indexed.
2. The gate sent the new question to an expert only for `LOW_CONFIDENCE` or
   `CROP_MISMATCH`, never for a dose, a high-risk topic or a chemical draft, and the
   question has no dose, price, weather or scheme words.
3. Same language and exactly the same crops mentioned as the reviewed question.
4. Same-language embedding similarity >= `review.reuse_min_similarity` (REUSE_THRESHOLD),
   calibrated so that no pair of different questions in the calibration set matches
   (`python -m src.review.calibrate_reuse`, `reports/stage4/reviewed_reuse_report.md`).
   REUSE_RESULT

The farmer sees the expert's text unchanged (no LLM rewrite) with "answered earlier by a
KCC expert for a similar question (case, date)". Each reuse is logged as a `reused`
event on the original case, counted on the expert desk, and shown on the case, so an
expert can see how far their answer travelled and correct it if needed. New reusable
answers are indexed the moment the expert resolves the case.

## 4. Screenshots

`reports/stage4/screenshots/`: chat opened from disk (the original bug, now explained),
Marathi desktop conversation ending with the expert's reply, Hindi mobile dark, the expert
desk with a claimed case, and an answered case on mobile dark. Taken with Playwright
against the live server; no console errors, no horizontal overflow at 390 px.

## 5. Next steps

1. Real voice notes (at least 20, both speakers, some with background noise) through
   `python -m src.assistant.voice_eval`.
2. Native review of the Marathi/Hindi templates (`needs_native_review: true`).
3. Reuse of expert answers is built (section 3b) but calibrated on machine-written
   paraphrases; re-check the threshold on real repeat questions once the desk has
   a few hundred answered cases. Add a way for experts to retire a reused answer.
4. Expert accounts instead of a shared token; notifications instead of polling; live calls.
