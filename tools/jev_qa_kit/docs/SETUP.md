# Setup: pointing the runner at your local Jev

The kit does not know your local Jev API. You can describe it in `config.json`,
which needs no code, or write a small adapter in `runner/backends/custom.py`.

## 1. Pick a backend

`config.json` → `"backend"`:

| backend | use |
|---|---|
| `mock` | deterministic fake answers. Use it for dry runs and the self-test. **Its numbers mean nothing.** |
| `http` | a JSON-over-HTTP endpoint, with the request and response shape set in `config.json` → `http` |
| `custom` | any other client: edit `runner/backends/custom.py` (one class, one method) |

You can override it per run: `python3 runner/run.py --backend http ...`.

## 2. The `http` backend

### What the runner sends (the default guess)

One request per line and question:

```http
POST http://127.0.0.1:8080/v1/classify
Content-Type: application/json
Authorization: Bearer ${JEV_API_KEY}

{
  "model": "jev",
  "state": { "jp_readable": "...", "en_readable": "...", "speaker": "Yuko Asahina (heroine)", ... },
  "questions": [
    { "id": "register", "type": "choice",
      "question": "Given the speaker's voice note, how does ...",
      "options": ["matches_voice", "too_formal", "too_casual", "wrong_character_voice"],
      "option_descriptions": { ... } }
  ]
}
```

A `score` question carries `"scale": [0, 1, 2, 3]` and `"scale_labels"` in
place of options. A `boolean` question carries neither.

### What it expects back (the default guess)

```json
{ "answers": [ { "id": "register", "probabilities": { "matches_voice": 0.81, "too_formal": 0.07, "too_casual": 0.09, "wrong_character_voice": 0.03 } } ] }
{ "answers": [ { "id": "meaning_preserved", "probability": 0.93 } ] }
{ "answers": [ { "id": "naturalness", "value": 2.4, "probabilities": { "0": 0.02, "1": 0.08, "2": 0.38, "3": 0.52 } } ] }
```

### Changing the mapping

Everything above is set in `config.json` → `http`:

| key | meaning |
|---|---|
| `endpoint`, `method`, `headers` | `${VAR}` is read from the environment when the request is sent; keep keys out of the file |
| `request_template` | the request body. Put a string `"{{name}}"` wherever a value goes |
| `item_template` | one item: used for batches, and available to `request_template` as `{{item}}` |
| `request_template_batch` | the body when `batch_size` > 1: `{{items}}` is the list of rendered items |
| `batch_size` | items per request (default 1). Only raise it if your API takes several states per call |
| `response.items_path` | (batch 1) where the answer is: a list whose first entry is the answer, or the answer object |
| `response.batch_items_path`, `batch_answer_path` | (batch > 1) the list of per-item results, and the answer inside each |
| `response.match_by`, `id_field` | `index` (results in request order) or `id` (each answer carries `"<line id>\|<question id>"`) |
| `response.boolean_prob_path` | P(true): a number, or `{"true": p}` |
| `response.choice_probs_path` | `{option: p}` or `[{"label": ..., "probability": ...}]`; renormalised over the options |
| `response.score_value_path`, `score_probs_path` | the score, or the distribution over the scale (either is enough) |

Template slots: `{{state}}` (a dict, or text when `state_format` is `text`),
`{{state_json}}` (the state as a JSON string), `{{question}}` (the object
shown above), `{{question_id}}`, `{{question_type}}`, `{{question_text}}`,
`{{options}}`, `{{scale}}` and `{{line_id}}`. A string that is exactly
`"{{x}}"` becomes the value with its JSON type. Inside a longer string, the
slot is replaced by its text.
Paths are dot-separated keys and list indexes (`"data.0.result"`). `""`
means the whole reply.

### Example: an API that takes the question as plain fields

```json
"request_template": {
  "input": "{{state_json}}",
  "classifier": {"kind": "{{question_type}}", "prompt": "{{question_text}}", "labels": "{{options}}"}
},
"response": {"items_path": "", "boolean_prob_path": "score",
             "choice_probs_path": "labels", "score_value_path": "score"}
```

### Example: Mastra classifier scorers behind a local route

Jev is used in Mastra through classifier scorers (`createClassifierScorer`).
To use those, expose a small local route in your Mastra app that takes
`{state, question}`, runs the scorer that matches `question.type`, and
returns `{probability}`, `{probabilities}` or `{value}`. Then point
`endpoint` at that route and use the default response paths. If your route
returns the Mastra result object unchanged, set the paths to wherever that
object puts the score, for example `"boolean_prob_path": "score"`.

### Plain-text state

Set `"state_format": "text"` to send the state as labelled paragraphs instead
of JSON. Each paragraph is `Jp readable: ...`, `Speaker: ...` and so on.

## 3. The `custom` backend

Edit `runner/backends/custom.py`. `classify(items)` receives a list of
`{line_id, question, payload, state}` and returns one answer per item, in the
same order:

```python
{"p_true": 0.83}                                  # boolean
{"probs": {"matches_voice": 0.7, "too_formal": 0.1, ...}}   # choice
{"value": 2.4, "probs": {"0": .05, "1": .1, "2": .25, "3": .6}}   # score (probs optional)
```

Raise `RetryableError` for transient failures; the runner backs off and
retries. Any other exception fails the item: it is written to
`results/errors.jsonl` and the next run retries it. The file has two worked
examples: a raw HTTP call (the default) and a Python client library.
Settings for it go under `"custom"` in `config.json`.

## 4. Check it

```bash
python3 runner/run.py --backend http --sample 5 --question meaning_preserved --results results/smoke.jsonl
cat results/smoke.jsonl results/errors.jsonl
```

Set `"store_raw_response": true` to keep each raw answer in the results while
you check the mapping. Delete `results/smoke.jsonl` afterwards, because real
runs append to `results/results.jsonl`.

## 5. Throughput settings

`workers` (concurrent requests), `rate_limit_per_sec` (across all workers; 0
means no limit), `max_retries`, `backoff_base_sec`, `backoff_max_sec` and
`timeout_sec`. Set `estimate.seconds_per_call` to your measured latency so
that `--estimate` is realistic. `estimate.cost_per_call` stays 0 for a local
model.
