# toki1-english

An unofficial English translation of **Tokimeki Memorial: Forever with You**
(Konami, 1995, PlayStation, SLPS-00065), and the tools that build an English
disc image and a PPF patch from your own Japanese disc.

Unofficial fan project, not affiliated with Konami or Sony. No game data is
included: no disc, executable, Japanese script, art or audio.

## Status

Every line started as a machine first pass (each row's `Notes` says how it
was edited and checked since). Of the script's 47,380 rows, 46,792 are
`edited`, 583 are still `draft` and 5 are `untranslated`; none is marked
`final` yet. Three optional pieces of signage art are still Japanese: the
culture-festival drama act cards and hero-show logo, and a tiny line on
the album cover.

## Disc

The patch reads your disc from `../toki1-decomp/disks/` (names in
toki1-decomp's README); Japan, Rev 1, raw BIN/CUE:

| file | size | SHA-1 |
|---|---:|---|
| Track 1 | 702,104,928 | `7b2f72d1319db27d0700070aa0bffe886b5ef7a4` |
| Track 2 | 45,151,344 | `6cdd8500168ab4ecb18b78ef7589586d26bc4501` |
| `SLPS_000.65` (inside Track 1) | 690,176 | `2d8d474816e4bf937b09dc3b017f550f7ce4e14b` |

## Build

Needs `../toki1-decomp`, set up and built, and Python 3.10+.

```bash
(cd ../toki1-decomp && make setup setup-ido52 check-clean-main check-exn-all)
. ../toki1-decomp/.venv/bin/activate && pip install -r requirements.txt
make check-prereqs
make patch          # -> build/patch/english.ppf, build/patch/iso/patched_disc.cue
make gates test ci  # re-check the build, unit tests, the CI jobs
```

## Improve the translation

1. Find the line you saw in game: `grep -rn "Nice weather" sheets/`.
   One CSV per game file, one row per line.
2. You edit `English`, `Status` (`draft` / `edited` / `final`), `Notes`, and
   `Speaker` if wrong. `ID`, `File`, `Offset`, `MaxBytes`, `PtrSite`, `Kind`
   and `Tokens` come from the disc: never edit them.
3. Rules (details in `guide/`: style guide, glossary, control codes,
   character bible):
   - keep every token the row's `Tokens` lists (`{G}`, `{opt}`...; `{br}` may move);
   - printable ASCII only; names as `guide/GLOSSARY.csv` spells them;
   - never paste Japanese: a note may quote a word, not a line.
4. `make lint` checks your edit without the disc; `make hook` runs it
   before every commit.
5. With your disc: `make hydrate` writes `work/sheets/` with the Japanese
   beside each row (never committed); edit there, then `make fold`. `make
   patch` runs the full gates and has the last word on fit. Try the result
   with the PPF, the patched `.cue`, or toki1-pc beside this repository.
6. Open a pull request. CI runs the lint (rows unchanged against `main`, no
   Japanese, tokens, fit) and the unit tests.

## Layout

| path | what |
|---|---|
| `sheets/` | the translation: `<DIR>/<FILE>.csv` |
| `guide/` | style guide, glossary, character bible, control codes |
| `config/` | patch profiles (`english.json` is the release), drafts, symbol pins |
| `patch/` | the patch code (IDO C); `patch/debug/` the debug build |
| `art/` | English lettering: PNG cells and manifests |
| `tools/` | build, gates, lint, hydrate; `reviewer/` sheet editor; `jev_qa_kit/` QA kit |
| `docs/` | how the patch works |
| `work/` | yours: hydrated sheets (ignored) |

## Licence

MIT for the project's own work (`LICENSE`). The translation is a fan
translation of Konami's text; the game and its text are Konami's
(`THIRD-PARTY.md`).
