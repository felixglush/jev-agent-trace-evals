# Rubrics

One YAML file per rubric. The file name is the rubric id. Seven come from the design doc and five from the Judgment Labs System One post (`source`); "user frustration" is shared, so it appears once.

| Field | Meaning |
| --- | --- |
| `question` | The one question the rubric answers. Sent to Jev as `instructions`. |
| `kind` | `choice` (one of N labels) or `noul` (labels exactly `yes`/`no`). |
| `scope` | `trace` judges the whole session; `item` judges one target event the extractor picks. |
| `labels` | Labels the models may pick, each with a description. Jev receives them as criteria. |
| `code_labels` | Labels the extractor may assign without a model: a code-only label such as `n/a`, or a model label code can settle (`no` when no tool failed). |
| `extractor` | Name of the slice function in `src/s1evals/slices/extractors.py`. |
| `evidence` | Plain-language description of the slice. |
| `budget_tokens` | Slice token cap. Over budget falls back to the slow judge. |
| `threshold` | Fast-judge confidence below this falls back to the slow judge. |
| `admitted` | Whether the rubric passed Gates 1 and 2 and may run on the fast path alone. |

Changing `question`, `labels` or the extractor means bumping `version`. Old scores keep their `judge_version` and stay readable.

Validate with `uv run s1evals rubrics check`.
