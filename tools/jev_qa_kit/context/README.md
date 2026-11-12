# context/

This is reference material for the people who label and fix lines. The
runner also quotes parts of it in the state it sends to Jev. Everything is
copied from the repository when the kit is built; the source paths are given
below.

| file | what | source |
|---|---|---|
| `characters/<slug>.md` | one voice bible per character: the verbatim row of the character bible (role, Japanese voice, English voice), followed by the shared "forms of address" and "shared conventions" sections | `guide/CHARACTER-BIBLE.md` |
| `characters/index.json` | the same rows as data. The `register` question's `voice_note` comes from here, keyed by `speaker.bible` in `lines.jsonl` | generated |
| `CHARACTER-BIBLE.md` | the full bible | `guide/` |
| `STYLE-GUIDE.md` | the English style guide: voice principles, names and honorifics (§3), mechanics, consistency, do/don't | `guide/` |
| `style_excerpts.json` | the style-guide sections by topic. `honorific_policy` quotes §3 (condensed to its address and honorific bullets) and `tone_shift` quotes §2 principles 2, 4, 5 and 6 | generated |
| `GLOSSARY.csv` | terms, places, items and characters (`Japanese, English, Category, Notes, Status`). The `terminology` question gets the matching rows, from `glossary_hits` in `lines.jsonl` | `guide/` |
| `VOICE-NOTES-ADOPTION.md` | which tone and voice notes were adopted, and the open producer decisions (Ayako's English loanwords; Yuina re-voiced deadpan) | `guide/` |
| `CONTROL-CODES.md` | the `{tokens}`: `{br}` break, `{opt}` reply separator, `{P}` (the player as the heroine addresses him), `{G}` (the heroine's given name), `{p}` `{m}` `{F}` (the player's names), `{Y}` (Yoshio), `{S}` `{O}` `{W}` `{A}` `{M}` (runtime text) | `guide/` |
| `WORKFLOW.md` | how the sheets are produced, reviewed and shipped: columns, status ladder, QA gates | `guide/` |
| `audit/` | the 2026-10-02 localization audits: speaker flags, voice fixes, consistency and glossary unifications, budget. Their findings are also in `lines.jsonl` `flags` | `guide/audit/` |
| `SCENE-INDEX.md`, `scene_index.json` | container → which scene it is, the heroine, the line count, the file to edit, and how sure the description is (`docs` or `name`) | generated |
| `notes/` | patch status, the broken-strings audit, the visual sweep, the text-draw inventory (window geometry), and the game-flow docs for dates, seasonal events, endings and phone calls | the project's docs, when the kit is built in the private monorepo (otherwise left out) |

The readable forms in `lines.jsonl` (`jp_readable`, `en_readable`) write the
tokens out in words: `{br}` becomes ` / `, `{P}` becomes
`[PLAYER, as she addresses him]`, and so on. Reply menus become
`Reply 1: ... || Reply 2: ...`.
