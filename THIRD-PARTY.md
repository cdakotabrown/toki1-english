# Third-party components

The project's own code, translation, art and documentation are MIT (see
`LICENSE`). Everything below is someone else's, and keeps its own terms. This
list exists so the boundary is checkable rather than remembered: a component is
either here with a licence, or it is not in the tree at all.

## The game

**Tokimeki Memorial: Forever with You** (SLPS-00065, Konami, 1995) is © Konami;
"Tokimeki Memorial" is a Konami trademark. The project is not affiliated with
Konami or Sony. The repository holds no disc images and none of the game's data
files, Japanese script text, art, audio or video. It does hold an unofficial
English translation of the script (`sheets/`, `config/`); that is a
fan translation of Konami's text, and the project claims no right in the
underlying work. The same holds for the English lettering drawn for the game's
pictures (`art/`): the PNG cells are the project's own drawings of
English words, placed into the game's files on your machine. The localization
sheets carry no Japanese: each row names the file, offset and byte budget of
the retail string, which the tools read from your own disc (owner decision D4,
`tools/retail_text.py`).

The disc-derived inputs (the retail executable and overlays, the extracted
file tree) are generated on your machine from your own disc, inside the
toki1-decomp checkout this repository builds against, and the paths that hold
them are gitignored there. The patch build writes only under `build/` here.

## Used at build time, not part of this repository

| Component | Where it comes from | Terms |
|---|---|---|
| **toki1-decomp** (the decompiled C, `include/`, the symbol ledger, the overlay and clean-build tools) | the sibling checkout (`tools/repo_paths.py`) | MIT, with its own third-party list (its `THIRD-PARTY.md`) |
| **IDO 5.2** compiler, via ido-static-recomp | vendored in toki1-decomp (`tools/ido-static-recomp/`) | proprietary SGI/MIPS code and an upstream without a stated licence; see toki1-decomp's `THIRD-PARTY.md` |
| **GNU binutils** (`mipsel-linux-gnu-ld`, `-objcopy`, `-nm`) | your distribution | GPL-3.0-or-later |
| **Pillow**, **numpy**, **pyelftools** | PyPI (`requirements.txt`) | HPND (Pillow), BSD-3-Clause (numpy), Unlicense (pyelftools) |

## In this repository

| Component | Where | Terms | Notes |
|---|---|---|---|
| **jev_qa_kit** | `tools/jev_qa_kit/` | Project-written | `LICENSE-NOTE.md` states it must never be shipped containing retail script text -- it operates on the player's extracted text |
| **Reference-emulator hooks** | -- | not distributed | `tools/regtest_screens.py`, `coverage_campaign.py`, `debug_run.py` drive an existing PS1 emulator's headless "regtest" host that you supply (`REFEMU_REGTEST`, or toki1-pc's `pc/tools/refemu.py`); no emulator code is in this repository |

If you find a third-party file that is not on this list, that is a bug: add it
with its terms or take it out.
