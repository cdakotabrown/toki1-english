# Tokimeki Memorial English script: Jev QA triage kit

This kit holds every English line that the English patch of *Tokimeki Memorial:
Forever with You* (SLPS-00065) ships. Each line comes with its Japanese source,
its speaker, its scene, the lines around it and its layout limits. The kit also
contains the files needed to run a triage pass over all of it with **Jev**, a
calibrated classifier that you run on your own machine.

Jev answers short questions with fixed answer sets (yes/no, one of N options, or
a 0–3 score) and gives a probability with each answer. The kit asks it nine
focused questions per line, such as "is the meaning preserved?", "does the
register fit this character?" and "is anything left untranslated?". It then
ranks the lines by risk, so the human editors read the riskiest lines first.
**Jev is used for triage only. It does not judge the translation:** every fix
is still made by a person.

> Read `LICENSE-NOTE.md` first. The kit contains the game's Japanese script.
> It is for local QA only: never redistribute it or upload it.

## Quick start (5 steps)

```bash
cd toki-jev-qa
python3 runner/selftest.py                    # 1. plumbing check, offline (mock backend)
python3 runner/run.py --estimate              # 2. how many calls a full run makes
#    edit config.json: backend "http" + your endpoint (docs/SETUP.md)
python3 runner/run.py --sample 50 --limit 20  # 3. smoke test against your local Jev
python3 report/make_label_template.py --n 200 # 4. pilot: label 200 lines by hand, then
python3 runner/run.py --ids-file labels/pilot_ids.txt && python3 report/calibrate.py
python3 runner/run.py && python3 report/build_report.py   # 5. full run, then open report/out/report.html
```

You need Python 3.8 or later and nothing else. There is no pip install, and
`config.toml` is optional (Python 3.11+). The only network traffic goes to the
endpoint you configure.

## What is where

| path | what |
|---|---|
| `data/lines.jsonl` | one JSON object per shipped English line (schema: `docs/DATA.md`) |
| `data/manifest.json` | counts per source, container, heroine, status, kind; not-shipped rows |
| `data/not_shipped.jsonl` | rows that stay Japanese in the patch, and why (context only, not asked) |
| `context/` | voice bibles (one file per character), style guide, glossary, control codes, scene index (`context/README.md`) |
| `questions/questions.json` | the triage questions: wording, answer set, state fields, when they apply |
| `config.json` | backend, workers, rate limit, retries, HTTP request/response mapping |
| `runner/` | `run.py` (the run), `selftest.py`, `common.py`, `backends/` (`mock`, `http`, `custom`) |
| `report/` | `build_report.py`, `make_label_template.py`, `calibrate.py`, `thresholds.json` |
| `labels/` | where the pilot label sheet goes (`labels/LABELS.md`) |
| `docs/` | SETUP, RUNNING, QUESTIONS, PILOT-AND-CALIBRATION, REPORT, DATA |
| `SELFTEST-OUTPUT.txt` | the self-test as it ran when the kit was built |

## How a run works

The runner sends one request per line and question. Each request carries
only the state fields that question needs. For example, the register
question gets the speaker's voice note and not the whole character bible,
because Jev does worse with irrelevant context. Answers are appended to
`results/results.jsonl`, keyed by line id, question id and question
version, so a run can be stopped and resumed at any time.

Checks that need no model run deterministically in the report and are not
sent to Jev: lost name tokens, Japanese left in the English, and text too
wide for its box. Jev is weak at counting and pixel arithmetic, so it is
never asked those.

Fixes go back into the repo. Every line names the exact file and key that
holds its English (`edit.file`, `edit.key`), as described in `docs/REPORT.md`.
The kit is rebuilt from the repo with
`python3 tools/build_jev_qa_kit.py`.
