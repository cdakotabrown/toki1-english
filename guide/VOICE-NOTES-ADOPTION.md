# Voice notes from a Tokimeki Memorial video essay — assessment and adoptions

The transcript itself is **not** in this repository: it is a third-party,
machine-generated transcript of someone else's video essay, and republishing it
would not be ours to do. This file is the record of what the localization took
from it; every claim below is also checkable against the sheets and the game.

Decided 2026-09-26 (producer). The source is a Whisper transcript of Tim
Rogers' Action Button video essay on the 1994 game, post-processed into a guide.
It is secondhand and machine-transcribed: character kanji are "from general
knowledge", gameplay facts and timestamps are unverified, and at least one name
is wrong. It is used here as **evidence about tone and voice**, never as a source
of facts about the script; the script itself (the sheets) wins on every conflict.

## Adopted (now codified in STYLE-GUIDE.md, CHARACTER-BIBLE.md, GLOSSARY.csv)

| # | Adoption | Where it landed |
|---|---|---|
| 1 | **Forms of address are a first-class signal.** Heroines move from surname (+kun) to the player's chosen nickname as affection rises; pronoun shifts (anata) mark the same thing. The engine inserts the player's name through tokens, so the *choice of form* is a code-side address table to localize once, and hand-written lines must never flatten or invent an address form. | STYLE-GUIDE §3 rewritten; engineering item added to the readiness audit backlog (address table) |
| 2 | **Tone principle:** sincere, bittersweet, never parodic; humour is gentle and situational; do not make any scene lighter than the source. | STYLE-GUIDE §2 new principle 6 |
| 3 | **Yuina Himoo's voice** is dry, deadpan, matter-of-fact and dismissive; her grandiosity is delivered flatly, not theatrically. | CHARACTER-BIBLE HI row rewritten; **editor flag on `sheets/SERIFU/DATE_HI.csv`** (drafted before this change, leans theatrical) |
| 4 | **Ayako Katagiri's mannerism is literal English phrases** ("Thank you", "Good timing", "Oh really", "It's so bad"). Two candidate renderings are recorded; the choice stays **OPEN** for the producer. | CHARACTER-BIBLE KA row (both options); DATE_KA drafted with option B |
| 5 | Bible refinements: Mira is vulnerable under the vanity; Miharu is cryptic; Nozomi secretly wants her femininity respected; Saki is practical and direct; Yumi Saotome is loud and emotionally transparent. | CHARACTER-BIBLE rows |
| 6 | **Cultural systems stay Japanese and are glossed lightly, never Americanized**: April school year, three-year high school, clubs, Valentine's Day / White Day, giri-choco, omikuji, bunkasai, seasonal references. | STYLE-GUIDE §5 list; GLOSSARY rows |

## Not adopted

- ~~**"Megumi Mikihara"** — transcription error; she is **Ai Mikihara** (美樹原愛).~~
  **RETRACTED 2026-11-03:** the review was right. 美樹原愛 is officially read
  みきはら めぐみ (Konami's 2025 character site), so she is **Megumi Mikihara**;
  the kit, glossary and sheets were switched mechanically (the research
  note is kept in the project's private docs).
- Dubbing / audio recommendations, release-history and business commentary —
  out of scope (this is a text localization).
- Gameplay strategy, stat thresholds, timestamps — irrelevant to the script and
  unverified.
- The reviewer's personal verdicts on routes and characters — not voice
  guidance.

## Correction the review surfaced (independent of the doc)

Our own kit had 紐緒結奈 as "Yumi Himoo". She is **Yuina Himoo**; Yumi is Saotome.
Fixed 2026-09-26 in the bible, glossary, extractor speaker map and every HI sheet;
no translated line used the wrong name.

## Editor actions queued by these adoptions

1. `DATE_HI`: re-voice Yuina toward deadpan (adoption 3). **Partly done 2026-09-26:** the TEST_HI bank was drafted to the revised voice and its English was propagated to every identical string in DATE_HI; the DATE_HI-only lines still need the editor pass.
2. All eleven `DATE_*` sheets: audit any hand-written address of the player
   (surname vs nickname) against adoption 1; most lines use tokens and need
   nothing.
3. Producer decision on Ayako (adoption 4), then a consistency pass on `DATE_KA`.
