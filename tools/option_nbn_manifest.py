#!/usr/bin/env python3
"""option_nbn_manifest.py - writes src/patch/art/OPTION/manifest.json.

The title Options screen (OPTION.EXN) draws the entries of its sub-lists
(text speed, icon mode, mouse, menu mode, cursor speed, voice, extras and
the extras' voice-cast / heroine lists) as SPRITE FRAMES of
FUKUTEST/OPTION.NBN, not as strings, so the drawn-text log never sees them:

  * option_init1 loads the file to 0x801B0000 and points every Rec68 slot
    of D_80128B30 at the frame table 0x801C32D8 (slot+12) and the page
    table 0x801C32C8 (slot+52: four 8-bpp 128x128 page buffers at
    0x801B0200 / 0x801BC200 / 0x801C3CF0 / 0x801B8200);
  * a frame is the sprite_slot_disp cel list (`s16 count, w, h, pad` +
    count x `s16 ox, oy, cel, tp, attr, w, h`), cel = page << 8 | tile of
    8-px tiles, the glyphs are 16x16 cells of the retail 12-px font with a
    vertical ramp (indices 55..49) and a drop shadow (226);
  * frames come in pairs, the odd one normal (tp 0x2000), the even one the
    highlighted copy (tp 0x2100): option_k_speed_init picks 14/16/18.

English: a Latin glyph set (8x16 cells, our 12-px font with the same ramp
and shadow) replaces the Japanese glyphs on page 1 below its first row
(rows 16..127; row 0 holds the highlight bar frame 10 draws), and frames
11..118 and 122..129 are rebuilt from the English below, one cel per
letter (nbn_inject.py apply_sprite_frames, `"tp": "retail"` keeps each
frame's pair colour).  Frames 0..10 (panel borders, the bar) and 119..121
(the pointer art) are kept.  The lists go into the retail list area
0x801C0200..0x801C32C8 and, as the English needs more cels, into page
buffer 2 (0x801C3CF0, 16 KB), whose glyphs only rebuilt frames drew.

English is DRAFT, consistent with tools/patch/ui_strings.py (the in-game
system settings) and translation/localization/GLOSSARY.csv (names, given
name first).

    python3 tools/patch/option_nbn_manifest.py      # writes the manifest
    python3 tools/patch/nbn_inject.py --render src/patch/art/OPTION/manifest.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
OUT = ART / "OPTION/manifest.json"

# frame (odd = normal; frame + 1 is the highlighted copy): (Japanese, English).
# The Japanese is a reviewer cue only (the art's "jp" field); a label of
# six characters or more is left empty: the public tree carries no retail
# text (D4(a)), and the frame is on the player's disc.
PAIRS = {
    11: ("超遅い", "Slowest"),
    13: ("遅い", "Slow"),
    15: ("普通", "Normal"),
    17: ("速い", "Fast"),
    19: ("超速い", "Fastest"),
    21: ("ＴＹＰＥ－Ａ", "TYPE-A"),
    23: ("ＴＹＰＥ－Ｂ", "TYPE-B"),
    25: ("フリー", "Free"),
    27: ("決定ボタン", "OK button"),
    29: ("", "Click mode"),
    31: ("", "Click speed"),
    33: ("", "Right button"),
    35: ("", "Left button"),
    37: ("", "Single click"),
    39: ("", "Double click"),
    41: ("初期状態", "Default"),
    43: ("変更", "Change"),
    45: ("ＯＮ", "On"),
    47: ("ＯＦＦ", "Off"),
    49: ("", "× button skips"),
    51: ("サブゲーム", "Mini-games"),
    53: ("", "Free talk"),
    55: ("", "Ending"),
    57: ("", "Album mode"),
    59: ("", "TwinBee Time Attack"),
    61: ("", "Stardust Symphony EX"),
    # the voice cast (free talk): actress (heroine)
    63: ("", "Mami Kingetsu (Fujisaki)"),
    65: ("", "Akiko Sekine (Kisaragi)"),
    67: ("", "Tomoko Naka (Himoo)"),
    69: ("", "Masayo Kawaguchi (Katagiri)"),
    71: ("", "Sachiko Sugawara (Nijino)"),
    73: ("", "Ayako Kurosaki (Koshiki)"),
    75: ("", "Ayako Sasaki (Kiyokawa)"),
    77: ("", "Rei Igarashi (Kagami)"),
    79: ("", "Yoko Teppozuka (Asahina)"),
    81: ("", "Mikiko Kurihara (Mikihara)"),
    83: ("", "Kurin Yoshiki (Saotome)"),
    85: ("", "Shiho Kikuchi (Tatebayashi)"),
    87: ("", "Narumi Tsunoda (Ijuin)"),
    89: ("", "Yuji Ueda (Yoshio)"),
    # the heroines (ending)
    91: ("藤崎　詩織", "Shiori Fujisaki"),
    93: ("如月　未緒", "Mio Kisaragi"),
    95: ("紐緒　結奈", "Yuina Himoo"),
    97: ("片桐　彩子", "Ayako Katagiri"),
    99: ("虹野　沙希", "Saki Nijino"),
    101: ("", "Yukari Koshiki"),
    103: ("清川　望", "Nozomi Kiyokawa"),
    105: ("鏡　魅羅", "Mira Kagami"),
    107: ("", "Yuko Asahina"),
    109: ("美樹原　愛", "Megumi Mikihara"),
    111: ("", "Yumi Saotome"),
    113: ("館林　見晴", "Miharu Tatebayashi"),
    115: ("", "Rei Ijuin"),
    117: ("", "Pad end"),
    122: ("", "Mouse-like"),
    124: ("パッドＡ", "Pad A"),
    126: ("パッドＢ", "Pad B"),
    128: ("", "Mouse-like + Pad A"),
}
KEEP = list(range(0, 11)) + [119, 120, 121]

# the retail ramp is 55..49 (7 levels); 6 keep a cell PNG within the
# lettering audit's 8 colours with the shadow and transparency
FG_ROWS = [55, 55, 55, 55, 55, 53, 52, 51, 50, 49, 49, 49]
SHADOW = 226
PAGE1 = "0xC200"            # 0x801BC200 - 0x801B0000


def glyph_cells(chars, adv):
    """8x16 cells (16x16 for a glyph wider than 7 px) left to right from
    page 1 row 16, wrapping at 128"""
    cells, x, y = [], 0, 16
    for ch in chars:
        w = 8 if adv[ch] <= 8 else 16
        if x + w > 128:
            x, y = 0, y + 16
        if y + 16 > 128:
            raise SystemExit("option_nbn_manifest: the glyph set does not fit page 1")
        cells.append({
            "name": "g%04x" % ord(ch), "glyph": ch, "offset": PAGE1,
            "x": x, "y": y, "w": w, "h": 16, "text": ch, "jp": "",
            "fg": FG_ROWS[4], "fg_rows": FG_ROWS, "shadow": SHADOW,
            "erase": [], "bg": 0, "align": "left", "valign": 0,
        })
        x += w
    return cells


def main():
    sys.path.insert(0, str(TOOLS_PATCH))
    import nbn_inject
    fnt = nbn_inject.font()
    chars = sorted({c for _, en in PAIRS.values() for c in en if c != " "})
    adv = {c: fnt[c][0] for c in chars}
    frames = []
    for f, (jp, en) in sorted(PAIRS.items()):
        for k in (f, f + 1):
            frames.append({"frame": k, "segs": [{"ox": 0, "oy": 0, "jp": jp, "text": en}]})
    man = {
        "file": "CDROM/FUKUTEST/OPTION.NBN",
        "note": __doc__.split("\n\n")[1].strip().replace("\n", " "),
        "bpp": 8,
        "page_w": 128,
        "page_h": 128,
        "page_bytes": 16384,
        "clut": {"source": "file:0x134F0", "entries": 256},
        "clear": [{"offset": "0xCA00", "bytes": 112 * 128}],
        "sprite_frames": {
            "id_prefix": "FUKUTEST/OPTION.NBN",
            "editor_sheet": "translation/localization/sheets/FUKUTEST/OPTION.NBN.csv",
            "status": "draft",
            "ram": "0x801B0000",
            "pages": "0x801C32C8",
            "page_count": 4,
            "table": "0x801C32D8",
            "count": 130,
            "keep": KEEP,
            # the retail list area, then page buffer 2 (0x801C3CF0: the
            # debug-name glyphs only frames 61..116 drew, all rebuilt)
            "regions": [["0x801C0200", "0x801C32C8"], ["0x801C3CF0", "0x801C7CF0"]],
            "letter_gap": 1,
            "glyph_dy": 0,
            "tp": "retail",
            "frames": frames,
        },
        "cells": glyph_cells(chars, adv),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"option_nbn_manifest: {len(frames)} frames, {len(man['cells'])} glyph cells -> "
          f"{OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
