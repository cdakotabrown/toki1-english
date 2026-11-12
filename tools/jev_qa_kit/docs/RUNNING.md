# Running: estimate, pilot, full run, resume

All commands run from the kit root (`toki-jev-qa/`).

## 0. Self-test (offline)

```bash
python3 runner/selftest.py
```

The self-test checks the data, runs the mock backend on a stratified sample,
reruns it to confirm the resume, runs the HTTP backend against a loopback fake
that speaks the default mapping, and then builds the report and a calibration.
It works in a temporary directory, so your `results/` is not touched.

## 1. Estimate

```bash
python3 runner/run.py --estimate
python3 runner/run.py --estimate --container SERIFU/DATE_ --question meaning_preserved register
```

The estimate prints the selected lines, the calls per question (line ×
applicable question), how many are already done, and the time at
`estimate.seconds_per_call` with your `workers` and `rate_limit_per_sec`. It
prints a cost only when `estimate.cost_per_call` is set. A full run is about
**296k calls** over about 51.8k lines; the exact numbers are in
`SELFTEST-OUTPUT.txt` and come from `--estimate`. Questions only go to the
lines they apply to:

| question | applies to |
|---|---|
| meaning_preserved, naturalness, untranslated_or_garbled, needs_human_review | every line |
| register | dialogue whose speaker has a voice note (heroines, the player, Yoshio, others) |
| tone_shift | dialogue (lines, replies, alternatives, labelled lines) |
| terminology | lines whose Japanese contains a glossary term |
| honorific_policy | lines with an honorific or address form (さん 君 先輩 先生 ... or -san / Senpai in the English) |
| choice_contrast | reply menus with two or more replies |

## 2. Dry run (see what would be sent)

```bash
python3 runner/run.py --dry-run --sample 20
less results/dry_run_states.jsonl
```

Read a few states. Each question carries only its `state_fields`
(`docs/QUESTIONS.md`). If a state looks too large or too thin for your Jev,
change `questions/questions.json` and bump that question's `version`.

## 3. Pilot

```bash
python3 report/make_label_template.py --n 200        # labels/pilot_labels.csv + labels/pilot_ids.txt
#   hand-label the CSV (docs/PILOT-AND-CALIBRATION.md)
python3 runner/run.py --ids-file labels/pilot_ids.txt
python3 report/calibrate.py                          # thresholds.calibrated.json + calibration report
```

Do the pilot **before** the full run. If a question turns out to be useless
(AUC near 0.5, or badly calibrated), fix its wording or drop it before you
spend 50k calls on it.

## 4. Full run

```bash
python3 runner/run.py                         # everything
python3 runner/run.py --girl Shiori           # or in slices
python3 runner/run.py --container 'SERIFU/DATE_*' --status draft
python3 runner/run.py --question untranslated_or_garbled meaning_preserved
```

Progress and ETA are printed to stderr every `progress_every_sec` seconds.

### Selection flags (combinable)

| flag | example |
|---|---|
| `--container` | `SERIFU/DATE_AS`, `'BUNKA/*'`, `EXEDIR/TEL.EXN`, `ART/`, `COMPOSED/` (prefixes or globs) |
| `--girl` | `FU`, `Shiori`, `Yuina Himoo` |
| `--status` | `draft`, `edited`, `engineering` (raw status or status class) |
| `--source-kind` | `container_sheet container_tagged overlay_string ui_string profile_string file_string art composition` |
| `--kind` | `line choice alternatives tagged ui art composition` |
| `--speaker` | substring of the resolved speaker name |
| `--question` | question ids |
| `--ids-file` | one line id per row |
| `--sample N` | stratified by group × status × speaker role × kind; `--seed` for another draw |
| `--limit N` | stop after N calls (smoke tests) |

## 5. Resume

Just rerun the same command. Every answer is appended to
`results/results.jsonl` as soon as it arrives, keyed by `(line id, question
id, question version)`, and a rerun skips the keys already present. If Ctrl-C
or a crash leaves a torn last line, it is ignored. Failed items are listed in
`results/errors.jsonl` and retried by the next run. Transient errors (timeouts,
HTTP 408/409/425/429/5xx, connection errors) are first retried in-run with
exponential backoff and jitter, up to `max_retries`.

To re-ask a question after editing it, bump its `version` in
`questions/questions.json`. Old answers stay in the file and are ignored.

To start over, move `results/` aside.

## 6. Report

```bash
python3 report/build_report.py
```

Then see `docs/REPORT.md`.
