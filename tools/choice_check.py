#!/usr/bin/env python3
"""choice_check.py - the fitting loop for DRAFT shortened event-choice
replies (config/patch/choice_overrides.json).

The retail choice box holds three rows at the 16-px pitch; a reply row is
257 px (text_msg.c plain layout).  A reply must fit ONE row, except in a
menu of one or two replies, where one reply may wrap onto a second row as
long as the menu stays within three rows (a menu of four replies gets one
row each).  inject.py applies the same rule and refuses the build
otherwise.

  choice_check.py --todo [--json OUT]   every choice row the sheets' English
                                        (plus choice_edits.json and the
                                        overrides so far) does not fit, with
                                        the Japanese and the current English
  choice_check.py [FILE]                check every override (default
                                        config/patch/choice_overrides.json):
                                        reply count = the Japanese's, tokens
                                        kept, every reply drawable, the rule
                                        above; exit 1 on any error

choice_overrides.json: {"note": ..., "rows": {"SERIFU/DATE_AS.BIN:0xe70":
"reply 1{opt}reply 2{opt}reply 3", ...}} (key = container under CDROM/ and
the row's offset, lowercase hex; the SPEAKTST mirrors of SERIFU rows need
their own keys).
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, SHEETS, CONTAINERS, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
import inject  # noqa: E402
import retail_text  # noqa: E402
import textcodec  # noqa: E402

DEFAULT = PATCH_CONFIG / "choice_overrides.json"


def choice_rows():
    """{key: (Japanese, English)} of every choice row of the injected containers"""
    out = {}
    conts = json.loads((CONTAINERS).read_text()) \
        if (CONTAINERS).exists() else None
    for p in sorted(SHEETS.glob("*/*.csv")):
        if p.parent.name not in inject.DEFAULT_DIRS:
            continue
        for r in retail_text.read_sheet(p):
                if r.get("Kind") != "choice" or "{br}" in r["Japanese"]:
                    continue        # multi-line alternatives are message bodies (inject.Row)
                out[inject.choice_key(r["ID"])] = (r["Japanese"], r.get("English", "") or "", r["ID"])
    return out


def fits(text):
    notes = []
    fitted, notes = inject.fit_text(inject.normalise(text.strip()), "choice", Counter())
    return fitted, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default=str(DEFAULT))
    ap.add_argument("--todo", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = choice_rows()
    over = json.loads(Path(a.file).read_text()).get("rows", {}) if Path(a.file).exists() else {}
    edits = json.loads(inject.CHOICE_EDITS.read_text()) if inject.CHOICE_EDITS.exists() else {}
    if a.todo:
        todo = []
        for k, (jp, en, rid) in rows.items():
            if not en.strip():
                continue
            cur = over.get(k) or edits.get("by_id", {}).get(rid)
            if not cur:
                fitted, _ = fits(en)
                cur = edits.get("by_text", {}).get(fitted) or edits.get("by_text", {}).get(en.strip()) or en
            _, notes = fits(cur)
            if notes:
                todo.append({"key": k, "japanese": jp, "english": cur, "problem": "; ".join(notes)})
        if a.json:
            Path(a.json).write_text(json.dumps(todo, ensure_ascii=False, indent=1) + "\n")
        for t in todo:
            print(f"{t['key']}\t{t['english']}\t[{t['problem']}]")
        print(f"[choice_check] {len(todo)} choice rows do not fit the retail box", file=sys.stderr)
        sys.exit(0)
    n_err = 0
    for k, en in over.items():
        if k not in rows:
            print(f"note  {k}: not a menu row (a line override; inject.py fits it to its region)")
            continue
        jp = rows[k][0]
        errs = []
        if en.count("{opt}") != jp.count("{opt}"):
            errs.append(f"{en.count('{opt}') + 1} replies, the Japanese has {jp.count('{opt}') + 1}")
        if inject.tokens_of(en) != inject.tokens_of(jp):
            errs.append(f"tokens {dict(inject.tokens_of(en))} != {dict(inject.tokens_of(jp))}")
        try:
            textcodec.encode(inject.normalise(en))
        except ValueError as e:
            errs.append(f"not drawable: {e}")
        _, notes = fits(en)
        errs += notes
        for e in errs:
            print(f"ERROR {k}: {e}  <{en}>")
        n_err += bool(errs)
    print(f"[choice_check] {a.file}: {len(over)} overrides, {n_err} with errors")
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
