#!/usr/bin/env python3
"""QA gate for the localization sheets (translation/localization/sheets/**).

Checks every row whose Status is not `untranslated`:
  tokens     every {token} of the Japanese survives in the English (order free)
  budget     encoded English length vs the in-place MaxBytes budget.  Two
             encodings are reported: `ascii` (1 byte/char, the half-width
             ASCII render path) and `fullwidth` (2 bytes/char, what retail can
             show today).  Over-budget rows are not errors yet -- they are the
             measured relocation demand -- but rows over `--hard` bytes are.
  charset    characters the ASCII path cannot render (anything outside
             printable ASCII and {tokens})
  syntax     reject unknown tokens and unmatched braces
  status     reject unknown statuses rather than silently skipping their rows
  consistency identical Japanese -> identical English across the sheet set
             (translation-memory rule; differences are listed, not failed,
             because context can legitimately differ)
  empty      Status says translated/edited/final but English is blank

row_findings() is the per-row rule set; tools/translation/lint_sheets.py
runs it without the disc, where the sheet's `Tokens` column (the set of
tokens the Japanese carries) stands in for the Japanese in the token rule.

Usage:
    python3 tools/translation/check_translation.py                 # all sheets
    python3 tools/translation/check_translation.py SERIFU/DATE_AS  # one sheet
    python3 tools/translation/check_translation.py --json out.json
Exit status 1 if any hard failure (tokens, syntax, status, empty, charset, hard budget).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT as REPO, SHEETS  # noqa: E402  (this checkout, either layout)

import retail_text  # noqa: E402
TOKEN_RE = re.compile(r"\{(br|opt|P|G|p|m|F|Y|S|O|W|A|M)\}")
DONE = {"draft", "translated", "edited", "qa", "final"}


def enc_len(text: str, width: int) -> int:
    n = 0
    pos = 0
    for m in TOKEN_RE.finditer(text):
        n += len(text[pos:m.start()]) * width + 1
        pos = m.end()
    n += len(text[pos:]) * width
    return n


def row_findings(r: dict, ja: str | None = None) -> dict:
    """The rules for one sheet row: {"status", "fails": [(kind, msg)],
    "warns": [(kind, msg)], "ascii", "fullwidth", "budget"} (the lengths
    only for a translated row).  `ja` is the row's Japanese, read from the
    disc; None checks the tokens against the `Tokens` column instead (as a
    set: the disc-free form, tools/translation/lint_sheets.py)."""
    out = {"status": r.get("Status", "").strip().lower(), "fails": [], "warns": []}
    st = out["status"]
    en = r.get("English", "")
    if st not in DONE and st != "untranslated":
        out["fails"].append(("status", f"unknown status {st!r}"))
        return out
    if st == "untranslated":
        return out
    if not en.strip():
        out["fails"].append(("empty", "status set but English blank"))
        return out
    have = sorted(TOKEN_RE.findall(en))
    if ja is not None:
        need = sorted(TOKEN_RE.findall(ja))
        if [t for t in need if t not in ("br",)] != [t for t in have if t not in ("br",)]:
            out["fails"].append(("tokens", f"JA {need} vs EN {have}"))
    else:
        need = sorted(set((r.get("Tokens") or "").split()) - {"br"})
        if need != sorted(set(have) - {"br"}):
            out["fails"].append(("tokens", f"Tokens {need} vs EN {have}"))
    plain = TOKEN_RE.sub("", en)
    if "{" in plain or "}" in plain:
        out["fails"].append(("syntax", "unknown token or unmatched brace"))
    bad = sorted({c for c in plain if not 0x20 <= ord(c) < 0x7F})
    if bad:
        out["fails"].append(("charset", "".join(bad)))
    budget = int(r["MaxBytes"])
    a = enc_len(en, 1)
    w = enc_len(en, 2)
    out.update(ascii=a, fullwidth=w, budget=budget)
    if a > budget:
        out["warns"].append(("budget-ascii", f"{a} > {budget}"))
    if a > HARD:
        out["fails"].append(("budget-hard", f"{a} > {HARD}"))
    return out


HARD = 255          # bytes: the encoded-length ceiling of one row (--hard)


def main(argv):
    hard = 255
    if "--hard" in argv:
        hard = int(argv[argv.index("--hard") + 1])
    out_json = None
    if "--json" in argv:
        out_json = Path(argv[argv.index("--json") + 1])
    sel = [a for a in argv[1:] if not a.startswith("-") and not a.endswith(".json")
           and not a.isdigit()]
    files = sorted(SHEETS.glob("*/*.csv"))
    if sel:
        # accept "DIR/FILE" selectors and sheet paths (".../sheets/DIR/FILE.csv")
        sel = [s.split("sheets/")[-1][:-4] if s.endswith(".csv") else s for s in sel]
        for s in sel:
            if not any(f"{f.parent.name}/{f.stem}".startswith(s) for f in files):
                print(f"check_translation: no sheet matches {s!r}")
                return 2
        files = [f for f in files if any(f"{f.parent.name}/{f.stem}".startswith(s) for s in sel)]
    fails = []
    warns = []
    tm = defaultdict(set)
    stats = defaultdict(int)
    global HARD
    HARD = hard
    for f in files:
        for r in retail_text.read_sheet(f):
                rid = r["ID"]
                ja = r["Japanese"]
                res = row_findings(r, ja)
                fails += [(rid, k, m) for k, m in res["fails"]]
                if res["status"] == "untranslated":
                    stats["untranslated"] += 1
                if res["status"] not in DONE:
                    continue
                stats["translated"] += 1
                if "ascii" not in res:
                    continue
                a, w, budget = res["ascii"], res["fullwidth"], res["budget"]
                if a > budget:
                    stats["over_ascii"] += 1
                    stats["over_ascii_bytes"] += a - budget
                    warns.append((rid, "budget-ascii", f"{a} > {budget}"))
                if w > budget:
                    stats["over_fullwidth"] += 1
                tm[ja].add(r.get("English", ""))
    incons = {ja: sorted(v) for ja, v in tm.items() if len(v) > 1}
    for rid, kind, msg in fails:
        print(f"FAIL {kind:12s} {rid}: {msg}")
    print(f"\nrows translated {stats['translated']}, untranslated {stats['untranslated']}")
    print(f"over in-place budget: ascii {stats['over_ascii']} rows "
          f"(+{stats['over_ascii_bytes']} bytes needed), fullwidth {stats['over_fullwidth']} rows")
    print(f"translation-memory inconsistencies: {len(incons)}")
    for ja, v in list(incons.items())[:10]:
        print(f"  {ja[:40]!r}: {v}")
    print(f"hard failures: {len(fails)}")
    if out_json:
        out_json.write_text(json.dumps({"stats": stats, "fails": fails,
                                        "warns": warns, "inconsistent": incons},
                                       ensure_ascii=False, indent=1))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
