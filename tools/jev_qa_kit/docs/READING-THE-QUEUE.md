# The review queue, and feeding fixes back

```bash
python3 report/build_report.py              # -> report/out/
```

| file | contents |
|---|---|
| `review_queue.csv` | every answered line, **riskiest first**: rank, risk, `flagged_by` (questions over threshold), `lint` (deterministic findings), id, container, heroine, speaker, kind, status, Japanese, English, **`edit_file`, `edit_key`**, P(problem) per question, Jev's answer per question, and the scene |
| `summary_by_character.csv` | per speaker: lines, flagged count and percentage, mean risk, flags per question |
| `summary_by_scene.csv` | the same per container |
| `summary.md` | headline numbers, flags per question, the top 25, the worst scenes |
| `report.html` | one self-contained page with filters (text, container, heroine, speaker, question, status, minimum risk), Japanese and English side by side, P(problem) per question, and a fold-out with the neighbouring lines and where to edit. It shows the riskiest `--html-rows` lines (default 5000) |

## Risk

For each answered question, p = P(problem). The risk is

    risk = mix × max(weight × p) + (1 − mix) × mean(p)

with `mix` and the weights in `report/thresholds.json`. A **lint** finding
raises the risk to at least `lint_risk_floor` (0.9). A line is flagged for a
question when p ≥ that question's threshold. Thresholds come from
`report/thresholds.calibrated.json` once you have calibrated, and from 0.5
before that; `summary.md` says which.

The lint findings need no model:

| lint | meaning |
|---|---|
| `token_mismatch` | the English lost or gained a name / reply token (`{P}`, `{G}`, `{opt}` ...) |
| `japanese_in_english` | Japanese characters in the shipped English |
| `reply_too_wide`, `row_too_wide` | wider than the box, using the patch builder's font metrics |
| `double_space` | two spaces in a row |
| `speaker_suspect`, `choice_too_wide`, `render_error` | carried over from the repo's audits and builder |

## Reading the queue

1. Start at the top of `review_queue.csv`, or sort `report.html` by heroine.
   One editor per heroine works well, because voice problems cluster by
   character.
2. For each line, decide **fix**, **fine** (a false positive), or
   **escalate** (a style-guide question). Record fine lines: they are free
   negative labels for the next calibration.
3. Watch the per-scene summary. A whole container with a high flag share
   usually means one systematic problem, such as a voice drift or a term
   used everywhere, and not N separate ones.

## Feeding fixes back into the repo

Every line says where its English lives: `edit_file` and `edit_key`, from
`edit` in `data/lines.jsonl`. The line id is stable for as long as the
retail file is unchanged.

| source_kind | the English lives in | key |
|---|---|---|
| `container_sheet` | `sheets/<DIR>/<FILE>.csv`, `English` column | `ID=` (full sheet ID, `assets/extracted_iso/CDROM/...:0xOFF`) |
| `container_sheet` whose `en_origin` is `choice_overrides.json` | `config/choice_overrides.json` → `rows` | `<DIR>/<FILE>.BIN:0xOFF`. This is a shortened reply that makes the menu fit; the sheet row is overridden |
| `container_sheet` whose `en_origin` is `choice_edits.json` | `config/choice_edits.json` | by_text / by_id |
| `container_sheet` in `MASTER/KOSIEN`, `BUNKA/URANAI`, `TARA_OBJ/KARAKASI` | `config/overlay_drafts.d/*.json` | `by_addr["<DIR>/<FILE>.BIN:0xOFF"]` |
| `container_tagged` | `config/tagged_rows_en.json` → `rows` | `"<DIR>/<FILE>.BIN:0xOFF"` (one entry per copy of the string: fix every copy) |
| `overlay_string`, `file_string` | the draft fragment named in `edit_file` (`config/overlay_drafts.d/*.json`) or an editor sheet | `by_addr["EXEDIR/X.EXN:0xOFF"]` (one entry per copy; gift, place and club names come from `tools/item_names.py`, which regenerates every copy) |
| `ui_string` | `tools/ui_strings.py` | `<TABLE>[0xADDR]` |
| `profile_string` | `config/english.json` | `main.strings[i]` / `overlays.<OV>.strings[i]` |
| `art` | `art/<NAME>/manifest.json` | the cell or segment named in `edit_key`. Re-letter with the art tools; widths are fixed |
| `composition` | the **pieces**, each its own line (`ui_string` / `overlay_string`); `config/compositions.json` only describes how they join | `id=` |

Rules from the repo's localization workflow (`context/WORKFLOW.md`):

- In a sheet, edit only `English`, `Status` (forward only: draft → translated
  → edited → qa → final) and `Notes`. Never reorder or delete rows, and keep
  every `{token}`. `{br}` count may change.
- Put a review note in `Notes` with the line id, for example
  `LQA jev-2026-11: meaning drift, fixed`.
- After editing, the repo gates are
  `python3 tools/check_translation.py <DIR>/<FILE>` and the patch
  build (`python3 tools/build_patched.py config/english.json`),
  which reports overflows and token mismatches.
- Rebuild the kit (`python3 tools/build_jev_qa_kit.py`) and rerun
  only what changed. Results are keyed by line id, so a line whose English
  changed should be re-asked: delete its rows from `results/results.jsonl`,
  or simply start a fresh results file for the second pass.
