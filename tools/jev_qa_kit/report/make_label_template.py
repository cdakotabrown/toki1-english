#!/usr/bin/env python3
"""make_label_template.py - pick a stratified pilot set and write the
hand-labelling sheet.

    python3 report/make_label_template.py --n 200            # -> labels/pilot_labels.csv + labels/pilot_ids.txt

The sheet has one row per line and one label column per question
(label_<question id>); fill them in a spreadsheet (UTF-8 CSV):

  boolean questions   yes / no            (blank = not labelled)
  choice questions    one of the options   (listed in labels/LABELS.md)
  score questions     0, 1, 2 or 3

Columns for questions that do not apply to a line are pre-filled with
"n/a".  Then run Jev on exactly these lines:

    python3 runner/run.py --ids-file labels/pilot_ids.txt
    python3 report/calibrate.py
"""
import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT / "runner"))
import common  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261103)
    ap.add_argument("--out", default=str(KIT / "labels" / "pilot_labels.csv"))
    ap.add_argument("--ids-out", default=str(KIT / "labels" / "pilot_ids.txt"))
    ap.add_argument("--lines", default=None)
    ap.add_argument("--only-dialogue", action="store_true", help="skip UI / art / composed lines")
    ap.add_argument("--force", action="store_true", help="overwrite an existing labels file")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists() and not a.force:
        raise SystemExit(f"{out} exists (it may hold your labels); pass --force to overwrite")
    lines = common.load_lines(a.lines)
    if a.only_dialogue:
        lines = [l for l in lines if l["kind"] in common.DIALOGUE_KINDS]
    sample = common.stratified_sample(lines, a.n, a.seed)
    questions = common.load_questions()
    ctx = common.Context()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["line_id", "container", "girl", "speaker", "kind", "status", "previous_line",
                    "japanese", "english"] + [f"label_{q['id']}" for q in questions] + ["labeller_notes"])
        for l in sample:
            prev = (l.get("neighbours") or {}).get("prev") or []
            pv = f"{prev[-1].get('speaker')}: {prev[-1].get('en') or prev[-1].get('jp')}" if prev else ""
            w.writerow([l["id"], l["container"], l["scene"].get("girl") or "",
                        l["speaker"].get("name") or f"? ({l['speaker'].get('candidates', '')})",
                        l["kind"], l["status"], pv, l.get("jp_readable") or l["jp"],
                        l.get("en_readable") or l["en"]] +
                       [("" if common.applies(q, l, ctx) else "n/a") for q in questions] + [""])
    Path(a.ids_out).write_text("\n".join(l["id"] for l in sample) + "\n", encoding="utf-8")
    print(f"[labels] {len(sample)} lines -> {out} and {a.ids_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
