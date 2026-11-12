# Text control codes (script containers and in-game messages)

Derived from the three parsers in the matched C, not guessed:
`src/main/matched/msg_str_disp.c` (in toki1-decomp) (message renderer), `serifu_cmd_exec.c`
(choice splitter), `kega_hassei.c` (three-line formatter).  Every dialogue
string is NUL-terminated Shift-JIS; the bytes below are the only single-byte
values that appear inside retail text.  The sheets show them as `{tokens}` and
`inject`/`check` convert them back.  **A translator must keep every token of
the source string in the target string** (the QA check enforces this); order
may change, `{br}` count may change.

| Token | Byte | Meaning | Expands to (runtime) |
|---|---|---|---|
| `{br}` | 0x20 `' '` | line break inside a message box | — |
| `{opt}` | 0x71 `'q'` | choice separator: a string with `{opt}` is a list of player replies (up to 3); also used as a message break in some files | — |
| `{P}` | 0x50 `'P'` | the **player's name as the current heroine addresses him**: his family name + 君, or his given name / nickname + さん, chosen per heroine by affection (`func_80051928` copies `D_800EE834`/`D_800EE83C`/`D_800EE844` = player family / given / nickname from the save, then `D_800B9B20` 君 or `D_800B9B24` さん). A line containing `{P}` is therefore the **heroine's** line (corrected 2026-10-04; earlier text said "heroine's family name") | `D_800D067C`, set by `func_80051928` |
| `{G}` | 0x47 `'G'` | the current heroine's **given name** | `D_800D0690`, set by `func_80051858` |
| `{p}` | 0x70 `'p'` | the **player's family name** (as entered on the name screen) | `D_800D066C` ← save data `D_800EE834` |
| `{m}` | 0x6D `'m'` | the **player's given name** | `D_800D0674` ← `D_800EE83C` |
| `{F}` | 0x46 `'F'` | the player's **full name** (`"%s%s"` of family + given, no space) | format `D_800B8A08` |
| `{Y}` | 0x59 `'Y'` | the friend's name **好雄 (Yoshio)** | literal at `D_800B8A00` |
| `{S}` | 0x53 `'S'` | runtime string (school year / subject text; set per scene) | `D_800D073C` |
| `{O}` | 0x4F `'O'` | runtime string | `D_800D0748` |
| `{W}` | 0x57 `'W'` | runtime string | `D_800D0750` |
| `{A}` | 0x41 `'A'` | runtime string | `D_800D075C` |
| `{M}` | 0x4D `'M'` | runtime string | `D_800D0780` |

Notes for translators
- `{F}` is family+given with no separator (Japanese order). English needs
  given-then-family with a space; that is a **code change** (format string
  `%s %s` and swapped arguments), tracked in the readiness audit, not something
  to work around in the text.
- `{P}` carries an honorific decided by the engine (`func_80051928` chooses
  surname+kun / given name+san / nickname+san from the heroine's affection).
  This is the address table STYLE-GUIDE §3 describes; the English build will
  localize it once ("Fujisaki" / "Shiori"-style forms are the HEROINE'S name
  and are a different thing: `{P}` is always the player). Do not hand-write
  honorifics into lines.
- A leading token (`{G}、ごめんね`) is common. The old run-scan sheet dropped
  those tokens; the exact sheets under `sheets/` keep them.
- **ASCII letters that collide with control bytes**: in the retail engine the
  bytes `P G p m F Y S O W A M q` and space are commands, so plain English text
  cannot be stored as single-byte ASCII until the parsers are re-pointed to
  control bytes below 0x20 (see the readiness audit, item 2). Translators
  write normal English; the injector, not the translator, handles encoding.
