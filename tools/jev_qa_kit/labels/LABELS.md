# Label values

`report/make_label_template.py` writes `labels/pilot_labels.csv`. Fill each
`label_<question>` cell with one of these values, leave it blank if you are
unsure, or keep `n/a` where the question does not apply. The full guide is
in `docs/PILOT-AND-CALIBRATION.md`.

| column | values | answer the question as worded |
|---|---|---|
| `label_meaning_preserved` | `yes` / `no` | yes = the English conveys the Japanese meaning |
| `label_register` | `matches_voice`, `too_formal`, `too_casual`, `wrong_character_voice` | against the speaker's voice note in `context/characters/` |
| `label_terminology` | `yes` / `no` | yes = the glossary renderings are used |
| `label_naturalness` | `0`, `1`, `2`, `3` | 0 broken, 1 stilted / translationese, 2 natural with minor awkwardness, 3 fully natural |
| `label_untranslated_or_garbled` | `yes` / `no` | yes = something is untranslated or garbled |
| `label_honorific_policy` | `follows_policy`, `honorific_kept`, `senpai_misused`, `address_handwritten`, `teacher_title_wrong` | STYLE-GUIDE §3 |
| `label_tone_shift` | `yes` / `no` | yes = the mood or intent changed |
| `label_choice_contrast` | `yes` / `no` | yes = the replies keep their contrast |
| `label_needs_human_review` | `yes` / `no` | yes = an editor should look at it |
