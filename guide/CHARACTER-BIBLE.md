# Character bible — voices for the English script (v0.1)

File codes: `DATE_XX`, `EVENT_XX`, `TEST_XX` (SPEAKTST), `XX_S6*` (BUNKA) are
one heroine's own lines. Choice strings inside them are the player.

| Code | Name (EN order) | Role | Japanese voice | English voice (defaults) |
|---|---|---|---|---|
| FU | Shiori Fujisaki | childhood friend, the "main" heroine; honour student, piano, class rep type | polite-standard, warm but corrective, never slang | Articulate, composed, gently bossy. Full sentences. Teases with understatement. |
| NI | Saki Nijino | athletics-club manager, cooks, tomboyish, everyone's big sister | energetic, plain-form, sporty cheer; direct and practical | Upbeat, brisk, team-captain warmth. Short exclamations, food metaphors. Says what she means; no coyness. |
| KI | Mio Kisaragi | literature club, library; timid, bookish | soft, hesitant, polite ("...desu", "ano...") | Quiet and careful, trailing sentences, apologises first. Vocabulary a notch literary. |
| HI | Yuina Himoo | science club "mad scientist"; ambitious, unpredictable, secretly vulnerable | dry, matter-of-fact, often dismissive; states plans as facts ("I am going to the museum on Sunday" and expects you to follow); calls the player 「君」; grandiose about her own genius | **Deadpan.** Clinical, precise, unimpressed; her world-domination grandeur is delivered flatly, as fact, never with exclamation marks or theatrical flourish. Sarcasm is dry, not loud. Rare cracks of warmth land hard because the baseline is cool. (Editor flag: DATE_HI was drafted before this entry and leans theatrical.) |
| KA | Ayako Katagiri | art club, fashionable, casual and reasonable | breezy; intersperses actual English phrases every other sentence (katakana "thank you", "good timing", "oh really", "it's so bad") | Cosmopolitan and light. Her mannerism is *English loanwords*, which vanish in an English script; two candidate renderings, **OPEN** for the producer: (A) keep them as slightly stilted, set-apart textbook phrases ("Oh, really!", "Good timing!") so the tic survives as a quirk of phrasing; (B) French/Italian flourishes ("magnifique", "ciao", "tres chic") -- what DATE_KA was drafted with. |
| KY | Nozomi Kiyokawa | swim club ace/captain; boyish, direct | blunt, plain-form, somewhat masculine grammar and word choice; husky | Frank, competitive, no filler. Uses "you" a lot; hates fuss. Secretly wants her femininity respected: a sincere compliment on that lands, teasing about it stings. |
| KG | Mira Kagami | beauty queen, haughty rich girl, looks older than her classmates | 「〜ですわ」 ojou-sama speech, condescending; vain ("Kagami" = mirror) | Imperious, precise, a touch theatrical. Never contractions when she is looking down on someone. Emotionally vulnerable beneath the vanity: when the mask slips she is allowed contractions and stammers, and those moments are the point. |
| AS | Yuko Asahina | trend-chasing "kogal"; arcades, fashion, gossip | heavy 1990s slang: 超 (super), ちょださー (lame), むっかー (ugh/grr), ソッコー (right now), ちょろっと (a smidge), アンビリ (unbelievable), バッチグー (perfect), まじで (for real) | Fast, slangy, judgemental, fun. Signature set (use consistently): "so/totally" for 超, "lame" for ださい, "Ugh!"/"Grr!" for むっかー, "right now" for ソッコー, "a smidge"/"kinda" for ちょろっと, "No way" for アンビリ, "Perfect!" for バッチグー, "for real?" for まじで. |
| KO | Yukari Koshiki | archery (kyudo) club; traditional, graceful, absent-minded | classical-polite, soft (「〜ですのよ」), old-fashioned words | Gracious, slightly formal, faintly out of time. Gentle non-sequiturs. |
| MI | Megumi Mikihara | animal lover; shy, kind, easily flustered | very soft, apologetic, 「…」 | Small voice, kind, stammers when surprised. Never sarcastic. Shiori calls her "Megu" (メグ; decided 2026-11-03, not "Meg"). |
| SA | Yumi Saotome | Yoshio's younger sister, first-year; cheeky, clingy, loud | "senpai" constantly, bratty-cute, yells ("yattaa!"), emotionally transparent | Calls the player "Senpai". Bossy-cute, exclamation marks, mock outrage; every feeling is on the surface. |
| OT | others | Rei Ijuin (rich "prince", masculine speech 「僕」), Miharu Tatebayashi (hidden heroine, cryptic), teachers, shopkeepers | varies | Rei: cool, curt, self-assured, masculine cadence. Miharu: cryptic and suggestive, few words, wistful. |
| — | Yoshio Saotome (`{Y}`) | best friend, gossip source | 「〜だぜ」, loud, big-brotherly | Loud, loyal, wingman energy. "Dude"-adjacent without saying dude every line. |
| — | the player (`{p}` `{m}` `{F}`) | first-year boy at Kirameki High | plain-form 「俺」 | Ordinary, a little awkward, capable of both sincerity and cheek (the choice triplets). |

Name spellings follow STYLE-GUIDE §3: Hepburn with long vowels dropped
(Yuko, Ijuin), separate kana kept (Himoo).

## Forms of address (see STYLE-GUIDE §3)
The surname-to-nickname switch is the game's intimacy signal and lives in code
(name tokens + an address table). Voice entries above describe *register*; the
form of address is never hand-written into a line.

## Shared conventions
- Girls address the player by given name via `{G}`-style tokens only where the
  engine inserts it; do not add his name elsewhere.
- Heroine reactions are graded: **good** (pleased), **neutral**, **bad**
  (annoyed). Keep the English grade obvious at a glance — the player reads
  the face and one line.
- Yuko's slang is the loudest voice in the pilot; other heroines must **not**
  inherit it. When a neutral phrase ("sou da ne", that's right) appears in another
  heroine's file it is translated in *her* voice, so the TM only propagates
  within a file/speaker.
