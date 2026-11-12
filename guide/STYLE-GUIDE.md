# Tokimeki Memorial: Forever with You — English Style Guide (v0.1, 2026-09-26)

Status: DRAFT for client sign-off. Items marked **OPEN** are decisions the
producer must make before the translator starts; everything else is the
default the pilot (`sheets/SERIFU/DATE_AS.csv`) was written to.

## 1. Product and audience
- Platform text for a 1995 PlayStation dating sim set at Kirameki High School
  over three school years. Target reader: English-speaking players 15+, who
  know anime conventions but should never need Japanese to follow a line.
- Register: contemporary, natural spoken English. No archaic "thee", no
  Britishisms unless a character calls for it, no internet slang that dates
  faster than the source.
- Rating equivalent: teen. The Japanese is clean; keep it clean.

## 2. Voice principles
1. **Character first.** Every heroine has a distinct idiolect (see
   `CHARACTER-BIBLE.md`). A line must sound like *her* before it sounds like a
   good sentence. Shared vocabulary across heroines is a defect.
2. **Say what the line does, not what it says.** Japanese dialogue in this
   game is short, reactive and full of set phrases; translate the function
   (tease, deflect, sulk, flirt) into what an English teenager would say in
   that spot. Literal renderings of "sou da ne. sou shiyou ka" ("That's right.
   Shall we do so?") are wrong; "Sure. Let's." is right.
3. **Player-choice strings are the player's voice.** He is an ordinary,
   slightly awkward high-school boy. Choices come in threes: typically
   sincere / cocky-or-teasing / dismissive. Keep that contrast visible so the
   player can predict the girl's reaction (the game's core loop).
4. **The heroines react to the choice, and the same line is reused across
   dozens of scenes.** A girl's reply must work after *every* choice that
   routes to it. Never translate a reply with a specific callback to one
   choice unless the source does.
5. **No added jokes, no softened insults.** Yuko calling something "cho dasaa"
   is "That's so lame"; do not upgrade or downgrade the sting.
6. **The game is sincere.** Its tone is bittersweet and nostalgic, never parodic;
   the humour is gentle and situational. Do not make any scene lighter, campier
   or more ironic than the source, and do not play the romance for laughs. When
   in doubt between a funnier line and a truer one, the truer one wins.

## 3. Names, honorifics, address
- **Name order: given name first** ("Shiori Fujisaki") in all prose. **Decided
  2026-11-05 (D1).** The festival profile screens keep their two fixed
  columns, surname then given name, as a display convention (no engineering swap).
- **Forms of address are a first-class signal in this game.** A heroine addresses
  the player by surname (+kun) early and switches to his chosen nickname (or given
  name) as affection rises; a shift to あなた marks the same thing. The engine
  inserts the player's name through tokens (`{p}` family, `{m}` given, `{F}` full)
  and the *choice of form at each affection level* is a code-side table that
  engineering localizes once. Rules for the text:
  - Never hand-write the player's name or an address form into a line; keep the
    token the source has, in English word order.
  - Never flatten the progression by translating an early surname line as if it
    were intimate, or a late nickname line as if it were formal. Carry the
    register (formal vs warm) in the surrounding words.
  - Heroine address forms "Kagami-san" / "Kisaragi-san" in the player's own lines: surname
    without honorific ("Kagami", "Kisaragi"), because the switch to her given name
    is the player's side of the same signal.
- **Honorifics are dropped** (-san, -kun, -chan) except:
  - 先輩 → "Senpai" only from Yumi Saotome, as a form of address (it is her
    whole characterization). **Decided 2026-11-05 (D2): keep "Senpai"**, only
    where the Japanese has the address (never added), capitalized, as a
    vocative at a natural clause start or end ("Because I love you, Senpai...").
  - 先生 → "Mr./Ms. <Surname>" or "Sensei" for the coaches. Default: Mr./Ms.
- The honorific the engine adds to `{P}` (family name) is a code-side table and
  will be localized once (see CONTROL-CODES).
- 好雄 (the friend) → **Yoshio**. The player's default name is whatever the
  player typed; never assume it.
- **Romanization of names: Hepburn, long vowels dropped** (producer decision
  2026-11-03). A long vowel written in kana as a doubled vowel (おう / おお /
  うう / ゆう ...) is spelled with ONE letter, no macron and no doubling:
  ゆうこ **Yuko** (not Yuuko), いじゅういん **Ijuin** (not Ijuuin). Macrons
  (Yūko) are out because the 12-px Latin font has no such glyphs. Two
  vowels that belong to separate kana are not a long vowel and are both
  written: ひもお **Himoo** (ひ・も・お), さおとめ **Saotome**. The rule
  covers every place a name ships: sheets, overlay and UI strings, art
  (name cards, Options lists, the staff roll) and the PC layer. Code
  identifiers (`tel_ijuuin_*`, `girl_ijuuin`) are not shipped text and keep
  their names.
- メグ (Shiori's nickname for Megumi) stays **Megu** (decided 2026-11-03).

## 4. Mechanics
- **Line breaks.** `{br}` is a hard break inside the message window. The
  Japanese window shows about 16 full-width characters per line; the English
  build renders half-width ASCII, so plan on **~32 characters per line, 3
  lines per window** until the engineering team confirms the final font
  metrics. Break at phrase boundaries, never mid-word. The count of `{br}` may
  differ from the source.
- **Choices.** `{opt}` separates the (up to three) replies inside one string.
  Each reply should fit on one line (≤ 32 chars) because the choice menu does
  not wrap. **OPEN**: engineering to confirm the choice-window width.
- **Budget.** Each row carries `MaxBytes`, the space the original string
  occupies. English is 1 byte per character on the ASCII path, tokens 1 byte.
  Do **not** self-censor to fit; write the right line, the QA tool reports the
  overflow and engineering relocates strings. Rows over 255 bytes are hard
  failures (engine buffer).
- **Punctuation.** ASCII only: `. , ! ? ' " ( ) - : ;` plus `...` (three
  periods, not the ellipsis glyph) and `--` for a dash. Straight quotes.
  「」 → double quotes. Japanese emphasis dots/long vowels ("cho dasaa-tt")
  become spelling or punctuation, not stretched letters ("laaame" is fine
  once per scene, not as a system).
- **Sound effects / interjections.** Translate to English equivalents
  (「えぇーっ」→ "Whaat?" / "No way!", 「ふーん」→ "Hm." / "Huh."). Never
  romanize ("Eeeh").
- **Stage directions.** Parenthesised inner thoughts (a bracketed "did I make her angry" line)
  stay parenthesised: "(Did I make her mad...?)".
- **The narrator lines** of the "... to iu koto wo kikidashita" frame (info gleaned from
  conversation) use a fixed frame: "You learned that ..." (**decided
  2026-11-05, D3**; a line that clearly conveys reluctant disclosure may be an
  explicit exception).

## 5. Consistency
- Terms, places and items live in `GLOSSARY.csv`; the glossary wins over
  taste. Add a row before inventing a term.
- Identical Japanese lines should be translated identically **within one
  speaker** (the sheet's TM check reports divergence). Across speakers the
  same Japanese may and often should differ.
- Seasonal and calendar text (holidays, school events) follows the glossary
  so UI, dialogue and the scheduler agree.

## 6. Do / Don't quick list
- Do keep lines short; Japanese teens speak in fragments and so do English ones.
- Do preserve the emotional beat order inside a line (surprise → verdict).
- Don't translate 「ね」/「よ」 tags as "right?"/"you know" every time.
- Don't localise pop-culture references to Western ones; keep 「ｐｒｆ」 (the
  in-game band) as "prf".
- **Cultural systems stay Japanese and are glossed in-line, never replaced**:
  the April school year and three-year high school, clubs as serious commitments,
  Valentine's Day (girls give) / White Day (boys return), giri-choco ("obligation
  chocolate"), omikuji fortunes at New Year, the autumn culture festival
  (bunkasai), seasonal set phrases. Use the GLOSSARY renderings; add a short
  natural gloss the first time a term appears in a scene ("giri-choco -- the
  obligation kind"), never a footnote and never an American substitute (no prom,
  no homecoming, no Halloween).
- Don't gender-neutralise the heroine's lines to make them reusable; they are
  per-heroine files (DATE_XX, EVENT_XX, TEST_XX) and only reused for her.

## Producer decisions 2026-11-05 (escalation round 1)

Locked (house style):
- **D1** name order: given name first in prose; profile columns stay surname / given.
- **D2** Yumi's "Senpai": kept, only where the Japanese has it (see section 3).
- **D3** narrator info lines: "You learned that ...".
- **D4** Ayako Katagiri's English loanwords: **option A**. Render each as marked,
  slightly set-apart textbook English ("Oh, really!", "Good timing!", "Thank you
  very much!") with the surrounding English kept smooth; no French or Italian
  flourishes. An English loanword followed by its Japanese equivalent becomes a
  natural reinforcement ("Thank you! Really, thanks!"), not a duplicate. Keep a
  list of her marked phrases so polishing does not flatten them.
- **D11** the winter date spot is "the ski resort" (menus "Ski Resort"); "the
  slopes" where the Japanese means the runs.
- **D13** phone answer: "Hello, this is the {p} residence." where the box allows;
  "Hello, {p} residence." otherwise (keep the source's token).

Working (adopt, review on screen before final):
- **D5** omikuji ranks: Best / Good / Fair / Minor / Later / Bad (Worst for 大凶) in
  5-character fields; "Best Fortune" ... "Worst Fortune" where there is room.
  The fortune art must be relettered to match.
- **D6** the Gauguin parody: "Gaugie".
- **D7** film parodies: "Sleepy Fist 2: Ouch"; "Love's Journey".
- **D10** 7-character speaker labels: the finance magistrate "Magist." (full
  title "Finance Magistrate" in dialogue); the hidden mysterious woman "Unknown".

Settled from the Japanese (local check, 2026-11-05):
- **D8** the gift sets: "Chichibinta Rika Transformation Set" (a hero
  transformation set, not a doll: Yumi is "into hero transformation sets");
  "Fighting Spirit History Set" (Inoki's catchphrase + "complete history", no
  other pun); the lip cosmetic stays "Lip gloss".
- **D9** the hero play: "Nazohl" / "Nazorah" kept; "Omoguro" and "Seminar" are
  right (a parody of the NHK quiz show "Quiz Omoshiro Seminar"); the shout after
  the cannon is the monster's cry, "Gyaaah!" stays.
**D12** the younger brother's one-character name 割: settled in round 3
(below) as "Wari".

### Escalation round 2 (2026-11-05)

Locked:
- **E1** "Amusement Park" (menu) / "the amusement park" (dialogue); not "theme park".
- **E2** "Ice Rink" (menu) / "the ice rink" (dialogue); "go skating" for the activity.
- **E3** the kefir fad gift: menu "Yogurt Mushroom Starter"; dialogue "yogurt
  mushrooms" for the fad, "starter" for what it does.
- **E5** exception to D1: a formal period-drama self-introduction keeps the family
  name first ("Finance Magistrate Ohashi Daizen!"). Only for in-play jidaigeki
  introductions, never ordinary dialogue.

Working:
- **E4** Yuko's ASAP slang: "pronto" by default; "right away" where her line is
  gentle or the Japanese is not marked slang.
- **E6** computer-club fortune booth: menu "Digital Fortune" (15 characters);
  "computer fortune-telling" in dialogue. Check the rendered width.

## Producer decisions 2026-11-05 (escalation round 3)

- **F1 Button glyphs:** the PS1 circle/cross button symbols (and the
  ideographic spacing that positions them) are allowed in English UI text:
  the one exception to the ASCII-only rule.
- **F2 Calendar day cell (MAINROM):** the shared day-unit / Sunday cell is to
  be split by engineering so Sunday reads "Su" and the day unit keeps its own
  lettering. Until then the cell stays "D".
- **D12 settled:** Mira's sibling 割 is "Wari".
- **F3 PC model label:** "NMS-9000" (hyphen) in every copy.
- **F4 Speakers:** BUNKA/SA_S6 0xb54 ("And I'm busy right now...") is Yumi;
  the camp line "Oh! If the club seniors catch me slacking here..." is Yumi's
  reply (GASSHUKU 0x1b4f4, TEST_SA 0x8a64; confirmed from the exchange order).
- **F5 G_APPEAR 0x148c (hallway line):** check the scene in an emulator
  capture before deciding narration vs the player's thought.
