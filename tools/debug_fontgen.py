#!/usr/bin/env python3
"""debug_fontgen.py - the font image Konami's debug text renderers expect.

The retail executable keeps three debug text renderers (_debug_string_show,
_debug_number_show, debug_hex_show) and a loader, debug_font_load, that
uploads a 64x32-WORD image from RAM 0x801F0020 to VRAM (704,480) when the
debug flag D_800B9710 is set.  Nothing on the retail disc ever puts a font at
0x801F0020 (it is the top of RAM, under the stack), so the shipped debug
text would draw whatever bytes happen to be there.  The debug patch profile
hooks debug_font_load and uploads THIS image instead.

Layout (derived from the renderers; texture page = GetTPage(0 /*4bpp*/, 0,
704, 256), so the image's texel row r is v = 224 + r, and u is a 4bpp texel
column of the 256-texel-wide page):

  rows  4..11  8x8 cells, v = 0xE4: _debug_string_show for bytes with bit 5
               clear (0x40..0x5F): u = (c & 0x1F) * 8 - 8  -> 'A' at 0 ...
               'Z' at 200, '[' 208, '\\' 216, ']' 224, '^' 232, '_' 240,
               '@' at 248 (wraps)
  rows 12..19  8x8 cells, v = 0xEC: _debug_number_show / debug_hex_show
               digits from the UV table D_800BA284: '0'..'9' at u = 0..72,
               and the minus sign at u = 0x50
  rows 20..31  6x12 cells, v = 0xF4: _debug_string_show for bytes with bit 5
               SET (0x20..0x3F and 0x60..0x7F) at u = (c & 0x1F) * 8 - 8, and
               the hex digits A..F of debug_hex_show (8x8 at u = 0..40, i.e.
               the cells of 'a'..'f').  Konami's own labels are lowercase, so
               the row holds a..z (small caps) and ; < = > ?; digits and
               punctuation inside STRINGS alias those cells and are not
               renderable (retail prints numbers with _debug_number_show).

Pixels are CLUT index 1; index 0 is transparent.  The renderers pick the
CLUT with GetClut(256 + (pal & 8) * 2 [strings] or * 4 [numbers], 504 +
(pal & 7)): the system palette block the game keeps in VRAM rows 504..511
has a bright colour in entry 1 of every x=256 row (pal 0..7), so the patch
draws its menu with pal 0..7.

Usage:
    python3 tools/patch/debug_fontgen.py --out build/patch/debug/gen
Writes <out>/debug_font.c (const u8 dbg_font_image[4096]) and
<out>/debug_font.png (a preview, when Pillow is available).
"""
import argparse
from pathlib import Path

W, H = 256, 32          # texels
GLYPH_ROWS = 8

# 5x7 glyphs (row strings; '#' = pixel), drawn into an 8x8 cell at (1,0)
GLYPHS = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11100", "10010", "10001", "10001", "10001", "10010", "11100"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "10001", "11001", "10101", "10011", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "*": ["00000", "10101", "01110", "11111", "01110", "10101", "00000"],
    "<": ["00010", "00100", "01000", "10000", "01000", "00100", "00010"],
    ">": ["01000", "00100", "00010", "00001", "00010", "00100", "01000"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    "[": ["01110", "01000", "01000", "01000", "01000", "01000", "01110"],
    "]": ["01110", "00010", "00010", "00010", "00010", "00010", "01110"],
    "_": ["00000", "00000", "00000", "00000", "00000", "00000", "11111"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "#": ["01010", "01010", "11111", "01010", "11111", "01010", "01010"],
    "@": ["01110", "10001", "10111", "10101", "10111", "10000", "01110"],
    ";": ["00000", "01100", "01100", "00000", "01100", "00100", "01000"],
}


def put(img, u0, v0, glyph, w=8):
    """draw a 5x7 glyph into the cell at (u0, v0); w<8 = narrow 6-wide cell"""
    x_off = 1 if w == 8 else 0
    for r, row in enumerate(glyph):
        for c, bit in enumerate(row):
            if bit == "1":
                x = (u0 + x_off + c) % W
                y = v0 + r
                if 0 <= y < H:
                    img[y][x] = 1


def build():
    img = [[0] * W for _ in range(H)]
    # row 4: 0x40..0x5F, 8x8
    for code in range(0x40, 0x60):
        ch = chr(code)
        if ch in GLYPHS:
            put(img, ((code & 0x1F) * 8 - 8) % W, 4, GLYPHS[ch])
    # row 12: digits for the number renderers (+ minus at 0x50)
    for d in range(10):
        put(img, d * 8, 12, GLYPHS[str(d)])
    put(img, 0x50, 12, GLYPHS["-"])
    # rows 20..31: the narrow 6x12 cells shared by 0x20..0x3F and 0x60..0x7F.
    # Konami's labels are lowercase ("game_mode", "tokimeki", "k_tel"), and
    # debug_hex_show's A..F come from cells 1..6 (= a..f), so the row holds
    # a..z as small caps in cells 1..26 and ; < = > ? in cells 27..31; cell 0
    # (space) stays blank.  Digits and most punctuation therefore do NOT
    # render inside strings (they alias p..y / k..o): numbers go through
    # _debug_number_show, as retail does.
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        put(img, (i + 1) * 8 - 8, 20, GLYPHS[ch], w=6)
    for code in range(0x3B, 0x40):
        ch = chr(code)
        if ch in GLYPHS:
            put(img, ((code & 0x1F) * 8 - 8) % W, 20, GLYPHS[ch], w=6)
    return img


def to_4bpp(img):
    out = bytearray()
    for y in range(H):
        for x in range(0, W, 2):
            out.append((img[y][x] & 0xF) | ((img[y][x + 1] & 0xF) << 4))
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    img = build()
    data = to_4bpp(img)
    assert len(data) == 64 * 32 * 2
    lines = ["/* generated by tools/patch/debug_fontgen.py -- do not edit */",
             "#include \"types.h\"",
             "",
             "/* 4bpp 256x32 texels = 64x32 VRAM words, uploaded to (704,480) by",
             "   dbg_font_load (the debug_font_load hook); see the generator. */",
             "const u8 dbg_font_image[4096] = {"]
    for i in range(0, len(data), 16):
        lines.append("    " + ", ".join(f"0x{b:02X}" for b in data[i:i + 16]) + ",")
    lines.append("};")
    (out / "debug_font.c").write_text("\n".join(lines) + "\n")
    try:
        from PIL import Image
        im = Image.new("L", (W, H))
        im.putdata([255 if img[y][x] else 0 for y in range(H) for x in range(W)])
        im.resize((W * 3, H * 3)).save(out / "debug_font.png")
    except ImportError:
        pass
    print(f"[debug_fontgen] {out / 'debug_font.c'} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
