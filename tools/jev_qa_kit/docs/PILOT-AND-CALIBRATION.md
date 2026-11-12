# Pilot labels and calibration

Jev reports calibrated probabilities. Its calibration is general, though, and
your questions and your notion of "a problem" are specific. Before trusting a
full run, hand-label a pilot and measure the agreement.

## 1. Make the sheet

```bash
python3 report/make_label_template.py --n 200            # --only-dialogue to skip UI / art
```

This writes `labels/pilot_labels.csv` (one row per line) and
`labels/pilot_ids.txt`. The lines are a **stratified** sample: every
combination of group (SERIFU, SPEAKTST, BUNKA, overlays, art ...), status
(draft / edited / engineering), speaker role and kind is represented in
proportion, with at least one line each. Questions that do not apply to a
line are pre-filled with `n/a`.

## 2. Label

Open the CSV in a spreadsheet; it is UTF-8. Labellers should know Japanese
and have `context/STYLE-GUIDE.md` and `context/characters/` open. For each
`label_<question>` column, enter:

| type | enter |
|---|---|
| boolean | `yes` or `no`, answering the question as worded (`meaning_preserved`: yes = meaning kept) |
| choice | one option exactly as spelled (see `labels/LABELS.md`) |
| score | `0`, `1`, `2` or `3` (naturalness) |

Leave a cell blank if you are unsure. Blank cells are ignored, not counted
as "fine". Use `labeller_notes` freely. Two labellers on the same 200 lines,
with the disagreements discussed, give a much better reference than one.

How many labels: 200 lines give about 200 labels for the every-line
questions, but far fewer for `honorific_policy` (about 3% of lines) and
`choice_contrast` (about 4%). For those two, label an extra targeted set:

```bash
python3 report/make_label_template.py --n 60 --out labels/extra.csv --ids-out labels/extra_ids.txt --force
```

To target only menus, run `python3 runner/run.py --dry-run --kind choice` to
list candidates, or filter `data/lines.jsonl` yourself. Merge the rows into
one labels file before you calibrate.

## 3. Run Jev on the pilot, then calibrate

```bash
python3 runner/run.py --ids-file labels/pilot_ids.txt
python3 report/calibrate.py                     # --policy f1 | --recall-target 0.9 | --min-labels 20
```

The outputs are `report/calibration/calibration_report.md` (all numbers),
`calibration_report.html` (reliability curves), `calibration.json`, and
**`report/thresholds.calibrated.json`**, which `build_report.py` uses from
then on.

## 4. Reading the calibration

Every metric is computed on the question's **problem event** against
P(problem):

| metric | read it as |
|---|---|
| base rate | the share of labelled lines that really have this problem |
| accuracy / kappa at 0.5 | raw agreement; kappa corrects for chance (> 0.6 good, < 0.2 the question is not working) |
| AUC | ranking quality: the chance that a real problem scores above a fine line. 0.5 is a coin flip. For triage this matters most, because the queue is sorted by risk |
| Brier | squared error of the probabilities (lower is better; the base rate × (1 − base rate) is what a constant guess scores) |
| ECE + reliability table | calibration: within each probability bin, does the observed problem share match the mean prediction? Points above the diagonal mean Jev under-calls problems, below it over-calls them |
| top-option accuracy, confusion | choice questions: does Jev pick the same option as the labeller? |
| MAE | score question: mean distance between Jev's expected score and the label |

### Picking thresholds

- `--policy recall` (default): the **highest** threshold that still catches
  `--recall-target` (default 85%) of the labelled problems. A triage queue
  should miss little, and the editors reading it are the filter.
- `--policy f1`: the best F1. Use it when the queue is too long to read.
- The sweep table shows the trade-off at each threshold: precision, recall,
  and the flag rate, which is the share of all lines the threshold sends to
  humans. Multiply the flag rate by about 51.8k lines to get the queue size.
- A question with fewer than `--min-labels` labels, or with no positive or no
  negative label, keeps its default threshold (0.5) and is marked DEFAULT in
  the report. Do not trust the flags it raises until it has labels.

### When a question does not work

If the AUC is under 0.65 or kappa is under 0.2 after 100 or more labels,
rewrite the question (`docs/QUESTIONS.md`): narrow it, change the state, or
split it. Bump its version, re-run the pilot, and calibrate again. Questions
can also be dropped from the full run with `--question`.

## 5. Keep humans in the loop

Spot-check the queue after the full run. Sample about 50 unflagged lines per
heroine and label them the same way. If they show problems, the recall
estimate from the pilot was optimistic, so lower the thresholds.
