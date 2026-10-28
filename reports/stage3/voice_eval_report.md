# Stage 3 - Voice evaluation

CER is Unicode codepoint edit distance divided by reference length after NFC normalization and whitespace collapse. Route agreement compares triage of the typed reference with triage of the STT transcript.

Audio types in this run: synthetic.

| Language | Audio evaluated | Mean CER | Route agreement |
|---|---:|---:|---:|
| hi | 2 | 0.422 (2 samples) | unavailable |
| mr | 2 | 0.221 (2 samples) | unavailable |

## Per-file outcomes

| File | Speaker | Lang | Noisy | Status | CER | Typed route | Voice route | Agreement | Expected route match |
|---|---|---|---|---|---:|---|---|:-:|:-:|
| synthetic/edge-mr.mp3 | synthetic-edge | mr | false | triage unavailable | 0.279 |  |  |  |  |
| synthetic/edge-hi.mp3 | synthetic-edge | hi | false | triage unavailable | 0.044 |  |  |  |  |
| synthetic/gtts-mr.mp3 | synthetic-gtts | mr | false | triage unavailable | 0.163 |  |  |  |  |
| synthetic/gtts-hi.mp3 | synthetic-gtts | hi | false | triage unavailable | 0.800 |  |  |  |  |

Route agreement could not be calculated because the Stage 2 triage runtime is unavailable.

Stage 2 triage unavailable: [Errno 2] No such file or directory: 'D:\\Downloads\\kcc-farmer-helpline-data-pipeline\\data\\artifacts\\question_texts.parquet'. CER is available if transcription succeeded; no route result is imputed.
