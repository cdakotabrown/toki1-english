# License note: read before using this kit

A **built** kit contains **Japanese script text from *Tokimeki Memorial:
Forever with You*** (Konami, 1995, SLPS-00065). The tracked template in the
repository does not: `tools/build_jev_qa_kit.py` adds the text on
a machine that has the disc, from the translation sheets extracted from that
legally owned disc. A built kit also holds the project's own English
translation of that text.

- The game text is copyrighted by its owner. It is included **only so that you
  can run a local quality-assurance pass** on the fan translation, on your own
  machine, with a model you run locally.
- **Never redistribute this kit or any file from it.** Do not upload it, in
  whole or in part, to any third-party or online service. That includes hosted
  model APIs, paste sites, issue trackers and public repositories. Keep the
  configured endpoint local.
- Results, reports and label sheets also quote the Japanese, so the same rules
  apply to them.
- Delete the kit when the QA pass is done. It can be rebuilt at any time from
  the repository by someone who owns the disc
  (`tools/build_jev_qa_kit.py`).

The code in `runner/` and `report/` and the documentation are the project's
own work. They contain no game data and may be reused freely.
