# CLAUDE.md

Rules for agents in **toki1-english**, the English translation and PS1 disc
patch for *Tokimeki Memorial: Forever with You*. Layout and commands:
`README.md`; how the patch works: `docs/ENGLISH-PATCH-ARCHITECTURE.md`.

## Never

- Commit anything from the disc: Japanese text, extracted art, patched files,
  the PPF, `work/`. The sheets carry no Japanese; it is read from the
  player's disc (`tools/retail_text.py`). `make lint` fails on a tracked or
  staged `work/` file and on Japanese outside `Notes` (10+ characters there).
- Rewrite English lines as a side effect of tool work: `sheets/` has its own
  review track.
- Write into `../toki1-decomp` (read it only) or build a path into it from
  this repository's root: `tools/roots.py` `locate()` is the only place that
  maps a path to the part that owns it.
- `git add -A`; commit with explicit paths.

## Paths are monorepo paths

This tree is exported flat from a monorepo whose paths differ
(`translation/localization/sheets/`, `src/patch/main/`, `config/patch/`,
`tools/patch/`). Code and data name an English file by that monorepo path
and one table maps it: `ENGLISH_LAYOUT` in `tools/repo_paths.py`, applied by
`tools/roots.py` (`locate()`, `SHEETS`, `GUIDE`, `ART`, `PATCH_SRC`,
`PATCH_CONFIG`). So `config/english.json` listing `src/patch/main/*.c` is
right. Never build a path from `ROOT` or `__file__` by hand. Fix tools in
the monorepo; this tree is regenerated.

## Gates

- `make patch` gates itself (loader contracts, disc audit, PPF read-back,
  text gates) and is the authority on fit. A green compile is not a correct
  disc: read the gate output. A stale `build/patch/gen/dte.json` can fake a
  FALLBACK failure: delete it first.
- The lint reuses the gates' code (`check_translation.row_findings`,
  `inject.fit_text`, `text_gates.wide_words`, `japanese_text.py`): change a
  rule there, never in a copy.
- After a decomp rename: `python3 tools/sync_patch_symbols.py --apply`
  (`--check` in CI); never relink a name by hand.
- Before a push: `make ci` must end `CI would pass`; change
  `tools/ci/run_ci_locally.sh` with `.github/workflows/build.yaml`.
- Patch C is IDO 5.2, C89: `/* */` comments only.
- No visible game windows; emulator tools run headless.
