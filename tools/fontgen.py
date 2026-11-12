#!/usr/bin/env python3
"""fontgen.py - compile tools/patch/font/latin12.txt into C tables + metrics.

The text file is the single source of truth for the English patch's Latin
glyphs AND for every tool that has to measure English text (the container
injector pre-wraps lines with the same advances the engine uses).

Outputs (default under build/patch/gen/):
  font_latin.c      const u16 patch_font_rows[95][12]; const u8 patch_font_adv[95];
                    const u16 patch_icon_rows[N][12]; const s32 patch_icon_count
                    (tools/patch/font/icons12.txt: codes 0xEF40, 0xEF41, ...)
  font_latin.json   {"adv": {"A": 7, ...}, "height": 12, "first": 32, "count": 95,
                     "icons": {"EF40": "mouse_left", ...}}

The icons are the button pictures the renderer draws for their private
Shift-JIS codes (icons12.txt; textcodec.ICONS spells them in strings).

Row encoding: 12 rows per glyph, each a u16 with the LEFTMOST pixel at bit
15, so the renderer can shift the row right by the pen position inside a
16-px cell.  adv = glyph box width + 1 px spacing.

Usage: fontgen.py [--src tools/patch/font/latin12.txt] [--out build/patch/gen]
                  [--check]   (parse + report only)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
DEFAULT_SRC = TOOLS_PATCH / "font/latin12.txt"
DEFAULT_ICONS = TOOLS_PATCH / "font/icons12.txt"
ICON_FIRST = 0xEF40                     # patch_text.h PT_ICON_FIRST
DEFAULT_OUT = ROOT / "build" / "patch" / "gen"
HEIGHT = 12
FIRST = 0x20
COUNT = 95


def parse(src: Path):
    glyphs = {}
    lines = src.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        i += 1
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith("glyph "):
            raise SystemExit(f"{src}:{i}: expected 'glyph', got {line!r}")
        parts = line.split()
        name = parts[1]
        ch = " " if name == "space" else name
        if len(ch) != 1 or not (FIRST <= ord(ch) < FIRST + COUNT):
            raise SystemExit(f"{src}:{i}: bad glyph name {name!r}")
        if parts[2] != "adv":
            raise SystemExit(f"{src}:{i}: expected 'adv'")
        adv = int(parts[3])
        if not 1 <= adv <= 16:
            raise SystemExit(f"{src}:{i}: adv {adv} out of range")
        rows = []
        for r in range(HEIGHT):
            if i >= len(lines):
                raise SystemExit(f"{src}: glyph {ch!r} truncated")
            row = lines[i].rstrip("\n")
            i += 1
            if any(c not in ".#" for c in row):
                raise SystemExit(f"{src}:{i}: bad row {row!r} in glyph {ch!r}")
            if len(row) > adv:
                raise SystemExit(f"{src}:{i}: row wider than adv ({len(row)} > "
                                 f"{adv}) in glyph {ch!r}")
            bits = 0
            for x, c in enumerate(row):
                if c == "#":
                    bits |= 1 << (15 - x)
            rows.append(bits)
        if ch in glyphs:
            raise SystemExit(f"{src}: duplicate glyph {ch!r}")
        glyphs[ch] = (adv, rows)
    missing = [chr(c) for c in range(FIRST, FIRST + COUNT) if chr(c) not in glyphs]
    if missing:
        raise SystemExit(f"{src}: missing glyphs: {''.join(missing)!r}")
    return glyphs


def parse_icons(src: Path):
    """icons12.txt: "glyph <name> sjis <HEX>" + 12 rows -> [(code, name, rows)]
    sorted by code (the renderer searches them in order)"""
    icons = []
    lines = src.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 4 or parts[0] != "glyph" or parts[2] != "sjis":
            raise SystemExit(f"{src}:{i}: expected 'glyph <name> sjis <HEX>', got {line!r}")
        name, code = parts[1], int(parts[3], 16)
        if not (0xEF40 <= code <= 0xEFFC and (code & 0xFF) != 0x7F):
            raise SystemExit(f"{src}:{i}: {name}: code {code:04X} is outside the "
                             f"private block 0xEF40..0xEFFC")
        rows = []
        for r in range(HEIGHT):
            if i >= len(lines):
                raise SystemExit(f"{src}: icon {name} truncated")
            row = lines[i]
            i += 1
            if any(c not in ".#" for c in row) or len(row) > 13:
                raise SystemExit(f"{src}:{i}: bad row {row!r} in icon {name} "
                                 f"('.'/'#', at most 13 px)")
            bits = 0
            for x, c in enumerate(row):
                if c == "#":
                    bits |= 1 << (15 - x)
            rows.append(bits)
        if any(code == c for c, _, _ in icons) or any(name == n for _, n, _ in icons):
            raise SystemExit(f"{src}: duplicate icon {name} / {code:04X}")
        icons.append((code, name, rows))
    icons.sort()
    if not icons:
        raise SystemExit(f"{src}: no icons")
    # the renderer indexes the rows by code - PT_ICON_FIRST (patch_text.h)
    for k, (code, name, _) in enumerate(icons):
        if code != ICON_FIRST + k:
            raise SystemExit(f"{src}: icon {name} has code {code:04X}; the codes must "
                             f"run 0x{ICON_FIRST:04X}, 0x{ICON_FIRST + 1:04X}, ... "
                             f"without a gap")
    return icons


def check_icons(icons):
    """the string side (textcodec.ICONS) must name the same codes"""
    sys.path.insert(0, str(TOOLS_PATCH))
    import textcodec
    ours = {code: name for code, name, _ in icons}
    theirs = {int.from_bytes(b, "big"): n for n, (_, b) in textcodec.ICONS.items()}
    if ours != theirs:
        raise SystemExit(f"[fontgen] icons12.txt {ours} and textcodec.ICONS "
                         f"{theirs} disagree")


def emit_c(glyphs, out_c: Path, icons=()):
    L = []
    L.append("/* GENERATED by tools/patch/fontgen.py from tools/patch/font/latin12.txt")
    L.append("   -- do not edit.  Proportional Latin font for the English patch. */")
    L.append('#include "types.h"')
    L.append("")
    L.append("const u16 patch_font_rows[95][12] = {")
    for c in range(FIRST, FIRST + COUNT):
        adv, rows = glyphs[chr(c)]
        body = ", ".join(f"0x{r:04X}" for r in rows)
        label = "space" if c == 0x20 else ("backslash" if c == 0x5C else
                                           ("star-slash" if chr(c) in "*/" else chr(c)))
        L.append(f"    /* 0x{c:02X} {label} */ {{ {body} }},")
    L.append("};")
    L.append("")
    L.append("const u8 patch_font_adv[95] = {")
    advs = [str(glyphs[chr(c)][0]) for c in range(FIRST, FIRST + COUNT)]
    for k in range(0, COUNT, 19):
        L.append("    " + ", ".join(advs[k:k + 19]) + ",")
    L.append("};")
    L.append("")
    L.append("/* button icons (tools/patch/font/icons12.txt): code 0xEF40 + index */")
    L.append(f"const s32 patch_icon_count = {len(icons)};")
    L.append(f"const u16 patch_icon_rows[{len(icons)}][12] = {{")
    for code, name, rows in icons:
        body = ", ".join(f"0x{r:04X}" for r in rows)
        L.append(f"    /* 0x{code:04X} {name} */ {{ {body} }},")
    L.append("};")
    L.append("")
    out_c.write_text("\n".join(L) + "\n")


def emit_json(glyphs, out_json: Path, icons=()):
    out_json.write_text(json.dumps({
        "height": HEIGHT, "first": FIRST, "count": COUNT,
        "icons": {f"{c:04X}": n for c, n, _ in icons},
        "adv": {chr(c): glyphs[chr(c)][0] for c in range(FIRST, FIRST + COUNT)},
        "rows": {chr(c): glyphs[chr(c)][1] for c in range(FIRST, FIRST + COUNT)},
    }, indent=1) + "\n")


def text_width(glyphs, s: str) -> int:
    return sum(glyphs.get(ch, glyphs["?"])[0] for ch in s)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--icons", type=Path, default=DEFAULT_ICONS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--measure", help="print the pixel width of this string")
    args = ap.parse_args()
    glyphs = parse(args.src)
    if args.measure is not None:
        print(text_width(glyphs, args.measure))
        return
    avg = sum(g[0] for g in glyphs.values()) / len(glyphs)
    lower = sum(glyphs[c][0] for c in "etaoinshrdlu") / 12
    icons = parse_icons(args.icons)
    check_icons(icons)
    print(f"[fontgen] {len(glyphs)} glyphs, mean adv {avg:.2f} px, "
          f"common-lowercase adv {lower:.2f} px; {len(icons)} icons")
    if args.check:
        return
    args.out.mkdir(parents=True, exist_ok=True)
    emit_c(glyphs, args.out / "font_latin.c", icons)
    emit_json(glyphs, args.out / "font_latin.json", icons)
    print(f"[fontgen] wrote {args.out / 'font_latin.c'} and font_latin.json")


if __name__ == "__main__":
    main()
