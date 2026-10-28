# Stage 3 Progress

## Phase 1 - Assistant foundations

- Added config-driven Groq Whisper STT/translation, typed language detection using the Stage 1 heuristic, LLM translation, and Edge TTS/gTTS adapters with text-only failure behavior.
- Added offline mocked tests; **14 passed**. Pinned the four new integration packages and added a placeholder `.env.example`; secrets remain in the ignored `.env`.
- Synthetic Marathi/Hindi clips were generated with Edge TTS and gTTS. Listening comparison is still pending because this environment cannot consume audio; Edge remains the configured default provisionally, not as a claimed listening result.
- Next: Phase 2 reply composition, fixed multilingual templates, session persistence, clarifications, and expert-case storage.

## Phase 2 - Reply composition and persistence

- Added conservative answer rewriting that uses only the historical source answer, rejects ungrounded numbers, and falls back to the original answer on provider errors. Every answer includes its KCC source citation.
- Added fixed English/Marathi/Hindi non-answer templates marked for native review; expert drafts are stored only for staff review and are never included in farmer replies.
- Added SQLite session/turn/pending-clarification/expert-case storage. Clarifications are single-use and expire after ten minutes; audio is not persisted. Added `.venv/` and `data/runtime/` to `.gitignore`.
- Focused tests: **10 passed**. No Stage 2 artifacts were rebuilt.
- Next: Phase 3 API endpoints and tests.

## Phase 3 - Chat, voice, session, and audio API

- Added session creation, typed chat, multipart voice upload, and short-lived reply-audio retrieval endpoints; the operator API and `/` route remain intact. Upload audio is never persisted; expert drafts remain server-side.
- Voice uploads now use both Whisper transcription and the Whisper English-translation endpoint; if translation fails, the transcript remains available and is retained as the summary fallback.
- Added mocked endpoint tests for typed fallback, missing sessions, expert-case hiding, voice upload/audio fetch, unavailable speech services, and Whisper audio translation. `tests/test_api.py`: **15 passed** after the Phase 3 follow-up fix.
- Added the required `python-multipart==0.0.20` parser to requirements and installed it into the existing Python 3.13.12 venv; no Stage 2 build was run.
- Next: Phase 4 farmer chat UI.

## Phase 4 - Farmer chat UI

- Added a standalone mobile-first `/chat` page with language selection, typed chat, MediaRecorder voice upload, playback, timer, keyboard support, dark mode, and text-only error handling. `/` and its operator console are unchanged.
- The design evaluator returned **PASS** after contrast and conversation-log accessibility fixes. Browser checks at 1400, 390, and 375 CSS pixels reported no horizontal overflow; the dark send-button hover is high contrast.
- Live API/browser recording and the requested screenshot set remain unverified: the page was opened as a local file, so same-origin API calls were blocked, and no microphone permission check was run.
- Next: Phase 5 translate-first experiment; model-backed evaluation depends on the existing Stage 2 runtime artifacts, which are currently absent.

## Phase 5 - Translate-first experiment (measurement blocked)

- Added opt-in `plain`, `expanded`, and `translate` query modes. In translate mode, retrieval/classification use English while the gate retains the original text and unions policy keywords/crops from its translation. Default behavior remains the existing glossary expansion; English query text is unchanged.
- Added an evaluation runner for the held-out retrieval set and Marathi/Hindi gate probes, with a documented adoption criterion requiring better top-1 retrieval and no route-accuracy regression. Thresholds were not changed.
- Kept the default query metadata shape unchanged for backward compatibility; the new mode metadata appears only when an experimental mode is selected.
- Offline retrieval-mode plus gate/policy tests: **108 passed**. `reports/stage3/translate_first_report.md` records the real blocker and unavailable measurements.
- The approved build regenerated ignored `data/views/` (241 seconds) but failed before embeddings: `sentence_transformers` is absent; `torch` is also absent. The declared ranges are unpinned, and the user’s dependency choice is pending. Translate-first is not adopted.
- Phase 5 measurement remains blocked until the dependency decision; return to the experiment if approved.

## Phase 6 - Voice evaluation harness (route comparison pending)

- Added `config/voice_eval.csv` and `python -m src.assistant.voice_eval`, with Unicode CER, typed-reference versus STT route agreement, per-language summaries, and safe handling of missing audio/triage. Audio paths are constrained to the ignored `data/voice_eval/` directory.
- Generated and evaluated four clearly synthetic probes (Edge/gTTS, Marathi/Hindi) through Groq Whisper. CER: Marathi **0.221** (2 samples), Hindi **0.422** (2 samples). These small synthetic results are not representative of farmer speech; the gTTS Hindi clip CER was **0.800**.
- Route agreement is unavailable because Stage 2 embeddings/classifier artifacts are missing. No farmer recordings or expected route values were fabricated. No Marathi/Hindi listening check was completed; Edge remains provisional pending human comparison.
- Next: Phase 7 documentation and hand-off; revisit blocked measurements if model-dependency installation is approved.

## Phase 7 - Documentation and hand-off

- Added Stage 3 setup/design/safety documentation, README run instructions, and a status entry that separates implemented features from unavailable measurements and Stage 4 work.
- Full available suite: **169 passed, 2 skipped, 0 failed**. The skips are `tests/test_triage_artifacts.py:65` and `:76` because Stage 2 models are not built. Voice harness tests: 4 passed; `git diff --check` is clean.
- Stage 2 views exist, but embeddings/classifiers are still blocked on absent, unpinned `sentence-transformers`/`torch`; the user's approval on exact Python 3.13 CPU pins is pending. Translate-first adoption and voice route agreement therefore remain open.
- Manual follow-up: complete model build and both evaluation reports, collect real speech, compare TTS by listening, native-review templates, and perform app-origin UI/microphone/screenshot/latency checks before calling Stage 3 fully validated.
