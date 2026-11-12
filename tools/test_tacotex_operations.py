#!/usr/bin/env python3
"""File-level tests of the Stardust Symphony EX OPERATIONS pages
(TACO/TACOTEX.NBN, src/patch/art/TACOTEX; strip map:
docs/translation/TACOTEX-OPERATIONS-STRIP-MAP.md):

* every manifest cell is a run of cels of TACOTEXO frame 1 or 2 that sit
  side by side on one screen row, in the cell's piece order (so an English
  line sliced across the pieces reads in order on screen);
* the injected pages draw exactly the cell PNGs there (ink = the fg_rows
  ramp index of its row, everything else 0), and no retail glyph pixel is
  left in any cel of the two frames except the kept Latin / button cels
  (L1 / L2, R1 / R2, circle, cross, triangle);
* no cell box touches a cel of frame 0 (the other TACOTEX art), and the
  English needs no squeeze;
* negative control: the retail pages fail the pixel check.

Needs the player's disc (assets/extracted_iso); skipped without.
"""
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
import nbn_inject  # noqa: E402

EXTRACTED = DECOMP / "assets" / "extracted_iso"
NBN = "CDROM/TACO/TACOTEX.NBN"
FRAMES_FILE = EXTRACTED / "CDROM/TACO/TACOTEXO.NBN"
MANIFEST = ART / "TACOTEX/manifest.json"
RAM = 0x801FA800                       # TACOTEXO's load address (taco_boot_init_load)
PAGE_TABLE, FRAME_TABLE = 0x268, 0x27C  # tpage_set_adr / img_set_adr - RAM
KEPT = {(0x8000, 0, 80), (0x8000, 56, 80),                    # L1 / L2, R1 / R2
        (0x0000, 32, 80), (0x0000, 56, 80), (0x0000, 80, 80)}  # circle, cross, triangle


def frames():
    """frame -> [(x, y, page offset, u, v, w, h)]"""
    o = FRAMES_FILE.read_bytes()
    pages = [a - 0x80180000 for a in struct.unpack_from("<5I", o, PAGE_TABLE)]
    out = {}
    for f, addr in enumerate(struct.unpack_from("<3I", o, FRAME_TABLE)):
        a = addr - RAM
        n = struct.unpack_from("<h", o, a)[0]
        cels = []
        for k in range(n):
            x, y, t, tp, attr, w, h = struct.unpack_from("<7h", o, a + 8 + 14 * k)
            cels.append((x, y, pages[(t >> 8) & 0xFF], (t & 15) * 8, ((t >> 4) & 15) * 8, w, h))
        out[f] = cels
    return out


def pieces(cell):
    if "pieces" in cell:
        return [(int(p["offset"], 16), int(p["x"]), int(p["y"]), int(p["w"])) for p in cell["pieces"]]
    return [(int(cell["offset"], 16), int(cell["x"]), int(cell["y"]), int(cell["w"]))]


def px(nbn, off, x, y):
    b = nbn[off + y * 64 + x // 2]
    return (b >> 4) if x & 1 else b & 15


@unittest.skipUnless((EXTRACTED / NBN).exists() and FRAMES_FILE.exists(), "needs the player's disc")
class TacotexOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.frames = frames()
        r = subprocess.run([sys.executable, str(TOOLS_PATCH / "nbn_inject.py"), str(MANIFEST)],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        cls.nbn = (ROOT / "build/patch/files" / NBN).read_bytes()
        cls.retail = (EXTRACTED / NBN).read_bytes()

    def test_cells_are_screen_rows_of_cels(self):
        for cell in self.man["cells"]:
            placed = []
            for off, u, v, w in pieces(cell):
                hits = [(f, c) for f in (1, 2) for c in self.frames[f]
                        if c[2:5] == (off, u, v) and c[5] >= w and c[6] == 16]
                self.assertEqual(len(hits), 1, (cell["name"], hex(off), u, v))
                placed.append((hits[0][0], hits[0][1][0], hits[0][1][1], w))
            for (f0, x0, y0, w0), (f1, x1, y1, _) in zip(placed, placed[1:]):
                self.assertEqual((f1, y1, x1), (f0, y0, x0 + w0), cell["name"])

    def drawn_mismatches(self, nbn):
        bad = []
        for cell in self.man["cells"]:
            png = Image.open(MANIFEST.parent / f"{cell['name']}.png").convert("RGBA")
            ramp = cell["fg_rows"]
            y_text = int(cell["valign"])
            sx = 0
            for off, u, v, w in pieces(cell):
                for y in range(16):
                    want_ink = min(max(y - y_text, 0), len(ramp) - 1)
                    for x in range(w):
                        ink = png.getpixel((sx + x, y))[3] >= 128
                        got = px(nbn, off, u + x, v + y)
                        if got != (ramp[want_ink] if ink else 0):
                            bad.append((cell["name"], sx + x, y, got))
                sx += w
        return bad

    def test_pages_draw_the_english(self):
        self.assertEqual(self.drawn_mismatches(self.nbn), [])

    def test_control_retail_fails(self):
        self.assertGreater(len(self.drawn_mismatches(self.retail)), 1000)

    def cell_area(self):
        area = set()
        for cell in self.man["cells"]:
            for off, u, v, w in pieces(cell):
                area |= {(off, u + i, v + j) for i in range(w) for j in range(16)}
        return area

    def test_no_japanese_left(self):
        area = self.cell_area()
        left = []
        for f in (1, 2):
            for x, y, off, u, v, w, h in self.frames[f]:
                if (off, u, v) in KEPT:
                    continue
                for j in range(h):
                    for i in range(w):
                        if (off, u + i, v + j) not in area and px(self.nbn, off, u + i, v + j):
                            left.append((f, hex(off), u + i, v + j))
        self.assertEqual(left, [])
        # the kept cels are untouched
        kept = [c for f in (1, 2) for c in self.frames[f] if c[2:5] in KEPT]
        self.assertEqual(len(kept), len(KEPT))
        for x, y, off, u, v, w, h in kept:
            for j in range(h):
                for i in range(w):
                    self.assertEqual(px(self.nbn, off, u + i, v + j), px(self.retail, off, u + i, v + j))

    def test_frame0_untouched(self):
        area = self.cell_area()
        for x, y, off, u, v, w, h in self.frames[0]:
            rect = {(off, u + i, v + j) for i in range(max(w, 1)) for j in range(h)}
            self.assertFalse(rect & area, (hex(off), u, v))
        # and every byte outside the cell boxes (the checksum aside) is retail
        for off in (0x2000, 0x4000):
            self.assertEqual(self.nbn[off:off + 0x2000], self.retail[off:off + 0x2000])

    def test_no_squeeze(self):
        for cell in self.man["cells"]:
            w = sum(p[3] for p in pieces(cell))
            tw = nbn_inject.text_layers(cell["text"], markup=False)[2] + (1 if cell.get("bold") else 0)
            self.assertLessEqual(tw, w, cell["name"])


if __name__ == "__main__":
    unittest.main()
