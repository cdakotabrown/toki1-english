# Localization workflow (how the translation is produced, reviewed and shipped)

This is the working agreement for a professional translator joining the
project. It assumes the engineering blockers (listed in the readiness audit,
kept in the project's private docs) are being handled by the engineering side in parallel; the translator never needs to touch them.

## 1. Roles
| Role | Owns | Deliverable |
|---|---|---|
| Producer | scope, sign-off on OPEN style decisions, priorities | signed style guide; batch order |
| Translator | first-pass English for assigned sheets | rows with `Status = translated` |
| Editor | voice, consistency, glossary discipline | rows `edited`; glossary rows `final` |
| Engineering | encoding, budgets, relocation, fonts, disc build | playable build per batch; QA report |
| LQA (tester) | in-game read-through per scene | issues filed against row IDs |

## 2. The unit of work: one sheet
`sheets/<DIR>/<FILE>.csv`, one per script container
(exact, pointer-table extraction — see `tools/extract_containers.py`).
Columns:

| Column | Who edits | Meaning |
|---|---|---|
| `ID` | nobody | `path:0xoffset`, stable as long as the retail file is unchanged; use it in every bug report |
| `File`, `Offset`, `PtrSite` | nobody | where the string lives and which pointer word references it (engineering data) |
| `MaxBytes` | nobody | bytes the string occupies today (in-place budget) |
| `Kind` | nobody | `line` (a character speaks) / `choice` (player replies, split by `{opt}`) |
| `Speaker` | editor may refine | heroine from the file code; `player (choice)` for choices |
| (Japanese) | nobody | not a column: read from the disc by `File`+`Offset`; control bytes shown as `{tokens}` (`CONTROL-CODES.md`) |
| `Tokens` | nobody | the tokens that must survive |
| `English` | translator/editor | the target line, tokens included, ASCII punctuation only |
| `Status` | everyone, forward only | `untranslated → draft → translated → edited → qa → final` |
| `Notes` | everyone | context, questions (`Q:`), decisions (`D:`), LQA references |

Rules
- Never reorder, delete or add rows; never edit the read-only columns.
- One sheet per pull request / hand-off; sheets are UTF-8 CSV, LF line ends,
  quoted with the Python `csv` defaults (Excel and Google Sheets both round-trip).
- Batch order (recommended): `SERIFU/DATE_*` (11 heroines' date scripts, the
  pilot `DATE_AS` first as reference), then `SPEAKTST/TEST_*` (conversation
  bank per heroine, largest), then `SERIFU/EVENT_*`, then the seasonal /
  special-event files (`XMAS`, `VALEN`, `WHITE`, `SHOGATU`, `GASSHUKU`,
  `SHUGAKU`, `ENDING`, `EPILOG`), then `BUNKA/*` (culture-festival scripts),
  then UI/system strings in the executables (separate sheet family, see below).

## 3. Reference material the translator gets
- `STYLE-GUIDE.md`, `CHARACTER-BIBLE.md`, `GLOSSARY.csv`, `CONTROL-CODES.md`.
- The pilot sheet `sheets/SERIFU/DATE_AS.csv` fully drafted, as the worked
  example of voice, choice triplets and token handling.
- Scene context: `docs/reference/GAME-ARCHITECTURE.md` (in toki1-decomp) describes the scenes; the date
  script is organised by spot (museum, bowling, concert, zoo, …) in file order.
- A playable Japanese build (retail image) and, per batch, the English build.
- **Not** supplied as reference: the `merged_translations.csv` English column.
  It was captured from a third-party real-time machine-translation overlay
  (a merge script kept in the private monorepo); it is neither licensed nor good
  enough to edit from and must not be pasted into sheets.

## 4. QA gates (engineering runs these; the translator sees the report)
```
python3 tools/check_translation.py SERIFU/DATE_AS
```
- `tokens`: every `{token}` present (hard fail).
- `charset`: ASCII-only text (hard fail).
- `budget`: bytes over the in-place budget (report; drives relocation).
- `consistency`: identical Japanese with different English inside one sheet
  family (report; editor decides).
- After injection: `verify_text_coverage.py` and an emulator LQA pass per
  scene with screenshots attached to row IDs.

## 5. Hand-off cadence
1. Producer assigns a sheet; translator sets rows to `draft` as they go and
   `translated` when the sheet is complete; opens questions as `Q:` notes.
2. Editor pass → `edited`; glossary additions land in the same hand-off.
3. Engineering builds; LQA plays the scene; issues go back as `Notes` with
   screenshots; fixes → `qa`; producer signs `final`.
4. `final` rows are frozen; a change to a final row needs a note explaining why.

## 6. Out of scope for the translator (engineering backlog)
Font/half-width rendering, control-byte remapping, string relocation and disc
rebuild, name-order code change for `{F}`, honorific table for `{P}`,
graphics text (title/menu NBN images), the executables' UI strings sheet.
