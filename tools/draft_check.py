#!/usr/bin/env python3
"""draft_check.py - the fitting loop for DRAFT English of the sheet-missing
sources (overlay `.data` strings, exe strings, data-file tables).

The rows live in the draft sheets text_sources.py writes under
build/patch/gen/sheets/<rel>.csv; the English goes into a fragment
config/patch/overlay_drafts.d/<name>.json ({"by_addr": {"<rel>:<0xoff>":
"English"}}, one entry per copy; a committed "by_text" keyed by the
Japanese is refused, D4(a)), which
tools/patch/overlay_sheets.py merges with config/patch/overlay_drafts.json.

  draft_check.py --todo EXEDIR/TEL.EXN            rows still without English
                 [--json OUT]                     (offset, slot bytes, Japanese
                                                   width, neighbours)
  draft_check.py config/patch/overlay_drafts.d/tel.json
                                                  check every entry

Checks per entry (the same rules overlay_sheets.py applies at build time):
  * every character is drawable (ASCII; the patch font) and every token the
    Japanese carries ({P} {G} {p} {m} ...) is kept;
  * FIT: the DTE-encoded English fits the string's slot (its bytes plus the
    zero padding after it) -- or the string has exactly one pointer word
    and can be relocated;
  * WIDTH: each row ({br}-separated) is at most 257 px (the widest text
    area of any window) -- an error; a row wider than both 201 px (the
    message-window body) and the Japanese row is a warning (the draw site
    may clip it: shorten it unless the screen is known to be wider).
Exit 1 when any entry has an error.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
import overlay_sheets as osh  # noqa: E402
import compose_check  # noqa: E402
import textcodec  # noqa: E402
import ui_strings  # noqa: E402
from inject import line_width  # noqa: E402

SHEETS = ROOT / "build" / "patch" / "gen" / "sheets"
DTE = ROOT / "build" / "patch" / "gen" / "dte.json"
TOK_RE = re.compile(r"\{[A-Za-z]+\}")
HARD_PX = 257
BODY_PX = 201


def rows_of(rel):
    p = SHEETS / f"{rel}.csv"
    if not p.exists():
        raise SystemExit(f"no draft sheet {p} (python3 tools/patch/text_sources.py --draft-sheets)")
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def all_rels():
    return sorted(str(p.relative_to(SHEETS))[:-4] for p in SHEETS.rglob("*.csv"))


_DATA = {}


def target(rel):
    if rel not in _DATA:
        if rel == "PSX.EXE":
            d, base = ui_strings.load_target("main")
            _DATA[rel] = (d, base, 0x80041000 - 0x800, osh.MAIN_DATA)
        elif rel.startswith("EXEDIR/") and rel.endswith(".EXN"):
            d, base = ui_strings.load_target(Path(rel).stem)
            _DATA[rel] = (d, base, 0x80132000, (None, None))
        else:
            d = (DECOMP / "assets" / "extracted_iso" / "CDROM" / rel).read_bytes()
            _DATA[rel] = (d, None, None, (None, None))
    return _DATA[rel]


def container_rels():
    p = PATCH_CONFIG / "containers_extra.json"
    if not p.exists():
        return set()
    return {k.split("extracted_iso/CDROM/")[1] for k in json.loads(p.read_text())}


def jp_width(jp):
    return max((textcodec.width(x) for x in jp.split("{br}")), default=0)


def tokens(text):
    return sorted(t for t in TOK_RE.findall(text) if t not in ("{br}", "{dst}"))


_COMPOSED = []


def _slot_key(rel, off):
    if rel == "PSX.EXE":
        return ("main", 0x80041000 - 0x800 + off)
    if rel.startswith("EXEDIR/") and rel.endswith(".EXN"):
        return (Path(rel).stem, 0x80132000 + off)
    return None


def composed(rel, off):
    """the slot is a composition piece (a module string may stand in)"""
    if not _COMPOSED:
        _COMPOSED.append(compose_check.composed_slots())
        _COMPOSED.append(set(compose_check.draw_slots()))
    return _slot_key(rel, off) in _COMPOSED[0]


def module_ok(rel, off):
    """a module string may stand in: a composition piece or a reasoned
    draw-only slot (compositions.json "draw_slots")"""
    composed(rel, off)
    k = _slot_key(rel, off)
    return k in _COMPOSED[0] or k in _COMPOSED[1]


def check_one(rel, row, en, dte):
    errs, warns = [], []
    off = int(row["Offset"], 16)
    jp = row["Japanese"]
    is_composed = composed(rel, off)
    if "{dst}" in en and not is_composed:
        return [f"{{dst}} outside a composition piece (config/patch/compositions.json)"], [], 0, 0
    try:
        enc = textcodec.encode(en.replace("{dst}", ""), dte)
    except ValueError as e:
        return [f"not drawable: {e}"], [], 0, 0
    if tokens(en) != tokens(jp):
        errs.append(f"tokens {tokens(en)} != Japanese {tokens(jp)}")
    data, base, base_addr, (lo, hi) = target(rel)
    ln, mx = ui_strings.slot_of(data, off)
    if rel in container_rels():
        mx = 1 << 30           # a container: inject.py repacks it (capacity per file)
    elif module_ok(rel, off) and mx >= 2 and (len(enc) > mx or "{dst}" in en):
        mx = 1 << 30           # a composition piece / draw slot: a module string stands in
    if len(enc) > mx:
        if base is not None:
            sites = osh.pointer_sites(data, base, base_addr + off, lo, hi) if lo else \
                osh.pointer_sites(data, base, base_addr + off)
            if len(sites) != 1:
                errs.append(f"FIT {len(enc)} B > slot {mx} B and {len(sites)} pointer words "
                            f"(shorten by {len(enc) - mx} B)")
        else:
            errs.append(f"FIT {len(enc)} B > slot {mx} B (shorten by {len(enc) - mx} B)")
    jw = jp_width(jp)
    for r in en.replace("{dst}", "").split("{br}"):
        w = line_width(r)
        if w > HARD_PX:
            errs.append(f"WIDTH {w} px > {HARD_PX}: {r!r}")
        elif w > max(BODY_PX, jw):
            warns.append(f"width {w} px > {max(BODY_PX, jw)} (Japanese {jw} px): {r!r}")
    return errs, warns, len(enc), mx


def load_fragment(path):
    f = json.loads(Path(path).read_text())
    return f.get("by_text", {}), f.get("by_addr", {})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fragment", nargs="?")
    ap.add_argument("--todo", help="REL (e.g. EXEDIR/TEL.EXN): rows still without English")
    ap.add_argument("--json", help="write the --todo rows here")
    ap.add_argument("--quiet", action="store_true", help="errors only")
    a = ap.parse_args()
    dte = json.loads(DTE.read_text())["entries"] if DTE.exists() else []
    by_text, by_addr = osh.load_drafts()
    if a.todo:
        rows = rows_of(a.todo)
        out = []
        # rows the last overlay_sheets.py run classified as covered by
        # ui_strings.py or kept on purpose are not to-do
        rep = ROOT / "build" / "patch" / "gen" / "overlay_sheets.report.json"
        settled = {}
        if rep.exists():
            for u in json.loads(rep.read_text()).get("rows_without_english", []):
                if u["class"] != "untranslated_visible":
                    settled[(u["source"], int(u["offset"], 16))] = u["class"]
        n_settled = 0
        for i, r in enumerate(rows):
            en, how = osh.english_for(a.todo, r, by_text, by_addr, {})
            if en:
                continue
            if (a.todo, int(r["Offset"], 16)) in settled:
                n_settled += 1
                continue
            data, base, base_addr, _ = target(a.todo)
            off = int(r["Offset"], 16)
            ln, mx = ui_strings.slot_of(data, off)
            out.append({"key": f"{a.todo}:0x{off:x}", "slot_bytes": mx,
                        "jp_px": jp_width(r["Japanese"]), "japanese": r["Japanese"],
                        "prev": rows[i - 1]["Japanese"] if i else "",
                        "next": rows[i + 1]["Japanese"] if i + 1 < len(rows) else ""})
        if a.json:
            Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
        for o in out:
            print(f"{o['key']}\t{o['slot_bytes']}B\t{o['jp_px']}px\t{o['japanese']}")
        print(f"[draft_check] {a.todo}: {len(out)} rows without English "
              f"({n_settled} more covered by ui_strings.py or kept on purpose: "
              f"build/patch/gen/overlay_sheets.report.json)", file=sys.stderr)
        return
    if not a.fragment:
        ap.error("a fragment or --todo")
    ftext, faddr = load_fragment(a.fragment)
    index = {}
    for rel in all_rels():
        for r in rows_of(rel):
            index[f"{rel}:0x{int(r['Offset'], 16):x}"] = (rel, r)
    n_err = n_warn = n = 0
    items = [(k, v, [index[k]] if k in index else None) for k, v in faddr.items()]
    for jp, v in ftext.items():
        # a by_text entry covers every copy of the string that no address-
        # keyed draft overrides (overlay_sheets.english_for precedence)
        hits = [x for x in index.values() if x[1]["Japanese"] == jp and
                f"{x[0]}:0x{int(x[1]['Offset'], 16):x}" not in by_addr]
        if not hits and any(x[1]["Japanese"] == jp for x in index.values()):
            continue                    # every copy has its own by_addr draft
        if not hits:
            if not a.quiet:
                print(f"note  {jp}: by_text draft matches no row of the draft sheets (unused)")
            continue
        items.append((jp, v, hits))
    for key, en, hits in items:
        n += 1
        if hits is None and key in faddr:
            rel, _, off = key.rpartition(":")
            if (SHEETS / f"{rel}.csv").exists():
                syn = osh.synthetic_row(rel, int(off, 16), target(rel)[0])
                if syn is not None:
                    hits = [(rel, syn)]
        if hits is None:
            print(f"ERROR {key}: no such row in the draft sheets")
            n_err += 1
            continue
        for rel, r in hits:
            errs, warns, nb, mx = check_one(rel, r, en, dte)
            k = f"{rel}:{r['Offset']}"
            for e in errs:
                print(f"ERROR {k} ({r['Japanese']}): {e}")
            if not a.quiet:
                for w in warns:
                    print(f"warn  {k} ({r['Japanese']}): {w}")
            n_err += bool(errs)
            n_warn += bool(warns)
    print(f"[draft_check] {a.fragment}: {n} entries, {n_err} with errors, {n_warn} with warnings")
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
