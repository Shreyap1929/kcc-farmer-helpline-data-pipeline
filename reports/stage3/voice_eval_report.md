# Stage 3 - Voice evaluation

CER is Unicode codepoint edit distance divided by reference length after NFC normalization and whitespace collapse. Route agreement compares triage of the typed reference with triage of the STT transcript.

Audio types in this run: synthetic.

| Language | Audio evaluated | Mean CER | Route agreement |
|---|---:|---:|---:|
| hi | 8 | 0.154 (8 samples) | 7/8 |
| mr | 8 | 0.290 (8 samples) | 8/8 |

## Per-file outcomes

| File | Speaker | Lang | Noisy | Status | CER | Typed route | Voice route | Agreement | Expected route match |
|---|---|---|---|---|---:|---|---|:-:|:-:|
| synthetic/edge-mr.mp3 | synthetic-edge | mr | false | ok | 0.233 | EXPERT_REVIEW | EXPERT_REVIEW | True |  |
| synthetic/edge-hi.mp3 | synthetic-edge | hi | false | ok | 0.044 | EXPERT_REVIEW | EXPERT_REVIEW | True |  |
| synthetic/gtts-mr.mp3 | synthetic-gtts | mr | false | ok | 0.163 | EXPERT_REVIEW | EXPERT_REVIEW | True |  |
| synthetic/gtts-hi.mp3 | synthetic-gtts | hi | false | ok | 0.800 | EXPERT_REVIEW | OUT_OF_SCOPE | False |  |
| synthetic/edge-mr-price.mp3 | synthetic-edge | mr | false | ok | 0.161 | LIVE_DATA_POINTER | LIVE_DATA_POINTER | True | True |
| synthetic/gtts-mr-price.mp3 | synthetic-gtts | mr | false | ok | 0.258 | LIVE_DATA_POINTER | LIVE_DATA_POINTER | True | True |
| synthetic/edge-mr-whitefly.mp3 | synthetic-edge | mr | false | ok | 0.864 | EXPERT_REVIEW | EXPERT_REVIEW | True | True |
| synthetic/gtts-mr-whitefly.mp3 | synthetic-gtts | mr | false | ok | 0.091 | EXPERT_REVIEW | EXPERT_REVIEW | True | True |
| synthetic/edge-mr-pmkisan.mp3 | synthetic-edge | mr | false | ok | 0.275 | SCHEME_POINTER | SCHEME_POINTER | True | True |
| synthetic/gtts-mr-pmkisan.mp3 | synthetic-gtts | mr | false | ok | 0.275 | SCHEME_POINTER | SCHEME_POINTER | True | True |
| synthetic/edge-hi-weather.mp3 | synthetic-edge | hi | false | ok | 0.077 | LIVE_DATA_POINTER | LIVE_DATA_POINTER | True | True |
| synthetic/gtts-hi-weather.mp3 | synthetic-gtts | hi | false | ok | 0.077 | LIVE_DATA_POINTER | LIVE_DATA_POINTER | True | True |
| synthetic/edge-hi-armyworm.mp3 | synthetic-edge | hi | false | ok | 0.067 | EXPERT_REVIEW | EXPERT_REVIEW | True | True |
| synthetic/gtts-hi-armyworm.mp3 | synthetic-gtts | hi | false | ok | 0.089 | EXPERT_REVIEW | EXPERT_REVIEW | True | True |
| synthetic/edge-hi-disease.mp3 | synthetic-edge | hi | false | ok | 0.038 | CLARIFY | CLARIFY | True | True |
| synthetic/gtts-hi-disease.mp3 | synthetic-gtts | hi | false | ok | 0.038 | CLARIFY | CLARIFY | True | True |
