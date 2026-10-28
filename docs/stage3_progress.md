# Stage 3 Progress

## Phase 1 - Assistant foundations

- Added config-driven Groq Whisper STT/translation, typed language detection using the Stage 1 heuristic, LLM translation, and Edge TTS/gTTS adapters with text-only failure behavior.
- Added offline mocked tests; **14 passed**. Pinned the four new integration packages and added a placeholder `.env.example`; secrets remain in the ignored `.env`.
- Synthetic Marathi/Hindi clips were generated with Edge TTS and gTTS. Listening comparison is still pending because this environment cannot consume audio; Edge remains the configured default provisionally, not as a claimed listening result.
- Next: Phase 2 reply composition, fixed multilingual templates, session persistence, clarifications, and expert-case storage.
