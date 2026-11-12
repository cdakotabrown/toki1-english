#!/usr/bin/env python3
"""text_gates.py - the build-failing checks on the English text of a patch
build (run by build_patched.py after the disc is written; also standalone).

Every gate reads what the build actually produced (build/patch/...) or the
same inputs and rules the build used; any error fails the build.

  fit        every draft fragment fits its slot and window
             (draft_check.py on config/patch/overlay_drafts*.json), every
             choice override fits the retail box (choice_check.py), the
             container injector placed every translated row (0 fallback),
             kept 0 rows Japanese for a token mismatch, wrote 0 speaker tag
             wider than the 44-px name column, 0 over-wide choices, 0
             unencodable rows; no word of a message is wider than the
             201-px event window (it could not wrap); overlay_sheets.py and
             ui_strings.py already fail on a string that does not fit
  records    the item-name table of record is current (item_names.py --check)
  compose    every runtime-composed string (compose_check.py)
  sites      every named string a draw call / banner / name-buffer copy uses
             reads English in the build (compositions.json "kept_japanese"
             lists, with the reason, the ones Japanese on purpose)
  codes      control codes per row: every {opt}-separated segment of the
             English carries the same name / runtime tokens as the
             Japanese segment (a {P} that moves to another reply of an
             alternatives row would be drawn in the wrong reply)
  readback   the repacked containers on disk: every translated row,
             followed through its pointer word, decodes with the build's DTE
             table without a '?' fallback byte and carries the Japanese
             row's control bytes; the DTE and module-string tables in the
             patched exe hold exactly the build's entries
  uncovered  no drawn Japanese without English: the inventory's visible-
             uncovered list (text_sources.py, the sheet-missing column) is
             empty, and every pointer word of every repacked container that
             still lands on retail Japanese bytes is a reasoned "keep" of
             config/patch/tagged_rows_en.json (proven never displayed)
  glyphs     every character of the build's English (containers, drafts, UI
             strings, DTE entries, module strings) is drawable by the
             renderer path that draws it: a glyph of the proportional font
             (tools/patch/font) for the engine; for the debug profile's
             strings, a glyph of the debug font (debug_fontgen.py cells);
             each one-glyph button string the game draws with code
             (BUTTON_CELLS) is a glyph the patched renderer has

  python3 tools/patch/text_gates.py [--out build/patch] [--only GATE ...]
"""
import argparse
import csv
import json
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, SHEETS, CONTAINERS, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import retail_text  # noqa: E402
import textcodec  # noqa: E402

NAME_TOKENS = ("{P}", "{G}", "{p}", "{m}", "{F}", "{Y}", "{S}", "{O}", "{W}", "{A}", "{M}")
TOK_RE = re.compile(r"\{(?:P|G|p|m|F|Y|S|O|W|A|M)\}")
MAIN_BASE = 0x80041000 - 0x800
# what every profile shares (the containers, the DTE table, the generated
# string files: build/patch/ whatever the profile's "out"); the exe and the
# <profile>.report.json come from the profile's own out directory
SHARED = ROOT / "build" / "patch"
PROFILE = ["english"]
# the one-glyph button strings (pad circle / cross, mouse right / left):
# get_pad_str / get_pad_str2 in the main exe, get_etc_yes_button /
# get_etc_no_button in ETC.  (where, file in the build, load base, cells)
BUTTON_CELLS = (
    ("main", "SLPS_000.65", MAIN_BASE, (0x800BCC24, 0x800BCC28, 0x800BCC2C, 0x800BCC30)),
    ("ETC", "EXEDIR/ETC.EXN", 0x80132000, (0x80150128, 0x80150144, 0x80150148, 0x8015014C)),
)


def run_tool(args):
    r = subprocess.run([sys.executable, str(locate(args[0]).relative_to(ROOT))] + args[1:],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


def gate_fit(out):
    errs = []
    frags = [PATCH_CONFIG / "overlay_drafts.json"] + \
        sorted((PATCH_CONFIG / "overlay_drafts.d").glob("*.json"))
    for f in frags:
        rc, txt = run_tool(["tools/patch/draft_check.py", "--quiet", str(f.relative_to(ROOT))])
        if rc != 0:
            errs += [ln for ln in txt.splitlines() if ln.startswith("ERROR")] or [txt[-300:]]
    rc, txt = run_tool(["tools/patch/choice_check.py"])
    if rc != 0:
        errs += [ln for ln in txt.splitlines() if ln.startswith("ERROR")] or [txt[-300:]]
    rep = json.loads((SHARED / "inject.report.json").read_text())["totals"]
    for k in ("rows_fallback", "token_mismatch", "label_over_budget", "choice_too_wide",
              "unencodable"):
        if rep.get(k):
            errs.append(f"inject: {k} = {rep[k]} (build/patch/inject.report.json)")
    osr = SHARED / "gen" / "overlay_sheets.report.json"
    if osr.exists():
        osj = json.loads(osr.read_text())
        for o in osj.get("overflow", []):
            errs.append(f"overlay_sheets overflow: {o['source']} {o['offset']} {o['text']!r}")
        # every sheet row without English of its own is covered elsewhere
        # (ui_strings.py) or kept Japanese with a reason; none is visible
        if "totals" not in osj:
            errs.append("overlay_sheets report has no totals (stale overlay_sheets.py run?)")
        for u in osj.get("rows_without_english", []):
            if u["class"] == "untranslated_visible":
                errs.append(f"untranslated (visible): {u['source']} {u['offset']} "
                            f"{u['japanese'][:30]!r}: {u['reason']}")
    # a word wider than the message body cannot wrap
    import inject
    for path in sorted(SHEETS.glob("*/*.csv")):
        if path.parent.name not in inject.DEFAULT_DIRS:
            continue
        for r in retail_text.read_sheet(path):
            errs += wide_words(r)
    return errs


def wide_words(r):
    """a row's words wider than the event window (they cannot wrap); reads
    only the English, so the disc-free lint (lint_sheets.py) shares it"""
    import inject
    en = (r.get("English") or "").strip()
    if not en or r.get("Status") == "untranslated":
        return []
    return [f"{r['ID']}: the word {word!r} is {textcodec.width(word)} px, "
            f"wider than the {inject.LINE_PX}-px window"
            for word in re.split(r"\s|\{br\}|\{opt\}", TOK_RE.sub("", en))
            if word and textcodec.width(word) > inject.LINE_PX]


def gate_records(out):
    rc, txt = run_tool(["tools/patch/item_names.py", "--check"])
    return [] if rc == 0 else [txt.strip()]


def gate_compose(out):
    import compose_check
    n, report = compose_check.run(out=str(out.relative_to(ROOT)), quiet=True)
    return [f"{r['id']}: {r['error']} (e.g. {r['examples'][0]!r})" for r in report] + \
        ([] if n == len(report) else [f"compose: {n - len(report)} coverage errors (see above)"])


def gate_sites(out):
    """every named string handed to a draw call reads English in the build,
    except the reasoned list config/patch/compositions.json "kept_japanese"""
    import compose_check
    spec = json.loads(compose_check.SPEC.read_text())
    img = compose_check.Image(True, str(out.relative_to(ROOT)))
    left = compose_check.drawn_literals_japanese(img, spec.get("kept_japanese", {}))
    return [f"{k}: {fn} in {src} draws {txt[:40]!r}" for k, (src, fn, txt) in sorted(left.items())]


def segment_tokens(text):
    return [Counter(TOK_RE.findall(seg)) for seg in text.split("{opt}")]


def gate_codes(out):
    import inject
    errs = []
    over = json.loads((PATCH_CONFIG / "choice_overrides.json").read_text()).get("rows", {})
    for path in sorted(SHEETS.glob("*/*.csv")):
        if path.parent.name not in inject.DEFAULT_DIRS:
            continue
        for r in retail_text.read_sheet(path):
                en = over.get(inject.choice_key(r["ID"])) or (r.get("English") or "")
                if not en.strip() or r.get("Status") == "untranslated":
                    continue
                jp = r["Japanese"]
                if Counter(TOK_RE.findall(jp)) != Counter(TOK_RE.findall(en)) or \
                        jp.count("{opt}") != en.count("{opt}"):
                    continue        # the injector keeps such a row Japanese (gate_fit counts it)
                if segment_tokens(jp) != segment_tokens(en):
                    errs.append(f"{inject.choice_key(r['ID'])}: tokens per segment "
                                f"{[dict(c) for c in segment_tokens(en)]} != Japanese "
                                f"{[dict(c) for c in segment_tokens(jp)]}")
    return errs


def gate_readback(out):
    """decode every placed container row from the files the build wrote"""
    import inject
    errs = []
    dte = json.loads((SHARED / "gen" / "dte.json").read_text())["entries"]
    conts = json.loads((CONTAINERS).read_text())
    rep = json.loads((SHARED / "inject.report.json").read_text())
    n = 0
    for c in rep["containers"]:
        cdrom = c["file"] if "file" in c else c.get("cdrom")
        if not cdrom:
            continue
        built = SHARED / "files" / cdrom
        key = f"assets/extracted_iso/{cdrom}"
        if not built.exists() or key not in conts:
            continue
        data = built.read_bytes()
        retail = locate(key).read_bytes()
        base = int(conts[key]["base"], 16)
        sheet = locate(conts[key]["sheet"])
        if not sheet.exists():
            continue
        for r in retail_text.read_sheet(sheet):
                if not r.get("PtrSite"):
                    continue
                site = int(r["PtrSite"].split(";")[0].split()[0], 16)
                if site + 4 > len(data):
                    continue
                ptr = struct.unpack_from("<I", data, site)[0]
                off = ptr - base
                if not 0 <= off < len(data):
                    errs.append(f"{cdrom} {r['Offset']}: pointer 0x{ptr:08X} outside the file")
                    continue
                raw = data[off:data.index(b"\0", off)]
                if raw == retail[int(r["Offset"], 16):retail.index(b"\0", int(r["Offset"], 16))]:
                    continue        # untouched (untranslated / immutable) row
                n += 1
                txt = textcodec.decode(raw, dte)
                if re.search(r"\{(x[0-9A-F]{2}|\?)\}", txt):
                    errs.append(f"{cdrom} {r['Offset']}: undrawable byte in {txt[:60]!r}")
                body = raw
                # tagged rows: tag byte + speaker + 0x1F separator
                if body and body[0] in inject.TAG_BYTES.values() and inject.TAG_SEP in body:
                    body = body[body.index(inject.TAG_SEP) + 1:]
                got = Counter(textcodec.TOKEN_BY_BYTE[b] for b in body
                              if b in textcodec.TOKEN_BY_BYTE and b not in (0x01,))
                want = Counter(t for t in re.findall(r"\{[A-Za-z]+\}", r["Japanese"])
                               if t in textcodec.TOKENS and t != "{br}")
                if got != want:
                    errs.append(f"{cdrom} {r['Offset']}: control codes {dict(got)} != the "
                                f"Japanese row's {dict(want)}: {txt[:60]!r}")
    # the tables the renderer expands
    exe = (out / "SLPS_000.65").read_bytes()
    report = json.loads((out / f"{PROFILE[0]}.report.json").read_text())
    syms = report.get("module", {}).get("symbols", {})

    def cstr(addr):
        o = addr - MAIN_BASE
        return exe[o:exe.index(b"\0", o)]
    tab = int(syms["patch_dte_table"], 16)
    for k, e in enumerate(dte):
        ptr = struct.unpack_from("<I", exe, tab - MAIN_BASE + 4 * k)[0]
        if cstr(ptr).decode("ascii", "replace") != e:
            errs.append(f"patch_dte_table[{k}] holds {cstr(ptr)!r}, the build's entry is {e!r}")
    if not n:
        errs.append("readback: no translated container row was read back (wrong paths?)")
    return errs


def gate_glyphs(out):
    errs = []
    font = textcodec.font()
    have = set(font)

    def check(where, text):
        bad = sorted({c for c in text if 0x20 <= ord(c) <= 0x7E and c not in have})
        if bad:
            errs.append(f"{where}: no glyph for {''.join(bad)!r} in {text[:50]!r}")
    for e in json.loads((SHARED / "gen" / "dte.json").read_text())["entries"]:
        check("DTE entry", e)
    for f in [PATCH_CONFIG / "overlay_drafts.json"] + \
            sorted((PATCH_CONFIG / "overlay_drafts.d").glob("*.json")):
        for k, v in json.loads(f.read_text()).get("by_addr", {}).items():
            check(f"{f.name} {k}", v)
        for k, v in json.loads(f.read_text()).get("by_text", {}).items():
            check(f"{f.name} {k}", v)
    for gen in ("ui_strings.json", "overlay_sheets.json"):
        p = SHARED / "gen" / gen
        if p.exists():
            g = json.loads(p.read_text())
            for s in g.get("main", []) + [x for lst in g.get("overlays", {}).values() for x in lst]:
                check(gen, s["text"])
    # the button strings the game draws with code, one glyph each, over the
    # yes/no and "press [button]" lines: one character, so the inventory's
    # two-character floor never sees them (a mouse player's "right" / "left"
    # kanji drew the missing-glyph box until 2026-11-07).  Every one must be
    # a glyph the patched renderer has: the retail font below the module's
    # kanji limit, the kept subset, or the patch's icons.
    ks = SHARED / "gen" / "kanji_subset.json"
    if ks.exists():
        drawable = set(json.loads(ks.read_text())["drawable_codes"])
        for where, path, base, cells in BUTTON_CELLS:
            p = out / path
            if not p.exists():          # a test profile without that file
                continue
            data = p.read_bytes()
            for addr in cells:
                o = addr - base
                raw = data[o:data.index(b"\0", o)]
                codes = [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw) - 1, 2)]
                if len(raw) != 2 or codes[0] not in drawable:
                    errs.append(f"button string {where} 0x{addr:08X} = {raw.hex()} is not "
                                f"one drawable glyph")
    # the debug profile draws its own strings with the debug font: bytes
    # with bit 5 clear (0x40..0x5F) are the 8x8 capitals, bit 5 set the
    # small caps a..z and ; < = > ? (debug_fontgen.py); digits and most
    # punctuation alias other cells
    dbg = locate("src/patch/debug")
    if dbg.exists():
        ok = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_@abcdefghijklmnopqrstuvwxyz;<=>? ")
        for c_file in sorted(dbg.glob("*.c")):
            src = re.sub(r"/\*.*?\*/", "", c_file.read_text(), flags=re.S)
            src = re.sub(r"#include[^\n]*", "", src)
            for m in re.finditer(r"\"([^\"\n]*)\"", src):
                bad = sorted({c for c in m.group(1) if c not in ok})
                if bad:
                    errs.append(f"{c_file.name}: debug-font string {m.group(1)!r} uses "
                                f"{''.join(bad)!r}, which the debug font cannot draw "
                                f"(bytes 0x20-0x3F alias the a..z cells)")
    return errs


JP_TEXT_RE = re.compile(r"[぀-ヿ一-鿿‥…]")


def gate_uncovered(out):
    """no drawn Japanese without English.  (1) the inventory's visible-
    uncovered list (text_sources.json, the coverage table's sheet-missing
    rows) is empty; (2) in every repacked container, every pointer word that
    lands on a string still holding its retail Japanese bytes (kana / kanji /
    ‥ …, the tag byte and speaker included) is a reasoned "keep" of
    config/patch/tagged_rows_en.json, and every keep entry still names such
    a string.  (2) needs no vocabulary test and no two-character floor, so
    it sees what the inventory cannot (a one-kanji lyric fragment 暗)."""
    errs = []
    inv = SHARED / "text_sources.json"
    if not inv.exists():
        errs.append(f"{inv.relative_to(ROOT)} missing: run tools/patch/text_sources.py")
    else:
        doc = json.loads(inv.read_text())
        if "visible_uncovered" not in doc:
            errs.append("text_sources.json has no visible_uncovered list (old inventory)")
        for v in doc.get("visible_uncovered", []):
            errs.append(f"inventory: {v['file']}:{v['offset']} {v['status']}: {v['text'][:40]!r}")
    keep = json.loads((PATCH_CONFIG / "tagged_rows_en.json").read_text()).get("keep", {})
    idx = {}
    for p in (CONTAINERS,
              PATCH_CONFIG / "containers_extra.json"):
        for k, v in json.loads(p.read_text()).items():
            idx[k.split("extracted_iso/", 1)[1]] = v
    rep = json.loads((SHARED / "inject.report.json").read_text())
    seen_keep = set()
    n = 0
    for c in rep["containers"]:
        cdrom = c.get("file")
        built = SHARED / "files" / cdrom if cdrom else None
        if not cdrom or cdrom not in idx or not built.exists():
            errs.append(f"{cdrom}: injected container not found on disk / in the index")
            continue
        data = built.read_bytes()
        retail = (DECOMP / "assets" / "extracted_iso" / cdrom).read_bytes()
        base = int(idx[cdrom]["base"], 16)
        short = cdrom.split("CDROM/", 1)[-1]
        done = set()
        for site in range(0, len(data) - 3, 4):
            off = struct.unpack_from("<I", data, site)[0] - base
            if not 0 <= off < len(data) or off % 4 or off in done:
                continue
            e = data.find(b"\0", off)
            if e <= off or e - off > 600 or retail.find(b"\0", off) != e or data[off:e] != retail[off:e]:
                continue            # empty, not a string, or rewritten by the build
            try:
                txt = data[off:e].decode("shift_jis")
            except UnicodeDecodeError:
                continue
            if not JP_TEXT_RE.search(txt):
                continue
            done.add(off)
            n += 1
            key = f"{short}:0x{off:x}"
            if key in keep:
                seen_keep.add(key)
                continue
            errs.append(f"{key} (pointer at 0x{site:x}) is still Japanese: {txt[:40]!r} -- "
                        f"draft it (tagged_rows_en.json rows / the sheet / overlay_drafts.d) "
                        f"or keep it with the evidence that it is never displayed")
    for k in sorted(set(keep) - seen_keep):
        errs.append(f"tagged_rows_en.json keep {k!r} no longer names a Japanese string "
                    f"behind a pointer: drop it")
    return errs


GATES = {"fit": gate_fit, "records": gate_records, "compose": gate_compose,
         "sites": gate_sites, "codes": gate_codes, "readback": gate_readback,
         "glyphs": gate_glyphs, "uncovered": gate_uncovered}


def run(out=ROOT / "build" / "patch", only=None, name="english"):
    PROFILE[0] = name
    total = 0
    for name, fn in GATES.items():
        if only and name not in only:
            continue
        errs = fn(Path(out))
        total += len(errs)
        print(f"[text_gates] {name}: {'OK' if not errs else f'{len(errs)} errors'}")
        for e in errs[:40]:
            print(f"    {e}")
        if len(errs) > 40:
            print(f"    ... {len(errs) - 40} more")
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "build" / "patch"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--profile-name", default="english",
                    help="the profile whose <name>.report.json and exe sit in --out")
    a = ap.parse_args()
    n = run(Path(a.out), a.only, a.profile_name)
    print(f"[text_gates] {n} errors")
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
