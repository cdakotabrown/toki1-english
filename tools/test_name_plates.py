#!/usr/bin/env python3
"""File-level tests of the sports-day surname plates (VISUAL-SWEEP.md 3.1.4):
TAIIKU/KARI.BIN's seven 32x16 plates (page at file offset 0) and the six
mirrored copies in TAIIKU/TAMA.BIN (pages 14 / 15).

* every plate box of the injected file holds the English of its cells and
  nothing else: ink (index 1) exactly where the cell PNGs are opaque, the
  plate colour (47) everywhere else; TAMA's are the mirror image of
  KARI's;
* the English is the surname as STYLE-GUIDE.md spells it (one line, or the
  two halves on the plate's two 8-px rows), in the tiny_caps face;
* outside the plate boxes the touched pages are the retail bytes, and the
  half-overwritten 紐緒 plate of TAMA.BIN is left as it is;
* negative control: the retail plates fail the same checks.

Needs the player's disc (assets/extracted_iso); skipped without.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
EXTRACTED = DECOMP / "assets" / "extracted_iso"
OUT = ROOT / "build" / "patch" / "files"
INK, PLATE = 1, 47

# surname plates: key -> (kanji, English surname)
SURNAMES = {
    "fujisaki": ("藤崎", "FUJISAKI"), "himoo": ("紐緒", "HIMOO"),
    "katagiri": ("片桐", "KATAGIRI"), "kiyokawa": ("清川", "KIYOKAWA"),
    "koshiki": ("古式", "KOSHIKI"), "kagami": ("鏡", "KAGAMI"),
    "kisaragi": ("如月", "KISARAGI"),
}
FILES = {"KARI": "CDROM/TAIIKU/KARI.BIN", "TAMA": "CDROM/TAIIKU/TAMA.BIN"}
PAGES = {"KARI": [0x0], "TAMA": [0x3A000, 0x3E000]}
HIMOO_HALF = (0x3A000, 16, 112)       # TAMA: 紐 alone (緒's half holds other art)


def px(data, off, x, y):
    return data[off + y * 128 + x]


def plates(man):
    """key -> (offset, x, y, [cells]) of the 32x16 plate the cells cover"""
    out = {}
    for c in man["cells"]:
        if "plate" not in c:
            continue
        off = int(c["offset"], 16)
        o, x, y, cells = out.setdefault(c["plate"], (off, int(c["x"]), int(c["y"]), []))
        out[c["plate"]] = (o, x, min(y, int(c["y"])), cells + [c])
    return out


def expected_ink(name, key, cells):
    """(x, y) inside the plate -> True where our PNGs put ink"""
    y0 = min(int(c["y"]) for c in cells)
    ink = set()
    for c in cells:
        im = Image.open(ART / name / f"{c['name']}.png").convert("RGBA")
        for yy in range(int(c["h"])):
            for xx in range(int(c["w"])):
                if im.getpixel((xx, yy))[3] >= 128:
                    ink.add((xx, int(c["y"]) - y0 + yy))
    return ink


@unittest.skipUnless(all((EXTRACTED / f).exists() for f in FILES.values()), "needs the player's disc")
class NamePlates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man = {k: json.loads((ART / k / "manifest.json").read_text(encoding="utf-8")) for k in FILES}
        r = subprocess.run([sys.executable, str(TOOLS_PATCH / "nbn_inject.py")]
                           + [str(ART / k / "manifest.json") for k in FILES],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        cls.out = {k: (OUT / f).read_bytes() for k, f in FILES.items()}
        cls.retail = {k: (EXTRACTED / f).read_bytes() for k, f in FILES.items()}
        cls.plates = {k: plates(m) for k, m in cls.man.items()}

    def test_plate_sets(self):
        self.assertEqual(set(self.plates["KARI"]), set(SURNAMES))
        self.assertEqual(set(self.plates["TAMA"]), set(SURNAMES) - {"himoo"})
        for k, ps in self.plates.items():
            for key, (off, x, y, cells) in ps.items():
                self.assertEqual({c["jp"] for c in cells}, {SURNAMES[key][0]}, key)
                self.assertEqual("".join(c["text"] for c in sorted(cells, key=lambda c: c["y"])),
                                 SURNAMES[key][1], key)
                self.assertTrue(all(c.get("pixel_font") == "tiny_caps" for c in cells))
                self.assertEqual(all(c.get("mirror") for c in cells), k == "TAMA", key)
                self.assertEqual(sum(int(c["h"]) for c in cells), 16, key)
                self.assertTrue(all(int(c["w"]) == 32 and int(c["x"]) == x for c in cells), key)

    def plate_errors(self, k, data):
        """pixels of the plate boxes that are not our English"""
        bad = []
        for key, (off, x0, y0, cells) in self.plates[k].items():
            ink = expected_ink(k, key, cells)
            for y in range(16):
                for x in range(32):
                    want = INK if (x, y) in ink else PLATE
                    if px(data, off, x0 + x, y0 + y) != want:
                        bad.append((k, key, x, y))
        return bad

    def test_plates_hold_the_english(self):
        for k in FILES:
            self.assertEqual(self.plate_errors(k, self.out[k]), [], k)

    def test_control_retail_fails(self):
        for k in FILES:
            self.assertGreater(len(self.plate_errors(k, self.retail[k])), 100, k)

    def test_retail_boxes_are_plates(self):
        """the boxes are exactly retail plates: only ink and plate colour, kanji ink inside"""
        for k in FILES:
            for key, (off, x0, y0, cells) in self.plates[k].items():
                vals = [px(self.retail[k], off, x0 + x, y0 + y) for y in range(16) for x in range(32)]
                self.assertEqual(set(vals), {INK, PLATE}, (k, key))
                self.assertGreater(vals.count(INK), 25, (k, key))

    def test_tama_is_kari_mirrored(self):
        for key, (off, x0, y0, _) in self.plates["TAMA"].items():
            koff, kx, ky, _ = self.plates["KARI"][key]
            for y in range(16):
                row = [px(self.out["TAMA"], off, x0 + x, y0 + y) for x in range(32)]
                krow = [px(self.out["KARI"], koff, kx + x, ky + y) for x in range(32)]
                self.assertEqual(row, krow[::-1], (key, y))

    def test_rest_of_the_pages_is_retail(self):
        for k in FILES:
            inside = set()
            for off, x0, y0, _ in self.plates[k].values():
                inside |= {off + (y0 + y) * 128 + x0 + x for y in range(16) for x in range(32)}
            for page in PAGES[k]:
                for o in range(page, page + 0x4000):
                    if o not in inside:
                        self.assertEqual(self.out[k][o], self.retail[k][o], (k, hex(o)))
        off, x0, y0 = HIMOO_HALF
        for y in range(16):
            for x in range(32):
                self.assertEqual(px(self.out["TAMA"], off, x0 + x - 16, y0 + y),
                                 px(self.retail["TAMA"], off, x0 + x - 16, y0 + y))


if __name__ == "__main__":
    unittest.main()
