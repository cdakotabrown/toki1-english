#!/usr/bin/env python3
"""File-level tests of the Memorial Spot genre tags (VISUAL-SWEEP.md 3.2):

* config/patch/english.json carries exactly the pokes mag_genre_tags.py
  generates from the manifest and the retail exe;
* with the pokes applied, frames 134..143 of basyo_init_tbl1 draw the
  English word strips (one cel per strip piece), and the injected
  MAINROM.NBN page 12 holds those words (ink = index 9, nothing else);
* the strips touch no pixel any other frame of the table draws, and no
  retail kana pixel survives in the old tag area;
* negative control: the retail records and page fail the same checks.

Needs the player's disc (disks/SLPS_000.65, assets/extracted_iso); skipped
without.
"""
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
import mag_genre_tags as mg  # noqa: E402

EXTRACTED = DECOMP / "assets" / "extracted_iso"
NBN = "CDROM/FUKUTEST/MAINROM.NBN"


def apply(exe, pokes):
    exe = bytearray(exe)
    for p in pokes:
        o = mg.fo(int(p["addr"], 16))
        data = struct.pack("<H", p["u16"]) if "u16" in p else bytes.fromhex(p["bytes"])
        exe[o:o + len(data)] = data
    return bytes(exe)


def px(nbn, x, y, page=12):
    b = nbn[page * 0x2000 + y * 64 + x // 2]
    return (b >> 4) if x & 1 else b & 15


@unittest.skipUnless(mg.EXE.exists() and (EXTRACTED / NBN).exists(), "needs the player's disc")
class GenreTags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retail = mg.EXE.read_bytes()
        cls.man = json.loads(mg.MANIFEST.read_text(encoding="utf-8"))
        cls.cells = {int(c["frame"]): c for c in cls.man["cells"]
                     if c["name"].startswith("genre_") and "frame" in c}
        r = subprocess.run([sys.executable, str(TOOLS_PATCH / "nbn_inject.py"), str(mg.MANIFEST)],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        cls.nbn = (ROOT / "build/patch/files" / NBN).read_bytes()
        cls.nbn_retail = (EXTRACTED / NBN).read_bytes()

    def test_profile_pokes_are_generated(self):
        prof = json.loads(mg.PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(mg.profile_pokes(prof), mg.generate(self.retail, self.man))

    def words_drawn(self, exe, nbn):
        """frame -> the word its cels show, read back as (cel rect ink) per piece"""
        bad = []
        for f in mg.FRAMES:
            c = self.cells[f]
            _, cels = mg.record(exe, f)
            want = mg.pieces(c)
            if len(cels) != len(want):
                bad.append((f, "cel count", len(cels)))
                continue
            from PIL import Image
            png = Image.open(mg.MANIFEST.parent / f"{c['name']}.png").convert("RGBA")
            sx = 0
            for (ox, oy, cel, tp, attr, w, h), (page, x, y, pw) in zip(cels, want):
                if (cel & 0xFFFF) != mg.tile(page, x, y) or w != pw or h != 8:
                    bad.append((f, "cel", hex(cel & 0xFFFF), w, h))
                    continue
                for yy in range(8):
                    for xx in range(pw):
                        ink = png.getpixel((sx + xx, yy))[3] >= 128
                        v = px(nbn, x + xx, y + yy)
                        if (v == 9) != ink or (not ink and v != 0):
                            bad.append((f, "pixel", x + xx, y + yy, v))
                sx += pw
        return bad

    def test_frames_draw_the_english_words(self):
        exe = apply(self.retail, mg.generate(self.retail, self.man))
        self.assertEqual(self.words_drawn(exe, self.nbn), [])
        # the other records are untouched
        for f in range(174):
            if f not in mg.FRAMES:
                self.assertEqual(mg.record(exe, f), mg.record(self.retail, f))

    def test_control_retail_fails(self):
        self.assertGreater(len(self.words_drawn(self.retail, self.nbn_retail)), 10)

    def other_frames_area(self):
        area = set()
        for f in range(174):
            if f in mg.FRAMES:
                continue
            for ox, oy, cel, tp, attr, w, h in mg.record(self.retail, f)[1]:
                cel &= 0xFFFF
                if cel >> 8 == mg.CEL_PAGE:
                    x0, y0 = (cel & 15) * 8, ((cel >> 4) & 15) * 8
                    area |= {(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)}
        return area

    def test_strips_overlap_no_other_frame(self):
        other = self.other_frames_area()
        for c in self.cells.values():
            for page, x, y, w in mg.pieces(c):
                rect = {(x + i, y + j) for i in range(w) for j in range(8)}
                self.assertFalse(rect & other, c["name"])
        # and outside the old kana area the strips use only blank retail page space
        kana = set()
        for f in mg.FRAMES:
            for ox, oy, cel, tp, attr, w, h in mg.record(self.retail, f)[1]:
                x0, y0 = (cel & 15) * 8, ((cel >> 4) & 15) * 8
                kana |= {(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)}
        for c in self.cells.values():
            for page, x, y, w in mg.pieces(c):
                for j in range(8):
                    for i in range(w):
                        if (x + i, y + j) not in kana:
                            self.assertEqual(px(self.nbn_retail, x + i, y + j), 0, (c["name"], x + i, y + j))

    def kana_left(self, nbn):
        """retail kana pixels still in the old tag area and not part of an English strip"""
        strips = set()
        for c in self.cells.values():
            for page, x, y, w in mg.pieces(c):
                strips |= {(x + i, y + j) for i in range(w) for j in range(8)}
        left = 0
        for f in mg.FRAMES:
            for ox, oy, cel, tp, attr, w, h in mg.record(self.retail, f)[1]:
                x0, y0 = (cel & 15) * 8, ((cel >> 4) & 15) * 8
                for y in range(y0, y0 + h):
                    for x in range(x0, x0 + w):
                        if (x, y) not in strips and px(nbn, x, y) == 9 and px(self.nbn_retail, x, y) == 9:
                            left += 1
        return left

    def test_no_kana_left(self):
        self.assertEqual(self.kana_left(self.nbn), 0)
        self.assertGreater(self.kana_left(self.nbn_retail), 0)

    def test_records_only_shrink(self):
        for f in mg.FRAMES:
            self.assertLessEqual(len(mg.pieces(self.cells[f])), len(mg.record(self.retail, f)[1]))


if __name__ == "__main__":
    unittest.main()
