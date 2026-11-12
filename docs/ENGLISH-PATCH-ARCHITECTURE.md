# How the PS1 English patch works (architecture, 2026-10-10; naming 2026-11-02)

This is the **implementation map**, not a translation-quality sign-off or a
history of every draft. `config/english.json` is the authoritative patch
profile; the dated coverage, remaining-art and editorial status is kept in
the project's private docs. The underlying PS1 decompilation is an
independently verified **unchanged retail build**. Nothing in `src/main/matched/` (in toki1-decomp)
or `src/overlay/` needs to be modified to make English work: the patch builder
starts from byte-exact clean binaries and changes **copies** for the English
disc. The original game and the patched game must never be confused.

## 1. The path from English source to a disc

```text
sheets/*/*.csv  + config/*draft*.json
                    |                       + authored strings in english.json
                    v
              overlay_sheets.py -> inject.py (container data + DTE dictionary)
                    |                     |
                    +-> ui_strings.py ----+-> English strings + pointer edits
                    |                     |
   font/latin12.txt -> fontgen.py         v
   patch/*.c -----> IDO module -> build_patched.py
   art/*/manifest.json -------->| hooks / checked binary edits / NBN art
                                          v
                      clean exe + clean EXNs + retail disc files
                                          v
                    translated disc image + independently checked PPF3
```

Run `. .venv/bin/activate && python3 tools/build_patched.py
config/english.json`. The fast gate without the disc image (sync
check, tests, the two test profiles, the release profile with every text
gate, hook read-back; about 45 s with the clean bases built) is
`python3 tools/fast_check.py`. The builder checks clean inputs, enforces text
placement/readback/visible-text gates, rebuilds ISO sectors and file-system
metadata, audits the disc, and verifies the PPF against the unpatched Track 1.
Do **not** use `--no-text-gates` for a release. `english-drawlog.json` adds a
RAM-draw logger for testing; `english-debug.json` adds Konami debug features.
Both are separate test discs, not the release profile.

### What actually gets translated

* Container script rows in `SERIFU`, `SPEAKTST`, `BUNKA`, `MASTER`, `TAIIKU`,
  `SHIAI`, `TARA_OBJ`, plus sheets generated for `KOSIEN`, `URANAI` and
  `KARAKASI` (`containers_extra.json`). `SPEAKTST` is a test container and
  isn't evidence of a reachable route. Source CSVs live under
  `sheets/`; accepted DRAFT fallback text lives in
  `config/overlay_drafts.json` and `overlay_drafts.d/`.
* Main-EXE and overlay-resident strings, pointer-relocated if they do not fit
  in place; `ui_strings.py`, `overlay_sheets.py`, `english.json:main.strings`,
  `english.json:overlays`, `choice_overrides.json`, `tagged_rows_en.json`,
  and `compositions.json` supply the cases. A sheet wins over a draft.
* Texture text that is **pixels**, not engine strings: the NBN art manifests
  in section 5. Patching just the text tables cannot translate those screens.

`inject.py` repacks a **copy** of each fixed-size container: DTE compresses
common English sequences, and accepted strings may be relocated into spare
slots with their pointer words updated. Token compatibility, pointer safety,
size and readback are checked. A row that cannot be fitted is **not** silently
truncated; fallback to Japanese is recorded and becomes a build failure when
behind a live pointer. `build/patch/inject.report.json` describes placement.

## 2. Why a new text renderer was necessary

Retail text is predominantly Shift-JIS, one 12x12 glyph per 16x12 4-bpp VRAM
cache cell. It positions strings, speaker labels, choices and plate graphics
by *bytes* or a fixed kanji cell width. Straight ASCII injection would give
incorrect glyphs, truncated buffers, overflowing UI, broken controls, and
Japanese grammatical order in composed strings.

`patch/patch_text.h` and `tools/textcodec.py` agree on a
patch-only encoding: ordinary ASCII (`0x20..0x7E`); retained Shift-JIS pairs;
`0x01..0x1F` control/token bytes (`{P}`, `{G}`, `{F}`, `{opt}`, etc.);
DTE bytes (`0xA0..0xDF`, `0xF0..0xFE`) expanded by the same generated
80-slot dictionary on the tool and console sides. `{F}` composes given name,
space, family name. A one-byte token can redirect through a bounded module
string or long-name slot, where a literal English replacement would not fit.
Module strings stand in for composition pieces and for the reasoned
`draw_slots` of `config/compositions.json`. A draw slot is a standalone
string reached by a `lui`/`addiu` pair, with no pointer word to relocate
through, and every reader of it only draws it or `strcpy`s it.
`compose_check.py` checks that reader list, the slot's width and buffer, and
that the slot has no `{br}` in a one-row draw.
Do not send unconverted retail strings into the new parser and hope for the
best: the container injector rewrites the control vocabulary consistently.

The patch module links IDO C into a reclaimed section of the **copied** main
executable formerly occupied by Japanese kanji glyphs. Every extern, hook
and call-site name resolves to an address through the naming ledger
(`tools/patch_symbols.py` over `config/symbol_names.json` (in toki1-decomp)); a name the
naming track has since renamed fails the build with the old name, the
address and the new one, and `tools/sync_patch_symbols.py --apply`
updates the patch side. Hooks use
absolute retail addresses. `build_patched.py` checks module bounds and
`tools/verify_hooks.py` reads every hook word back from the build.
This costs some high-index kanji glyphs: the renderer draws an honest missing-
glyph box if a glyph was overwritten. The Latin name-entry page replaces the
hiragana page, and its Kanji tab stays inert rather than showing broken keys.
Japanese key grids still needed for kana/symbol selection are preserved.

### Renderer and typewriter (patch-only hooks)

| Original entry point | New code | Reason |
|---|---|---|
| `set_kanji_string` | `text_vwf.c` | Queue strings, allow one-character rows, zero blank-row counts, log actual drawn text in test builds. |
| `load_string` | `text_vwf.c` | Decode DTE/tokens, rasterise Latin font and retained Shift-JIS into the existing 384-cell VRAM cache. |
| `disp_string` | `text_vwf_draw.c` | Draw text **and shadow** at measured proportional offsets; respect retail advance for Japanese. |
| `k_disp_inc` | `text_reveal.c:pt_k_disp_inc` | One English glyph per tick, with English-only shorter intervals; keep the retail revealed-cell counter and completion contract. |

Latin glyph shapes and widths come from `tools/font/latin12.txt` via
`fontgen.py` (`build/patch/gen/font_latin.c`). The same file carries the
patch's own button icons from `tools/font/icons12.txt`: private
Shift-JIS codes `0xEF40..` (unassigned in JIS X 0208, so the retail range
table maps them to no glyph) that `pt_sjis_rows` draws instead of the box;
`textcodec.ICONS` spells them in strings. The game draws a prompt's button
with code, as a one-glyph string over the line (`get_pad_str` /
`get_pad_str2`, ETC's `get_etc_yes_button` / `get_etc_no_button`): the
retail circle and cross for a pad, which the renderer still draws from the
retail font, and for a mouse the kanji for "right" and "left", which the
module overwrites. The English strings name the mouse icons there; the
`glyphs` text gate checks every such button string is drawable
(`BUTTON_CELLS`). For normal English text, each
decoded glyph—including letters expanded from DTE—gets **one cache cell** and
a saved pixel x-offset; the retail reveal index then counts glyphs, not
packed groups of letters. Compare the essential rule:

```c
/* text_vwf.c, simplified: the flag means this cell is one glyph. */
patch_glyph_x[cell] = 0x8000 | pixel_x;
/* text_reveal.c: accelerate only flagged cells, still advance ONE cell. */
delay = glyph_cell ? max(1, (retail_delay + 1) / 3) : retail_delay;
```

This keeps typewriter speed near the previous packed-English implementation
while ensuring the *last letter*, not the last old 16-pixel strip, gates
scrolling, skipping, and voiced-line completion. Speed zero cannot be faster
than one glyph/frame. If a decoded entry would exceed 255 cells or the
remaining 384-cell cache, it falls back to the older packed-strip path;
`patch_glyph_fallbacks` counts these cases, and the original timing applies
there. If **even the packed text cannot fit**, it displays a missing-glyph
box where a slot exists and increments `patch_glyph_drops`, rather than
wrapping an 8-bit entry count or writing outside the cache. A full cache
cannot display even the box; the drop counter still records it. The
name-entry key grid uses its separate fixed-cell, centred mode.
Do not implement reveal solely by clipping sprites: retail would consider a
line complete before the clipped-out letters appeared.

## 3. Code consumers that had to change

Everything in this table is a **patch-only hook** configured in
`english.json`; retail-matching C is untouched. Names are documentary;
addresses, not mutable names, resolve the actual patch sites.

| Patch file | Hooked original functions | Why |
|---|---|---|
| `text_msg.c` | `func_80081398` -> `pt_schedule_analyze`; `func_80082F60` -> `pt_choice_shuffle` | Decode and wrap longer lines, schedule per-row breaks, preserve choice/input semantics. |
| `text_field.c` | `sndisp` -> `pt_field_message`; `sndi` -> `pt_field_line`; `gnsx` -> `pt_speaker_label` | Field/phone/prologue text, quote/bracket, pixel-width speaker labels and wrapped rows. Rows beyond the first three wait hidden at y=82 until the stock scroller activates them. |
| `text_event.c` | `serifu_cmd_exec` -> `pt_event_message` | Event speaker tags, narration/sound cues, XA wait, prefixed lines and control-byte semantics. |
| `text_choice.c` | `menu2_init`, `menu3_init` -> `pt_menu2_init`, `pt_menu3_init` | Two-/three-answer geometry, cursor/hit areas measured in pixels. |
| `text_misc.c` | `basyo_init`, `girl_menu_set`, `telephone_choice_menu_init`, `get_p_name` -> `pt_basyo_init`, `pt_vacation_day_init1`, `pt_telephone_choice_menu_init`, `pt_get_p_name` | Place-name plate widths, heroine grid, phone-book columns, English-order player names. |
| `text_names.c` | `strcpy`, `strcat`, `strncat` -> `pt_strcpy`, `pt_strcat`, `pt_strncat` | Composed English needs longer safe names and token-aware word order, not raw byte concatenation. |

The main profile also redirects **six album-card `strncat` call sites** to
`pt_name_hold`, `pt_name_put` and `pt_strncat_nick`. The `ETC` overlay has one
`strncat` call-site redirect to `pt_full_name_cat` for the exam board. Those
are call-site rewrites, *not* blanket changes to all callers.

### Overlay-specific hooks

| Overlay | Original -> replacement | English-specific constraint |
|---|---|---|
| `NAME_ENT` | `name_ent_hira_disp` -> `pt_name_page_latin`; `name_ent_tab_index_set` -> `pt_name_band`; `name_ent_glyph_write` -> `pt_name_key`; `name_ent_key_cursor_set` -> `pt_name_cursor`; `name_ent_record_set` -> `pt_name_commit` (`text_name_ent.c`) | Latin keyboard, grid cursor, width-safe names, inactive Kanji tab. **Configured `pt_name_key` address is `0x80134254`** despite the documentary name; don't guess it from the name. |
| `SHOUGATU` | `shougatu_serifu_step` -> `pt_shougatu_greeting` (`text_ov_labels.c`) | Width/English-order New Year greeting. |
| `BUNKA_SD` | `bunka_sd_rollcall_step` -> `pt_bunka_sd_rollcall`; `bunka_sd_result_step` -> `pt_bunka_sd_announcer` (`text_ov_labels.c`) | Stage speaker names. |
| `BUNKASAI` | `bunkasai_main8` -> `pt_bunkasai_photo` (`text_ov_bunkasai.c`) | Composed club photo caption. |
| `DATE2` | `date2_sched_menu_disp` -> `pt_date2_lyrics`; `date2_song_menu_init` -> `pt_date2_song_menu` (`text_ov_date2.c`) | Karaoke fragment spacing and song-menu hit box. |
| `ENDING` | `ending_song_line_disp` -> `pt_ending_song` (`text_ov_labels.c`) | Ending song/credit label alignment. |

Other Japanese strings are rewritten as *data* by the injector, not by
inventing C hooks for every line. English syntax sometimes requires a
composed-string override rather than a 1:1 translation: the Shiori club
walk-home line, for example, reads the live club buffer as
`the Literature Club` (route `hero.shiori.walkhome_club`); `compositions.json`
records audited sites and accepted Japanese exceptions.

## 4. Build invariants and text coverage

* Source discovery and exceptions: `tools/text_sources.py --fail-on-visible`
  inspects both English sheets and unchanged Japanese still behind *live*
  pointers. `tagged_rows_en.json:keep` and `compositions.json:kept_japanese`
  document deliberate exceptions, not blank cheques for undrawn text.
* `tools/text_gates.py`: eight independent gates—`fit`, `records`,
  `compose`, `sites`, `codes`, `readback`, `glyphs`, `uncovered`. A successful
  compiler/link or `check-raw` is NOT proof of a correct English disc.
* `tools/coverage_campaign.py`: reproducible emulator routes and RAM
  draw log (`config/coverage_plan.json`, `coverage_review.json`). The
  route campaign is runtime evidence, not a build gate or editorial approval.
  The club route additionally checks decoded live memory and English draw
  count. `--with-deps` includes saved-card producers as well as state parents.
* Release `build_patched.py`: bootable ISO sector/EDC/ECC audit, exact-size
  containers, overlay checksums, and independent PPF3 self-check. The
  `english-drawlog` profile uses proven-dead extra code regions for its
  instrumentation; `extra_keep_objects` pins the renderer's deliberately
  poked draw-hook data in the main region. The separate `english-debug`
  profile extends its kanji-block region by 0x400 bytes to fit its debug
  font and glyph-reveal code; the release profile does **not**. The extra
  regions are re-proven dead by `free_regions.py` on every build, not taken
  on faith.

Dated measurements belong in the project's private status docs; never promote a 2026-10-10 snapshot to an eternal promise. The source sheets
and many art credits remain **DRAFT** pending human editing. Zero Japanese
*text draws* does not imply zero Japanese pixels: some instruction panels,
retained key grids, and other baked assets require a separate art pass.

## 5. Art and non-text changes

The following are the **tracked art sources changed by the patch**, not
copyrighted retail sheets. `tools/nbn_inject.py` applies each
`art/<name>/manifest.json` against its exact expected retail input;
it verifies palette, cell geometry and affected file bytes. The game-specific
routing and cell coordinates live in the manifests, not duplicated here.

| Manifests | On-screen reason |
|---|---|
| `TITLE` | Title menu lettering, including highlighted Options. |
| `MAINROM` | Common HUD/menu sprite labels; the night planner's save badge (SAVE). |
| `FILESEL`, `NAME_ENT` | Memory-card/album screens and the Latin name-entry page. |
| `EXAMINE` | Exam-result labels. |
| `ALL_C` | All-clear group picture labels. |
| `OMIKUJI` | New Year's fortune card. |
| `B_BUNGEI`, `B_DENNOU`, `B_SUISOU`, `B_TENSOU` | Festival club-stage art. |
| `BATTLE_HUD` | RPG battle HUD; one manifest is copied to eight destinations. |
| `STAFF_R` | Latin glyph cells and rewritten draft credit sprite frames. |
| `SPSETU`, `KASETU`, `TASETU`, `NINSETU`, `SHATEKI`, `KINGYO` | Sports-day and summer-festival mini-game instruction panels (mod/srn tile maps, re-tiled by `tools/tilemap_panel.py`).; SHATEKI's FINISH! banner and KINGYO's Today's Catch result board (sprite pages). |
| `OPTION` | Title Options sub-lists (sprite frames rebuilt from a Latin glyph set). |
| `TAIIKU_CARDS` | Sports-day cue cards Go! / Right / Left (SPOON, with byte copies in NININ and TAI_BG). |
| `TAMA` | Ball-roll course-out banner BALL / OUT! (scaled font in a CLUT ramp of TASETU.BIN). |
| `TACOTEX` | Stardust Symphony EX (TACO) OPERATIONS tutorial pages: the 12-px font in the retail chrome ramp, each line sliced across the cels that draw it. |
| `CUT_10` | Rei Ijuin's prologue name card REI IJUIN: a logotype set in the hand-authored display face `tools/font/display_caps.txt` (`tools/artface.py`), in the card's own gold ramp and keyline. |

These 24 source manifests can affect more than 23 disc files (for example the
battle copies). Every lettering PNG must be the exact render of its manifest
text from a declared source: the 12-px Latin font, or (a `face` cell) a
hand-authored vector face under `tools/font/` whose SHA-1 the manifest
records (`nbn_inject.py` refuses any other pixels, a face file that no
longer hashes as declared, and a face file without the authorship header;
`pc/tools/test_translation_pack.py` (in toki1-pc) holds the negative controls: an edited
pixel, a crop of the retail kanji, an edited face file). Baked Japanese still
on the manual-review list (e.g. the sports-day name tags) is
**not** falsely labelled translated. Raw retail assets, disc dumps and generated files stay out of
source control. The art-by-art analysis is kept in the project's private docs.
