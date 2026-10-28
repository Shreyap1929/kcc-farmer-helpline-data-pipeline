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
- Added mocked endpoint tests for typed fallback, missing sessions, expert-case hiding, voice upload/audio fetch, and unavailable speech services. `tests/test_api.py`: **14 passed**.
- Added the required `python-multipart==0.0.20` parser to requirements and installed it into the existing Python 3.13.12 venv; no Stage 2 build was run.
- Next: Phase 4 farmer chat UI.

## Phase 4 - Farmer chat UI

- Added a standalone mobile-first `/chat` page with language selection, typed chat, MediaRecorder voice upload, playback, timer, keyboard support, dark mode, and text-only error handling. `/` and its operator console are unchanged.
- The design evaluator returned **PASS** after contrast and conversation-log accessibility fixes. Browser checks at 1400, 390, and 375 CSS pixels reported no horizontal overflow; the dark send-button hover is high contrast.
- Live API/browser recording and the requested screenshot set remain unverified: the page was opened as a local file, so same-origin API calls were blocked, and no microphone permission check was run.
- Next: Phase 5 translate-first experiment; model-backed evaluation depends on the existing Stage 2 runtime artifacts, which are currently absent.
