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
