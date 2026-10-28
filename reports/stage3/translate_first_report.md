# Stage 3 - Translate-first experiment

Evaluation uses the frozen held-out retrieval keywords and Marathi/Hindi gate probes.
The safety gate thresholds are unchanged. For adoption, translate-first must strictly
improve held-out top-1 on-topic retrieval and must not reduce expected-route accuracy
compared with current glossary expansion. English inputs are excluded from transformation
and retain the existing query path.

## Results

| Variant | Held-out retrieval on topic | Gate routes correct |
|---|---:|---:|
| plain | 0/0 | 0/0 |
| expanded | 0/0 | 0/0 |
| translate | unavailable | unavailable |

**Decision:** Keep glossary expansion.

**Evaluation limitation:** Stage 2 runtime artifacts are missing: [Errno 2] No such file or directory: 'D:\\Downloads\\kcc-farmer-helpline-data-pipeline\\data\\artifacts\\question_texts.parquet'. Build required to measure.

No translation provider was available. Translate-first scores are unavailable; no result is imputed.

## Retrieval examples and failures

| Variant | Input | Top-1 KB question | Topic match |
|---|---|---|:-:|

## Gate-probe route results

| Variant | Input | Expected | Actual | Correct |
|---|---|---|---|:-:|
