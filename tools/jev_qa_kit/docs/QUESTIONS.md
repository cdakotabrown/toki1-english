# The triage questions

`questions/questions.json` defines nine questions. Each one follows the
guidance for using Jev:

- **Bounded.** A fixed answer set (boolean, a short choice list, or a 0–3
  score) that the runner can turn into one number, P(problem).
- **Focused.** One property per question. A line that is wrong in two ways
  is flagged twice, which is easier to act on than a single "quality" score.
- **Minimal state.** Each question lists its `state_fields`, and the state
  carries nothing else. Jev gets worse when it is given irrelevant context,
  so the register question receives the speaker's voice note, not the whole
  bible.
- **No arithmetic.** Jev is weak at numeric precision and multistep
  reasoning. Line widths, byte budgets and token counts are therefore checked
  deterministically (the `lint` in the report) and never asked.
- **Calibrated thresholds.** Thresholds come from a hand-labelled pilot,
  not from guesses (`docs/PILOT-AND-CALIBRATION.md`).

## The set

| id | type | answer set | problem means | state fields |
|---|---|---|---|---|
| `meaning_preserved` | boolean | true / false | false | jp_readable, en_readable, kind, speaker, neighbours_short, token_legend |
| `register` | choice | matches_voice, too_formal, too_casual, wrong_character_voice | not matches_voice | speaker, voice_note, jp_readable, en_readable, previous_line |
| `terminology` | boolean | true / false | false | jp_readable, en_readable, glossary_entries |
| `naturalness` | score | 0 1 2 3 | ≤ 1 | en_readable, kind, speaker_role, scene_short |
| `untranslated_or_garbled` | boolean | true / false | true | en_raw, en_readable, token_legend, allowed_japanese_terms |
| `honorific_policy` | choice | follows_policy, honorific_kept, senpai_misused, address_handwritten, teacher_title_wrong | not follows_policy | policy_excerpt, speaker, jp_readable, en_raw, tokens |
| `tone_shift` | boolean | true / false | true | jp_readable, en_readable, speaker, neighbours_short, tone_principles |
| `choice_contrast` | boolean | true / false | false | jp_replies, en_replies, scene_short, previous_lines |
| `needs_human_review` | boolean | true / false | true | jp_readable, en_readable, speaker, scene_short, neighbours_short, known_flags |

## Rationale

- **meaning_preserved** is the core check. It allows rewording, because the
  style guide asks for function over form ("Sure. Let's." and not "That's
  right. Shall we do so?"), so a literal comparison would flag good lines.
  The neighbours are included because short reactive lines ("I see.") only
  make sense in context.
- **register** is answered against the character's own voice note (the
  `english_voice`, `japanese_voice` and role of one row of
  CHARACTER-BIBLE.md). It is only asked when the speaker is known; 13.8k
  lines in multi-speaker files have an unresolved speaker
  (`docs/DATA.md`). `wrong_character_voice` catches the defect the bible
  warns about: one heroine's signature words (Yuko's slang, Kagami's
  hauteur) leaking into another's lines.
- **terminology** is only asked when the Japanese contains a glossary term.
  The matching glossary rows are supplied in the state, so Jev compares
  against them and not against its own idea of the term.
- **naturalness** is a score and not a boolean, because "stilted but fine"
  and "broken" call for different responses. It sees only the English plus
  the speaker role and scene, so that it judges the English as English.
- **untranslated_or_garbled** gets the raw English (tokens visible) and the
  readable form, plus the Japanese-origin terms that are allowed on purpose
  (Senpai, giri-choco, bunkasai, omikuji, prf). The deterministic lint
  catches Japanese characters as well; this question adds romaji, leftover
  notes, placeholders and broken tokens.
- **honorific_policy** is only asked where an honorific or address form
  appears in either language. The policy text is STYLE-GUIDE §3, condensed to
  its honorific and address bullets.
- **tone_shift** is the style guide's "no added jokes, no softened insults"
  and "the game is sincere" (§2.5–2.6), together with emotional beat order
  (§6).
- **choice_contrast** is the core gameplay loop (§2.3): the player predicts
  the girl's reaction from the contrast between the replies. It is only asked
  for reply menus with two or more replies.
- **needs_human_review** is the catch-all. It also sees the known flags (for
  example audit findings, a reply override, or a suspected speaker). Expect
  it to correlate with the others; the calibration shows whether it adds
  anything.

## Editing a question

1. Change the wording, options, `state_fields` or `applies_when` in
   `questions/questions.json`.
2. **Bump its `version`.** Results are keyed by version, so the changed
   question is asked again and the old answers are kept but ignored.
3. Check it with `python3 runner/run.py --dry-run --sample 20 --question <id>`.
4. If the answer set changed, re-label that column of the pilot and rerun
   `report/calibrate.py`.

## Adding a question

Add an object with `id`, `version`, `type` (`boolean` | `choice` | `score`),
`question`, `options` (choice) or `scale` (score), `state_fields`,
`applies_when` and `problem`:

- `{"when": "true"}` or `{"when": "false"}` for a boolean;
- `{"when": "not", "answer": "<ok option>"}` for a choice;
- `{"when": "score_at_most", "value": N}` for a score.

Add its weight and default threshold to `report/thresholds.json`, and run
`report/make_label_template.py --force` if you want it in the pilot.

State fields that are available (`runner/common.py` → `field_value`):
`jp_readable`, `en_readable`, `en_raw`, `kind`, `speaker`, `speaker_role`,
`voice_note`, `previous_line`, `previous_lines`, `neighbours_short`,
`neighbours_full`, `token_legend`, `glossary_entries`, `scene_short`,
`allowed_japanese_terms`, `policy_excerpt`, `tone_principles`, `tokens`,
`jp_replies`, `en_replies`, `known_flags` and `constraints`.

Predicates (`runner/common.py` → `PREDICATES`): `always`, `has_english`,
`speaker_has_voice_note`, `is_dialogue`, `has_glossary_hits`,
`has_honorific_signal` and `is_reply_menu`. You can add your own as a
one-line lambda.
