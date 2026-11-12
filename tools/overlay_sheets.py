#!/usr/bin/env python3
"""overlay_sheets.py - sheet-driven English for every source the container
injector and ui_strings.py do not cover: the overlay `.data` strings, the
main exe's remaining strings (the information magazine), text tables inside
data files (FUKUTEST/JOHO.NBN) and the containers that have no sheet
(MASTER/KOSIEN.BIN, BUNKA/URANAI.BIN, TARA_OBJ/KARAKASI.BIN).

Inputs, in order of precedence:
  1. an editor sheet with the cloud agent's columns under
     translation/localization/sheets/<rel>.csv (e.g. EXEDIR/TEL.EXN.csv);
  2. config/patch/overlay_drafts.json and the fragments under
     config/patch/overlay_drafts.d/*.json: `by_addr` ("<rel>:<0xoffset>"),
     one entry per copy of a string (the drafts used to have a `by_text`
     table keyed by the Japanese; the public tree carries no retail text,
     D4(a), so a committed `by_text` is refused -- english_for still takes
     an in-memory one);
  3. the DRAFT sheets text_sources.py writes under build/patch/gen/sheets/
     (Japanese, offset, slot; English empty) -- regenerated here when
     missing.

Output: build/patch/gen/overlay_sheets.json, merged into the profile by
build_patched.py (`strings_files`): an entry per translated string, in
place when the English fits the slot (the string's bytes plus the zero
padding up to the next non-zero byte), through its pointer word when the
file holds exactly one (overlay relocation pool / main string pool), and
reported otherwise; `files` entries for the data files.  With
--containers the extra containers' sheets are written with the English
filled in to build/patch/gen/sheets_en/ for tools/patch/inject.py
(config/patch/containers_extra.json), which runs before the DTE table
exists, so that mode needs no dictionary.

  python3 tools/patch/overlay_sheets.py --containers          # before inject
  python3 tools/patch/overlay_sheets.py --dte build/patch/gen/dte.json
"""
import argparse
import csv
import json
import re
import struct
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, CONTAINERS, PATCH_CONFIG, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import textcodec  # noqa: E402
import ui_strings  # noqa: E402
import compose_check  # noqa: E402

SHEETS = ROOT / "build" / "patch" / "gen" / "sheets"
SHEETS_EN = ROOT / "build" / "patch" / "gen" / "sheets_en"
EDITOR = SHEETS
DRAFTS = PATCH_CONFIG / "overlay_drafts.json"
EXTRA = PATCH_CONFIG / "containers_extra.json"
MAIN_DATA = (0x800B5A60, 0x800BD250)
FW_DIGITS = str.maketrans("０１２３４５６７８９・", "0123456789-")
SHEET_COLS = ["ID", "File", "Offset", "MaxBytes", "PtrSite", "Kind", "Speaker",
              "Japanese", "Tokens", "English", "Status", "Notes"]


def ensure_sheets(force=False):
    if force or not SHEETS.exists() or not any(SHEETS.rglob("*.csv")):
        subprocess.run([sys.executable, str(TOOLS_PATCH / "text_sources.py"),
                        "--draft-sheets", "--quiet"], check=True, cwd=ROOT,
                       capture_output=True)


DRAFTS_D = PATCH_CONFIG / "overlay_drafts.d"
COMPOSED = set()     # compose_check.composed_slots(): composition pieces ({dst} templates)
MODULE_OK = set()    # compose_check.module_slots(): + the reasoned draw-only slots
INJECTED_DIRS = {"SERIFU", "SPEAKTST", "BUNKA", "MASTER", "TAIIKU", "SHIAI"}   # inject.DEFAULT_DIRS
# Slots whose real size the trailing-zero heuristic (ui_strings.slot_of)
# overstates because the code copies a fixed-size block.  SHOUGATU's shrine
# wishes 学業成就 / 健康祈願 / 恋愛成就 are three 9-byte records that
# shougatu_taku_set copies as ONE 27-byte block (Blk27 D_80143E48) and
# strcpy's from buf[9 * serifu_no]: each wish is at most 8 bytes + NUL, the
# last one included (the zeros after it are never copied, so a longer
# string runs off the stack buffer: "Luck in love" did, 10 bytes).
SLOT_CAPS = {("EXEDIR/SHOUGATU.EXN", 0x11e48): 8,
             ("EXEDIR/SHOUGATU.EXN", 0x11e51): 8,
             ("EXEDIR/SHOUGATU.EXN", 0x11e5a): 8}


def synthetic_row(rel: str, off: int, data: bytes):
    """a draft keyed by address that no sheet lists (a one-character joiner
    such as RPG_BAT's は or TEL's 月/日, below the inventory's two-character
    floor): accepted when a C string starts there (a NUL before it) and it
    reads as retail Shift-JIS text (or the string is word-aligned); the
    row the build then places"""
    record = off >= 2 and data[off - 2] == 0 and data[off - 1] in b" gE"
    if off <= 0 or off >= len(data) or data[off] == 0 or \
            (data[off - 1] != 0 and off % 4 and not record):
        return None             # a C string starts after a NUL or on a word (ENDING's
                                # 廊下 follows its pointer table directly), or one byte
                                # after a record's command letter (BUNKA_SD's stage
                                # lines: ' ' / 'g' + text, the text drafted at +1)
    e = data.find(b"\0", off)
    import tagged_rows
    try:
        jp = tagged_rows.retail_to_sheet(data[off:e])
    except (UnicodeDecodeError, ValueError):
        return None
    if not any(ord(c) > 0x7F for c in jp):
        return None
    return {"ID": f"assets/extracted_iso/CDROM/{rel}:0x{off:x}", "File": "", "Offset": f"0x{off:x}",
            "MaxBytes": str(e - off), "PtrSite": "", "Kind": "line", "Speaker": "",
            "Japanese": jp, "Tokens": "", "English": "", "Status": "untranslated",
            "Notes": "synthetic row (by_addr draft of a string no sheet lists)"}


def injected_containers():
    """the container files inject.py repacks (translation/localization/
    containers.json entries in its directories), as <DIR>/<FILE>"""
    p = CONTAINERS
    if not p.exists():
        return set()
    out = set()
    for k in json.loads(p.read_text()):
        rel = k.split("CDROM/", 1)[-1]
        if rel.split("/")[0] in INJECTED_DIRS:
            out.add(rel)
    return out


def load_drafts():
    """overlay_drafts.json plus every fragment under overlay_drafts.d/
    (one per source group, same keys); a fragment may not redefine a key
    the others already set"""
    d = json.loads(DRAFTS.read_text()) if DRAFTS.exists() else {}
    if d.get("by_text"):
        raise SystemExit(f"[overlay_sheets] {DRAFTS.name}: `by_text` is keyed by retail "
                         f"Japanese, which the tree must not carry: key the drafts by_addr")
    by_text, by_addr = {}, dict(d.get("by_addr", {}))
    for frag in sorted(DRAFTS_D.glob("*.json")) if DRAFTS_D.exists() else []:
        f = json.loads(frag.read_text())
        if f.get("by_text"):
            raise SystemExit(f"[overlay_sheets] {frag.name}: `by_text` is keyed by retail "
                             f"Japanese, which the tree must not carry: key the drafts by_addr")
        for src, dst in ((f.get("by_text", {}), by_text), (f.get("by_addr", {}), by_addr)):
            for k, v in src.items():
                if k in dst and dst[k] != v:
                    raise SystemExit(f"[overlay_sheets] {frag.name}: {k!r} already drafted "
                                     f"as {dst[k]!r}")
                dst[k] = v
    return by_text, by_addr


def read_sheet(path: Path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def english_for(rel: str, row: dict, by_text, by_addr, editor_rows):
    """the English of one row: editor sheet > by_addr > by_text > auto"""
    off = int(row["Offset"], 16)
    jp = row["Japanese"]
    e = editor_rows.get(off)
    if e and (e.get("English") or "").strip() and e.get("Status", "draft") != "untranslated":
        return e["English"].strip(), "editor"
    for k in (f"{rel}:0x{off:x}", f"{rel[len('CDROM/'):]}:0x{off:x}" if rel.startswith("CDROM/") else None):
        if k and k in by_addr:
            return by_addr[k], "by_addr"
    if jp in by_text:
        return by_text[jp], "by_text"
    # fullwidth digit records (B.W.H figures) are transliterated
    if jp and all(c in "０１２３４５６７８９・" for c in jp):
        return jp.translate(FW_DIGITS), "auto"
    return "", ""


# why a sheet row has no English of its own (the build report's classes);
# anything else is "untranslated_visible" and fails the build
NO_ENGLISH_CLASSES = {
    "covered_in_place": "ui_strings.py rewrites this string in place (its English "
                        "is written in ui_strings.py, not in a draft fragment)",
    "covered_inside_rewrite": "the row starts inside a string ui_strings.py "
                              "rewrites whole (a printf format's tail)",
    "covered_blank": "ui_strings.py blanks this string on purpose (an explicit \"\": "
                     "its meaning is carried by the English of the line before it, "
                     "e.g. NAME_ENT's 'is that OK?' after \"Recreate the system file?\")",
    "covered_relocated": "ui_strings.py relocates this string: its English goes to "
                         "the string pool and the pointer word that named it is "
                         "rewritten, so the retail slot is never drawn",
    "kept": "kept Japanese on purpose: listed under \"keep\" in "
            "config/patch/overlay_drafts.d/*.json with the reason",
}


def load_keep():
    """the reasoned "keep" lists of the draft fragments: {"<rel>:0xoff":
    reason} for strings that stay Japanese on purpose (never drawn, debug
    console only, read by a BIOS with only a Shift-JIS font, compared
    against player input)"""
    keep = {}
    frags = [DRAFTS] + (sorted(DRAFTS_D.glob("*.json")) if DRAFTS_D.exists() else [])
    for frag in frags:
        if not frag.exists():
            continue
        for k, why in json.loads(frag.read_text()).get("keep", {}).items():
            if not str(why).strip():
                raise SystemExit(f"[overlay_sheets] {frag.name}: keep {k!r} has no reason")
            keep[k] = why
    return keep


def classify_untranslated(rel, off, is_main, is_exn, ov, have, spans, ptr_cover, keep,
                          cover_text):
    """(class, reason) for a sheet row without English"""
    k = f"{rel}:0x{off:x}"
    if k in keep:
        return "kept", keep[k]
    if is_main or is_exn:
        tgt = "main" if is_main else ov
        addr = (0x80041000 - 0x800 if is_main else 0x80132000) + off
        text = cover_text.get((tgt, addr))
        if text is not None and any(ord(c) > 0x7E and c not in textcodec.LATIN_SJIS_OK
                                    for c in text):
            return "untranslated_visible", (f"the covering ui_strings.py / profile entry is "
                                            f"still Japanese: {text[:30]!r}")
        if text == "" and (addr in have.get(tgt, ()) or addr in ptr_cover.get(tgt, ())):
            return "covered_blank", NO_ENGLISH_CLASSES["covered_blank"]
        if addr in have.get(tgt, ()):
            return "covered_in_place", NO_ENGLISH_CLASSES["covered_in_place"]
        if any(a0 < addr < a1 for a0, a1 in spans.get(tgt, ())):
            return "covered_inside_rewrite", NO_ENGLISH_CLASSES["covered_inside_rewrite"]
        if addr in ptr_cover.get(tgt, ()):
            return "covered_relocated", NO_ENGLISH_CLASSES["covered_relocated"]
    return "untranslated_visible", ("no draft, no ui_strings.py entry, no keep reason: "
                                    "a drawn string left Japanese")


def pointer_sites(data: bytes, base: int, addr: int, lo=None, hi=None):
    needle = struct.pack("<I", addr)
    out = []
    i = data.find(needle)
    while i != -1:
        if i % 4 == 0 and (lo is None or lo <= base + i < hi):
            out.append(base + i)
        i = data.find(needle, i + 1)
    return out


def write_container_sheets(extra, by_text, by_addr):
    """the extra containers' English sheets for inject.py"""
    for k, info in extra.items():
        n = 0
        rel = k.split("extracted_iso/")[1]                 # CDROM/DIR/FILE
        src = SHEETS / (rel.replace("CDROM/", "") + ".csv")
        if not src.exists():
            print(f"[overlay_sheets] {rel}: no draft sheet (text_sources.py --draft-sheets)")
            continue
        rows = read_sheet(src)
        ed = EDITOR / (rel.replace("CDROM/", "") + ".csv")
        editor_rows = {int(r["Offset"], 16): r for r in read_sheet(ed)} if ed.exists() else {}
        dst = locate(info["sheet"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=SHEET_COLS)
            wr.writeheader()
            for r in rows:
                en, how = english_for(rel, r, by_text, by_addr, editor_rows)
                r = dict(r)
                r["English"] = en
                r["Status"] = "draft" if en else "untranslated"
                r["Notes"] = (r.get("Notes", "") + f"; English: {how}") if en else r.get("Notes", "")
                wr.writerow({c: r.get(c, "") for c in SHEET_COLS})
                n += bool(en)
        print(f"[overlay_sheets] {rel}: {n} rows with English -> {dst.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dte", default="build/patch/gen/dte.json")
    ap.add_argument("--out", default="build/patch/gen/overlay_sheets.json")
    ap.add_argument("--profile", default="config/patch/english.json")
    ap.add_argument("--containers", action="store_true",
                    help="only write the extra containers' English sheets")
    a = ap.parse_args()
    extra = json.loads(EXTRA.read_text()) if EXTRA.exists() else {}
    extra_rel = {k.split("extracted_iso/")[1] for k in extra}
    # A fresh tree: text_sources.py would make the draft sheets before the
    # extra containers have a sheet, so it cannot see their tagged rows
    # (speaker-prefixed lines, e.g. KOSIEN's announcer strings) and lists
    # the text after each speaker prefix as a row of its own.  Injecting
    # such a sheet overwrote that "row" (inject.py: immutable row changed,
    # MASTER/KOSIEN.BIN:0x329): the first build of a clean checkout failed
    # and a second one passed.  So when a container sheet is missing, write
    # them, then regenerate the drafts with them in place.
    fresh = a.containers and any(not locate(i["sheet"]).exists() for i in extra.values())
    ensure_sheets()
    by_text, by_addr = load_drafts()

    # --- the extra containers: sheets with English for inject.py ---------
    if a.containers:
        write_container_sheets(extra, by_text, by_addr)
        if fresh:
            ensure_sheets(force=True)
            by_text, by_addr = load_drafts()
            write_container_sheets(extra, by_text, by_addr)
        return

    dte = []
    p = locate(a.dte)
    if p.exists():
        dte = json.loads(p.read_text())["entries"]
    prof = json.loads(locate(a.profile).read_text())
    have = {"main": set()}
    spans = {}
    ptr_cover = {}
    cover_text = {}         # (target, retail addr) -> the English that covers it
    for tgt, lst in [("main", prof.get("main", {}).get("strings", []))] + \
            [(ov, spec.get("strings", [])) for ov, spec in prof.get("overlays", {}).items()]:
        for s in lst:
            if "addr" in s:
                cover_text[(tgt, int(s["addr"], 16))] = s.get("text", "")
    for s in prof.get("main", {}).get("strings", []):
        if "addr" in s:
            have["main"].add(int(s["addr"], 16))
    for ov, spec in prof.get("overlays", {}).items():
        have[ov] = {int(s["addr"], 16) for s in spec.get("strings", []) if "addr" in s}
    gen = ROOT / "build/patch/gen/ui_strings.json"
    if gen.exists():
        g = json.loads(gen.read_text())
        for s in g.get("main", []):
            if "addr" in s:
                have["main"].add(int(s["addr"], 16))
        for ov, lst in g.get("overlays", {}).items():
            have.setdefault(ov, set()).update(int(s["addr"], 16) for s in lst if "addr" in s)
        # a ui_strings entry rewrites its retail string WHOLE (a sprintf
        # format such as SHOUGATU's "おっ、%sだ。" -> "Oh, it's %s."), so a
        # sheet row that starts inside it (the "だ。" after the %s) is
        # covered: placing it would cut the new string short
        for tgt, lst in [("main", g.get("main", []))] + list(g.get("overlays", {}).items()):
            for s in lst:
                if "addr" in s and s.get("max_bytes"):
                    a0 = int(s["addr"], 16)
                    spans.setdefault(tgt, []).append((a0, a0 + int(s["max_bytes"])))
        # a ui_strings entry that RELOCATES a string ("ptr_at": the English
        # goes to the pool and the pointer word is rewritten) covers the
        # retail string the pointer named, whose slot stays untouched
        for tgt, lst in [("main", g.get("main", []))] + list(g.get("overlays", {}).items()):
            img, ibase = ui_strings.load_target(tgt)
            for s in lst:
                if "ptr_at" in s:
                    p = int(s["ptr_at"], 16) - ibase
                    a0 = struct.unpack_from("<I", img, p)[0]
                    ptr_cover.setdefault(tgt, set()).add(a0)
                    cover_text[(tgt, a0)] = s.get("text", "")
                elif "addr" in s:
                    cover_text[(tgt, int(s["addr"], 16))] = s.get("text", "")
    out = {"main": [], "overlays": {}, "files": {}}
    stats = defaultdict(Counter)
    untranslated = []
    keep = load_keep()
    COMPOSED.clear()
    COMPOSED.update(compose_check.composed_slots())
    MODULE_OK.clear()
    MODULE_OK.update(COMPOSED | set(compose_check.draw_slots()))
    overflow = []
    for sheet in sorted(SHEETS.rglob("*.csv")):
        rel = str(sheet.relative_to(SHEETS))[:-4]                 # EXEDIR/TEL.EXN | PSX.EXE
        cdrom = rel if rel == "PSX.EXE" else "CDROM/" + rel
        if cdrom in extra_rel:
            continue                                               # inject.py's job
        if rel in injected_containers():
            # a row the container's sheet lacks, inside a container inject.py
            # repacks: a file offset means nothing after the repack
            print(f"[overlay_sheets] {rel}: inside an injected container, not placeable here "
                  f"(needs a row in the container's sheet)")
            continue
        rows = read_sheet(sheet)
        ed = EDITOR / sheet.relative_to(SHEETS)
        editor_rows = {int(r["Offset"], 16): r for r in read_sheet(ed)} if ed.exists() else {}
        is_main = rel == "PSX.EXE"
        is_exn = rel.startswith("EXEDIR/") and rel.endswith(".EXN")
        ov = Path(rel).stem if is_exn else None
        if is_exn and ov in ("EVENT", "GYOZI", "O"):
            continue
        if is_main:
            data, base = ui_strings.load_target("main")
            base_addr = 0x80041000 - 0x800
        elif is_exn:
            data, base = ui_strings.load_target(ov)
            base_addr = 0x80132000
        else:
            fpath = DECOMP / "assets" / "extracted_iso" / cdrom
            if not fpath.exists():
                continue
            data, base = fpath.read_bytes(), None
            base_addr = None
        listed = {int(r["Offset"], 16) for r in rows}
        for k in by_addr:
            krel, _, koff = k.rpartition(":")
            if krel == rel and int(koff, 16) not in listed:
                syn = synthetic_row(rel, int(koff, 16), data)
                if syn is None:
                    print(f"[overlay_sheets] {k}: no string starts there; draft ignored")
                    continue
                rows.append(syn)
        for r in rows:
            off = int(r["Offset"], 16)
            st = stats[rel]
            st["rows"] += 1
            en, how = english_for(rel, r, by_text, by_addr, editor_rows)
            if not en and how not in ("by_addr", "by_text"):
                # no draft here: say WHY the row has no English of its own
                cls, why = classify_untranslated(rel, off, is_main, is_exn, ov, have,
                                                 spans, ptr_cover, keep, cover_text)
                st[cls] += 1
                untranslated.append({"source": rel, "offset": f"0x{off:x}",
                                     "japanese": r["Japanese"], "class": cls,
                                     "reason": why})
                continue            # an explicit "" is a deliberate blank (a -san suffix)
            st["translated"] += 1
            ln, mx = ui_strings.slot_of(data, off)
            mx = min(mx, SLOT_CAPS.get((rel, off), mx))
            if is_main or is_exn:
                addr = base_addr + off
                target = "main" if is_main else ov
                if addr in have.get(target, set()) or \
                        any(a0 < addr <= a1 for a0, a1 in spans.get(target, ())):
                    st["already"] += 1
                    continue
            cstart = data.rfind(b"\0", 0, off) + 1
            if re.search(rb"%[-0-9]*[sd]", data[cstart:off]) and not \
                    any(a0 < (base_addr or 0) + off <= a1
                        for a0, a1 in spans.get("main" if is_main else ov, ())):
                # the TAIL of a printf format ("だ。" after the %s of
                # "おっ、%sだ。"): placed alone it would cut the format short
                print(f"[overlay_sheets] {rel}:0x{off:x}: row {r['Japanese']!r} is the tail of "
                      f"the printf format {data[cstart:off + ln].decode('shift_jis', 'replace')!r}; "
                      f"not placed (draft the whole format in ui_strings.py)")
                st["translated"] -= 1
                st["untranslated_visible"] += 1
                st["format_piece"] += 1
                continue
            pct = data.find(b"%", off, off + ln)
            if pct >= off + int(r.get("MaxBytes") or ln) and "%" not in en:
                # a printf format the inventory split at its conversion
                # ("おっ、" of "おっ、%sだ。"): the English written up to the
                # NUL would drop the %s and the text after it ("Oh, it's"
                # with no fortune), so the whole format goes through
                # ui_strings.py instead
                print(f"[overlay_sheets] {rel}:0x{off:x}: row {r['Japanese']!r} is a piece of "
                      f"the printf format {data[off:off + ln].decode('shift_jis', 'replace')!r}; "
                      f"not placed (draft the whole format in ui_strings.py)")
                st["translated"] -= 1
                st["untranslated_visible"] += 1
                st["format_piece"] += 1
                continue
            if is_main or is_exn:
                target = "main" if is_main else ov
                composed = (target, addr) in COMPOSED
                if "{dst}" in en and not composed:
                    raise SystemExit(f"[overlay_sheets] {rel}:0x{off:x}: {{dst}} in {en!r}, but the "
                                     f"slot is not a piece of any config/patch/compositions.json "
                                     f"composition (a template only works on a strcat piece)")
                if (target, addr) in MODULE_OK and mx >= 2 and (
                        "{dst}" in en or len(textcodec.encode(en, dte)) > mx):
                    # a composed string's joiner whose English does not fit
                    # its slot, or a reordering template, or a draw-only
                    # slot (compositions.json "draw_slots") with no pointer
                    # word: a module string (src/patch/main/text_names.c,
                    # PT_C_STR)
                    entry = {"addr": f"0x{addr:08X}", "max_bytes": mx, "text": en,
                             "encoding": "patch", "module": True, "note": r["Japanese"][:40]}
                    st["module"] += 1
                    if is_main:
                        out["main"].append(entry)
                    else:
                        out["overlays"].setdefault(ov, []).append(entry)
                    continue
                enc = textcodec.encode(en, dte)
                if is_main:
                    sites = pointer_sites(data, base, addr, *MAIN_DATA)
                else:
                    sites = pointer_sites(data, base, addr)
                entry = None
                if len(enc) <= mx:
                    entry = {"addr": f"0x{addr:08X}", "max_bytes": mx, "text": en,
                             "encoding": "patch", "dte": True, "note": r["Japanese"][:40]}
                    st["in_place"] += 1
                elif len(sites) == 1:
                    entry = {"ptr_at": f"0x{sites[0]:08X}", "text": en, "encoding": "patch",
                             "dte": True, "note": r["Japanese"][:40]}
                    st["relocated"] += 1
                else:
                    st["overflow"] += 1
                    overflow.append((rel, f"0x{off:x}", len(enc), mx, len(sites), en, r["Japanese"][:30]))
                    continue
                if is_main:
                    out["main"].append(entry)
                else:
                    out["overlays"].setdefault(ov, []).append(entry)
            else:
                enc = textcodec.encode(en)
                if len(enc) > mx:
                    st["overflow"] += 1
                    overflow.append((rel, f"0x{off:x}", len(enc), mx, 0, en, r["Japanese"][:30]))
                    continue
                out["files"].setdefault(cdrom, []).append(
                    {"offset": f"0x{off:X}", "max_bytes": mx, "text": en, "encoding": "patch",
                     "note": r["Japanese"][:40]})
                st["in_place"] += 1
    dst = locate(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    tot = Counter()
    for v in stats.values():
        tot.update(v)
    no_en = {c: tot[c] for c in NO_ENGLISH_CLASSES}
    rep = {"sources": {k: dict(v) for k, v in stats.items()},
           "totals": {"rows": tot["rows"], "with_english": tot["translated"],
                      **no_en, "untranslated_visible": tot["untranslated_visible"]},
           "classes": NO_ENGLISH_CLASSES,
           "rows_without_english": untranslated,
           "overflow": [{"source": s, "offset": o, "bytes": n, "slot": mx, "pointer_sites": ps,
                         "text": en, "japanese": jp} for s, o, n, mx, ps, en, jp in overflow]}
    (dst.parent / "overlay_sheets.report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    for k, v in sorted(stats.items()):
        if v["translated"]:
            print(f"[overlay_sheets] {k:28s} rows {v['rows']:4d} english {v['translated']:4d} "
                  f"in-place {v['in_place']:4d} relocated {v['relocated']:3d} module {v['module']:3d} "
                  f"overflow {v['overflow']:3d} already {v['already']:3d}")
    for s, o, n, mx, ps, en, jp in overflow[:40]:
        print(f"OVERFLOW {s} {o}: {n} > {mx} bytes, {ps} pointer sites: {en!r} ({jp})")
        print(f"OVERFLOW {s} {o}: {n} > {mx} bytes, {ps} pointer sites: {en!r} ({jp})",
              file=sys.stderr)
    print(f"[overlay_sheets] {tot['rows']} rows, {tot['translated']} with English: "
          f"{tot['in_place']} in place, {tot['relocated']} relocated, {tot['module']} module, "
          f"{tot['overflow']} overflow, {tot['format_piece']} format pieces refused -> "
          f"{dst.relative_to(ROOT)}")
    covered = [c for c in NO_ENGLISH_CLASSES if c.startswith("covered")]
    print(f"[overlay_sheets] rows without English of their own: "
          f"{sum(tot[c] for c in covered)} covered by ui_strings.py ("
          + ", ".join(f"{tot[c]} {c[len('covered_'):].replace('_', ' ')}" for c in covered)
          + f"), {tot['kept']} kept Japanese on purpose (\"keep\" lists), "
          f"{tot['untranslated_visible']} untranslated (visible)")
    bad = [u for u in untranslated if u["class"] == "untranslated_visible"]
    for u in bad[:40]:
        print(f"UNTRANSLATED {u['source']} {u['offset']}: {u['japanese'][:40]!r} ({u['reason']})",
              file=sys.stderr)
    if bad:
        # a drawn string with no English and no reason is a build error:
        # draft it (config/patch/overlay_drafts.d/, tools/patch/draft_check.py
        # --todo) or list it under "keep" with the reason it stays Japanese
        print(f"[overlay_sheets] {len(bad)} drawn strings have no English (visible)",
              file=sys.stderr)
        sys.exit(1)
    if overflow:
        # a string that does not fit is left Japanese: a build error, not a
        # report line (shorten it: tools/patch/draft_check.py)
        print(f"[overlay_sheets] {len(overflow)} strings do not fit their slot", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
