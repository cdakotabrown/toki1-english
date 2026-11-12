# data/lines.jsonl

Each row of `data/lines.jsonl` is one line the English patch ships. There is
one JSON object per row, and every shipped English string appears exactly
once. `data/manifest.json` has the counts, per source kind, group,
container, heroine, speaker role, status and kind.

## Schema

| field | meaning |
|---|---|
| `id` | stable id. For script containers it is `<DIR>/<FILE>.BIN:0x<offset>`; for overlay, main and data-file strings it is `EXEDIR/<OV>.EXN:0x<offset>` / `PSX.EXE:0x<offset>` / `FUKUTEST/<FILE>:0x<offset>` (the same form `config/overlay_drafts.d` uses as `by_addr`); for art it is `ART/<NAME>:<cell>`; for compositions it is `COMPOSED/<id>#<n>` |
| `source_kind` | `container_sheet`, `container_tagged`, `overlay_string`, `file_string`, `ui_string`, `profile_string`, `art` or `composition` (see "How lines were collected") |
| `sheet_id` | the full sheet `ID` (`assets/extracted_iso/CDROM/...:0x..`) for container rows, otherwise null |
| `group`, `container` | `SERIFU` / `SERIFU/DATE_AS`; `EXEDIR` / `EXEDIR/TEL.EXN`; `ART` / `ART/OPTION`; `COMPOSED` / `COMPOSED/main` |
| `offset`, `addr` | file offset; RAM address for executable strings |
| `scene` | `{container, description, confidence, girl, girl_code, event, location, date}`. The description comes from `context/scene_index.json`. `confidence`: `docs` means stated in the repo's docs, `name` means inferred from the file name and its lines. `event`, `location` and `date` are **null**, because the script containers carry no per-line scene markup (see Known gaps) |
| `speaker` | `{raw, name, role, source, bible, candidates?}`. `role` is one of heroine, player, npc, friend, narrator, ui or unknown. `source` is `sheet`, `tagged row label`, `row kind (choice)`, `string kind`, `art`, `composition` or `unresolved`. `bible` is the `context/characters/<slug>.md` file for the voice note. `candidates` is set when unresolved, for example "Yuko Asahina or the player" |
| `kind` | `line`, `choice` (player reply menu, replies split by `{opt}`), `alternatives` (`{opt}`-split lines of which the game shows one), `tagged` (a line with a speaker label), `ui`, `art` or `composition` |
| `jp`, `jp_readable` | Japanese with `{tokens}`, and the same with the codes in words |
| `en_source` | the English as written in its source (sheet, draft, table) |
| `en`, `en_readable` | **the English as it ships**: overrides applied, normalised (ASCII quotes and dashes, `...`) and re-flowed to the window, exactly as the patch builder encodes it; then the same in words |
| `en_origin` | where the shipped English came from (sheet, `choice_overrides.json`, `tagged_rows_en.json`, `overlay_drafts by_addr`, editor sheet, `ui_strings.py`, `english.json`, art manifest ...) |
| `edit` | `{file, key, column?, also?, note?}`: where to change it (see `docs/REPORT.md`) |
| `status`, `status_class` | raw status (`draft`, `edited`, `engineering`) and class (`draft`, `edited`, `final`, `engineering`). `engineering` means English written by the patch engineers in code or config (UI tables, profile strings, art, compositions); it never passed through a sheet |
| `sheet_notes` | the sheet's `Notes` cell (translator / editor history, `D:` decisions, `Q:` questions) |
| `tokens` | name and reply tokens in the Japanese (`{P}`, `{G}`, `{opt}` ...) |
| `constraints` | containers: `box`, `max_px_per_row` (201 px message window, 257 px reply row), `rows_per_page` (3; the window scrolls), `rows`, `widest_row_px`, `reply_px`, `rows_per_reply`, `rows_per_menu`, `char_budget_per_row` (~32), `retail_slot_bytes`, `encoded_bytes_with_dte`. Strings: `slot_bytes`, `placement` (in place / relocated / module string), `pointer_word`. Art: `cell_px`. Compositions: `max_px`, `buf_bytes` |
| `flags` | known findings `{source, flag, detail}`: the 2026-10-02 localization audits (`speaker_suspect`, `voice_fix_applied`, `consistency_unified`, `glossary_term_fixed`), builder notes (`choice_too_wide`, `shortened_reply_override`, `reflowed_or_overridden`, `relocated_in_container`), `pc_boot_overwrite_fixed` (BROKEN-STRINGS-AUDIT ranges), `japanese_in_english`, `composition_sample` |
| `seq` | `{group, index, of}`: the position in its sequence (offset order inside one container or file) |
| `neighbours` | `{prev: [...3], next: [...3]}`, each `{id, speaker, kind, jp, en}`. These are neighbours in the same sequence; rows that stay Japanese are included with `en: null` |
| `glossary_hits` | glossary rows whose Japanese occurs in the line: `{jp, en, category, notes}` |
| `ships` | always true in this file. Rows that do not ship are in `data/not_shipped.jsonl` |

## How lines were collected

`tools/build_jev_qa_kit.py` (in the repo) decides what ships the
way the patch builder does, by calling the builder's own code:

1. **Script containers** (SERIFU, SPEAKTST, BUNKA, MASTER, TAIIKU, SHIAI,
   TARA_OBJ; profile `config/english.json` → `containers`). The kit
   calls `tools/inject.py` `load_containers()`, which loads the sheets,
   the tagged rows the sheets skip (`tagged_rows_en.json`) and the reply
   overrides (`choice_overrides.json`, `choice_edits.json`). It then runs
   `prepare()` + `pack()` with the run's DTE table. A row ships when it is
   still translated after the pack: an accepted status, every token kept, a
   writable slot, and room in the container. `en` is the fitted text the
   injector encodes. The three containers without a translation sheet
   (`MASTER/KOSIEN`, `BUNKA/URANAI`, `TARA_OBJ/KARAKASI`) are included with
   the English from `overlay_drafts`.
2. **Overlay, main and data-file strings.** The kit runs
   `tools/ui_strings.py` and `tools/overlay_sheets.py` exactly as
   the build does, so the precedence is the builder's: profile strings
   (`english.json`), then `ui_strings.py`, then the draft sheets with
   `overlay_drafts` and editor sheets. Each emitted entry is one line, and
   strings that do not fit their slot are not shipped. A string the patch
   blanks on purpose (`""`, a joiner whose meaning the neighbour carries) is
   not a line.
3. **Art lettering.** Every `text` cell and sprite segment in
   `art/*/manifest.json`, deduplicated within a manifest.
4. **Compositions.** Every alternative of `config/compositions.json`
   is rendered once from the shipped pieces, with sample names (Taro Tanaka,
   Shiori ...). These are sample renderings for checking how pieces join, and
   duplicates are dropped. The pieces are lines in their own right.

BATTLE and BUNKASD sheets are mini-game data, not text. The injector refuses
them, and they are not here.

## Known gaps

- **Speaker unresolved for about 13.8k lines.** These are lines in
  multi-speaker containers (GEKO, GASSHUKU, SHOGATU, SHUGAKU, XMAS, ENDING,
  BUNKA KS/KT ...) whose sheet `Speaker` cell is blank. `speaker.role` is
  `unknown` and `candidates` names the file's heroine where there is one.
  The `register` question is not asked for these lines, and the other
  questions see "unknown speaker". The speaker-flag audit
  (`context/audit/speaker-flags-*.csv`) lists about 1,000 rows where the
  sheet's speaker is suspected wrong; these carry a `speaker_suspect` flag.
- **Scene granularity.** The containers are flat pointer tables of strings
  interleaved with script nodes, with no per-line markers for event,
  location or date. The scene is per container (`context/SCENE-INDEX.md`),
  and the date scripts are in date-spot order. `event`, `location` and `date`
  are null.
- **Neighbours follow file offset order.** This is the script order inside
  a container, but a "conversation" is not delimited: the first and last
  lines of an exchange may show lines from the adjacent exchange.
  SPEAKTST/TEST_* are conversation banks, so their neighbours are often
  unrelated lines.
- **BUNKA KS_S6\* / KT_S6\*** are attributed to Mio Kisaragi and Ayako
  Katagiri from their content (`scene.confidence = name`).
- **Compositions** are samples, not every rendering. The repo's
  `tools/compose_check.py` renders and checks every combination from
  a patched build.
- **Art** cells hold text that is lettered into pictures. Their constraint
  is the cell size, and they are not re-flowable.
- **Not covered:** text that is still Japanese on the patched disc (baked
  art not yet converted, listed in `context/notes/BROKEN-STRINGS-AUDIT.md`
  §5.2), FMV subtitles (none), and strings the patch keeps Japanese on
  purpose (memory-card titles for the BIOS, `strcmp` literals).
  `data/not_shipped.jsonl` lists the container rows that stay Japanese, with
  the reason. Almost all are token-only script-node rows.
- **Status.** No row is marked `final` yet, and none is `machine`: the
  sheets are `draft` (first-pass LLM drafts) or `edited` (an editor pass).
