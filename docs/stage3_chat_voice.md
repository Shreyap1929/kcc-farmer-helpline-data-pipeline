# Stage 3 - Chat and voice design

## Scope and runtime flow

The farmer UI is served from `/chat`; the existing operator console remains at `/`.
Typed and recorded messages use the existing Stage 2 triage gate. Stage 3 adds typed
language detection, Groq Whisper adapters, an optional text translation adapter, safe
reply composition, optional TTS, SQLite session state, and a farmer-facing API.

The supported routes are:

| Endpoint | Purpose |
|---|---|
| `POST /api/chat/session` | Create a session with optional district, month, crop and language |
| `POST /api/chat/message` | Triage a typed message and return localized reply text |
| `POST /api/chat/voice` | Accept one multipart voice note, transcribe it, and return transcript, text and optional audio URL |
| `GET /api/chat/audio/{id}` | Retrieve generated reply audio from a bounded process-memory cache |

Voice uploads are limited to 10 MB and the configured 60-second maximum. Farmer audio
is never written to disk. Reply audio is temporary and served with `no-store`; sessions,
turns, pending clarifications and expert hand-offs live in ignored
`data/runtime/assistant.db`.

## Language and model choices

- Typed Marathi/Hindi detection reuses the Stage 1 Devanagari function-word heuristic;
  Latin-script text follows the specification's English default.
- Groq Whisper model identifiers are configuration values in
  [`../config/assistant.yaml`](../config/assistant.yaml). STT returns its detected
  language; a separate Whisper translation adapter is available for audio-to-English.
- Text translation and the answer rewriter use the configured Groq chat model with
  temperature zero. Translation prompts request translation only; answer rewriting may
  use only the historical source answer.
- Text-only operation does not require a Groq key. Translation errors fall back to the
  original text; answer rewrite errors fall back to the historical answer; voice/TTS
  errors leave a text response and a voice-unavailable indicator.
- Edge TTS is the configured default, with gTTS available behind the same interface.
  Both providers generated Marathi/Hindi synthetic clips. The current CER values measure
  Whisper's transcription of those clips, not TTS intelligibility. No human listening
  comparison was performed, so Edge is provisional and neither provider is claimed as
  the quality winner.

## Reply safety and persistence

For `ANSWER`, the composer rewrites only `answer_source.answer`. It runs the existing
`ungrounded_numbers` check and falls back to the source answer if the rewrite adds a
number or the provider fails. Replies include a KCC call/date/district source line.
Every non-answer route uses a fixed English/Marathi/Hindi template; Marathi and Hindi
templates carry `needs_native_review: true` in
[`../config/reply_templates.yaml`](../config/reply_templates.yaml).

For `EXPERT_REVIEW`, the original text, English summary, language, route reasons,
expert-only draft and sources are persisted with status `pending`. The draft is never
included in the farmer response. There is no expert dashboard or approval workflow in
Stage 3. Clarification context is one-use and expires after ten minutes.

The existing gate implementation and thresholds are preserved. Chemical and dose
questions remain expert-only, historical prices/weather/scheme status still use pointer
routes, and answer thresholds were not tuned. The experimental translated retrieval
mode unions policy signals and crop terms from original and translated input; it is
opt-in. It has not been adopted because a comparable model-backed evaluation is blocked
by missing Stage 2 embedding/classifier artifacts.

## Local setup

Build the Stage 2 runtime outputs only if they are absent, then set `GROQ_API_KEY` in a
local ignored `.env` (never in source control). Run:

```powershell
uvicorn src.api.app:app --port 8000
```

The farmer page is `/chat`; the Stage 2 operator console is `/`. Without a Groq key,
typed chat remains available through the existing gate path and voice is reported
unavailable.

## Evaluation and current limitations

The offline API/assistant tests mock Groq and TTS. Four synthetic clips (two Marathi,
two Hindi) were generated from known text using Edge TTS and gTTS, then submitted to
Groq Whisper. The observed character error rates are recorded in
[`../reports/stage3/voice_eval_report.md`](../reports/stage3/voice_eval_report.md):
Marathi 0.221 (2 samples), Hindi 0.422 (2 samples). The gTTS Hindi sample scored 0.800.
These are synthetic-only probe scores and do not estimate real farmer speech quality.
Typed-versus-voice route agreement is unavailable because the Stage 2 model/index
artifacts are incomplete. No latency benchmark, live API browser test, microphone test,
or requested desktop/mobile/dark screenshot set was completed.

At least 20 real notes from Shreya and Amir (both languages, at least three noisy) are
still needed in the ignored `data/voice_eval/` folder. Native speakers must review the
fixed Marathi/Hindi templates, and humans must listen to both TTS providers before a
provider choice is final. Stage 4 owns the expert-review interface and resolution flow.
