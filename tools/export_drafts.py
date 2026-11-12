#!/usr/bin/env python3
"""export_drafts.py - every DRAFT English string the patch carries outside
the editor's sheets, exported as sheets in the translation agent's CSV
layout for the editor (build/patch/handoff/).

The patch drafts English in several places because the cloud agent's
sheets (translation/localization/sheets/) only cover the containers:

  * the profile's own strings (config/patch/english.json: the prologue,
    the opening lyrics, the memory-card dialogs, ... by address) and
    tools/patch/ui_strings.py (build/patch/gen/ui_strings.json);
  * the overlay / exe / data-file drafts (config/patch/overlay_drafts.json
    and config/patch/overlay_drafts.d/*.json) applied to the draft sheets
    text_sources.py writes (build/patch/gen/sheets/);
  * the tagged container rows (config/patch/tagged_rows_en.json);
  * the shortened event replies (config/patch/choice_edits.json,
    config/patch/choice_overrides.json).

Output (one CSV per source file, columns ID File Offset MaxBytes PtrSite
Kind Speaker Japanese Tokens English Status Notes, Status "draft", the
Notes saying where the draft lives so an edited sheet can be fed back):

  build/patch/handoff/<DIR>/<FILE>.csv      (EXEDIR/TEL.EXN.csv, PSX.EXE.csv, ...)
  build/patch/handoff/tagged_rows.csv      (keyed <DIR>/<FILE>:0x<offset>, with the
                                            Japanese read from the disc, the pointer
                                            site and the reasoned "keep" rows)
  build/patch/handoff/choice_overrides.csv

An edited copy of build/patch/handoff/<DIR>/<FILE>.csv placed under
translation/localization/sheets/<DIR>/<FILE>.csv takes precedence over the
drafts at build time (overlay_sheets.py, editor > by_addr).

  python3 tools/patch/export_drafts.py [--out build/patch/handoff]
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, CONTAINERS, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import overlay_sheets as osh  # noqa: E402
import tagged_rows  # noqa: E402

COLS = osh.SHEET_COLS
EXTRACTED = DECOMP / "assets" / "extracted_iso"
MAIN_BASE = 0x80041000 - 0x800
OV_BASE = 0x80132000


def retail_string(data: bytes, off: int) -> str:
    e = data.find(b"\0", off)
    raw = data[off:e if e >= 0 else len(data)]
    try:
        return tagged_rows.retail_to_sheet(raw)
    except (UnicodeDecodeError, ValueError):
        try:
            return raw.decode("shift_jis")
        except UnicodeDecodeError:
            return raw.hex()


def profile_entries():
    """(rel, data) -> [entry] for the profile's and ui_strings.py's strings"""
    prof = json.loads((PATCH_CONFIG / "english.json").read_text())
    groups = defaultdict(list)
    for e in prof.get("main", {}).get("strings", []):
        groups["main"].append((e, "config/patch/english.json"))
    for ov, spec in prof.get("overlays", {}).items():
        for e in spec.get("strings", []):
            groups[ov].append((e, "config/patch/english.json"))
    g = ROOT / "build/patch/gen/ui_strings.json"
    if g.exists():
        u = json.loads(g.read_text())
        for e in u.get("main", []):
            groups["main"].append((e, "tools/patch/ui_strings.py"))
        for ov, lst in u.get("overlays", {}).items():
            for e in lst:
                groups[ov].append((e, "tools/patch/ui_strings.py"))
    return groups


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build/patch/handoff")
    a = ap.parse_args()
    out = locate(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sheets = defaultdict(dict)          # rel -> {offset: row}
    counts = Counter()

    # 1. profile + ui_strings, by address
    for target, lst in profile_entries().items():
        if target == "main":
            rel, path, base = "PSX.EXE", EXTRACTED / "PSX.EXE", MAIN_BASE
        else:
            rel, path, base = f"EXEDIR/{target}.EXN", EXTRACTED / "CDROM/EXEDIR" / f"{target}.EXN", OV_BASE
        data = path.read_bytes()
        for e, src in lst:
            if "addr" in e:
                off = int(e["addr"], 16) - base
            elif "ptr_at" in e:
                site = int(e["ptr_at"], 16) - base
                off = int.from_bytes(data[site:site + 4], "little") - base
            else:
                continue
            if not (0 <= off < len(data)):
                continue
            jp = retail_string(data, off)
            sheets[rel][off] = {
                "ID": f"{rel}:0x{off:x}", "File": rel, "Offset": f"0x{off:x}",
                "MaxBytes": str(e.get("max_bytes", "")), "PtrSite": e.get("ptr_at", ""),
                "Kind": "line", "Speaker": "", "Japanese": jp, "Tokens": "",
                "English": e.get("text", ""), "Status": "draft",
                "Notes": f"DRAFT in {src}" + (f"; {e['note']}" if e.get("note") else "")}
            counts[src] += 1

    # 2. the draft sheets with the overlay drafts applied
    by_text, by_addr = osh.load_drafts()
    frag_of = {}
    for frag in sorted(osh.DRAFTS_D.glob("*.json")):
        for k in json.loads(frag.read_text()).get("by_addr", {}):
            frag_of[k] = f"config/patch/overlay_drafts.d/{frag.name}"
    for sheet in sorted(osh.SHEETS.rglob("*.csv")):
        rel = str(sheet.relative_to(osh.SHEETS))[:-4]
        rows = osh.read_sheet(sheet)
        listed = {int(r["Offset"], 16) for r in rows}
        data = None
        for k in by_addr:
            krel, _, koff = k.rpartition(":")
            if krel == rel and int(koff, 16) not in listed:
                if data is None:
                    p = EXTRACTED / (rel if rel == "PSX.EXE" else "CDROM/" + rel)
                    data = p.read_bytes()
                    if rel == "PSX.EXE":
                        pass
                syn = osh.synthetic_row(rel, int(koff, 16), data)
                if syn:
                    rows.append(syn)
        for r in rows:
            off = int(r["Offset"], 16)
            en, how = osh.english_for(rel, r, by_text, by_addr, {})
            if not en and how not in ("by_addr", "by_text"):
                continue
            if off in sheets[rel]:
                continue                     # the profile / ui_strings entry wins at build time
            k = f"{rel}:0x{off:x}"
            src = frag_of.get(k, "config/patch/overlay_drafts.json") if how == "by_addr" else \
                ("config/patch/overlay_drafts.json (by_text)" if how == "by_text" else how)
            r = dict(r)
            r.update({"ID": k, "File": rel, "English": en, "Status": "draft",
                      "Notes": f"DRAFT in {src}"})
            sheets[rel][off] = r
            counts[src.split(" ")[0]] += 1

    n_files = 0
    for rel, rows in sorted(sheets.items()):
        if not rows:
            continue
        dst = out / f"{rel}.csv"
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=COLS)
            wr.writeheader()
            for off in sorted(rows):
                wr.writerow({c: rows[off].get(c, "") for c in COLS})
        n_files += 1

    # 3. tagged container rows
    t = json.loads((PATCH_CONFIG / "tagged_rows_en.json").read_text())
    # each keyed row as the injector finds it: Japanese (from the disc, this
    # is a local hand-off file) and pointer site
    found = {}
    idx = {}
    for p in (CONTAINERS,
              PATCH_CONFIG / "containers_extra.json"):
        if p.exists():
            idx.update(json.loads(p.read_text()))
    for rel, info in sorted(idx.items()):
        if rel.split("CDROM/", 1)[-1].split("/")[0] in ("BATTLE", "BUNKASD"):
            continue
        sheet = locate(info["sheet"])
        if not locate(rel).exists() or not sheet.exists():
            continue
        offs = {int(r["Offset"], 16) for r in osh.read_sheet(sheet)}
        for r in tagged_rows.scan_container(rel, info, offs):
            found[tagged_rows.en_key(rel, int(r["Offset"], 16))] = r
    with open(out / "tagged_rows.csv", "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["Key (DIR/FILE:0xoffset)", "Tag", "Speaker", "Japanese (from the disc)",
                     "Speaker English", "English", "Status", "Pointer site", "Notes"])
        for k, en in t.get("rows", {}).items():
            r = found.get(k)
            spk = r["Speaker"] if r else ""
            wr.writerow([k, r["Tag"] if r else "", spk, r["Japanese"] if r else "",
                         t.get("speakers", {}).get(spk, ""), en, "draft",
                         r["PtrSite"] if r else "(no tagged row there any more)",
                         "DRAFT in config/patch/tagged_rows_en.json"])
            counts["config/patch/tagged_rows_en.json"] += 1
        for k, why in t.get("keep", {}).items():
            wr.writerow([k, "", "", "", "", "", "keep", "", f"kept Japanese on purpose: {why}"])

    # 4. shortened replies
    with open(out / "choice_overrides.csv", "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["Key", "English (shortened)", "Status", "Notes"])
        for f, key in (("choice_overrides.json", "rows"), ("choice_edits.json", "by_id"),
                       ("choice_edits.json", "by_text")):
            p = PATCH_CONFIG / f
            if not p.exists():
                continue
            for k, en in json.loads(p.read_text()).get(key, {}).items():
                wr.writerow([k, en, "draft", f"DRAFT in config/patch/{f} ({key}); the sheet text is untouched"])
                counts[f"config/patch/{f}"] += 1

    for k, v in counts.most_common():
        print(f"[export_drafts] {v:5d}  {k}")
    print(f"[export_drafts] {sum(counts.values())} draft strings, {n_files} source sheets "
          f"+ tagged_rows.csv + choice_overrides.csv -> {out.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
