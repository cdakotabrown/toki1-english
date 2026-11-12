#!/usr/bin/env python3
"""The name entry's field labels, units and Yes / No are English
(NAME_ENT.NBN cel_remap).

Reads the frame table of build/patch/files/CDROM/NAME_ENT/NAME_ENT.NBN the
way sprite_slot_disp draws it and checks that no frame still draws a
Japanese label cel (the (cel, width) pairs the manifest's rules name), that
the English word cells the frames now draw are on page 0 and hold ink, and
that every other cel is unchanged.  Negative control: the retail file read
the same way draws every one of the Japanese label cels.  Skipped without
the player's extracted disc or the patch build.

    python3 -m unittest tools/patch/test_name_ent_labels.py
"""
import json
import struct
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
MAN = ART / "NAME_ENT/manifest.json"
BUILT = ROOT / "build" / "patch" / "files" / "CDROM" / "NAME_ENT" / "NAME_ENT.NBN"
RETAIL = DECOMP / "assets" / "extracted_iso" / "CDROM" / "NAME_ENT" / "NAME_ENT.NBN"


def frames(data, cr):
    ram = int(cr["ram"], 16)
    table = int(cr["table"], 16) - ram
    out = []
    for f in range(int(cr["count"])):
        p = struct.unpack_from("<I", data, table + 4 * f)[0] - ram
        n = struct.unpack_from("<h", data, p)[0]
        out.append([struct.unpack_from("<7h", data, p + 8 + 14 * k) for k in range(n)])
    return out


class NameEntLabelsTest(unittest.TestCase):
    def setUp(self):
        if not RETAIL.exists() or not BUILT.exists():
            self.skipTest("needs the extracted disc and build_patched.py output")
        self.man = json.loads(MAN.read_text(encoding="utf-8"))
        self.cr = self.man["cel_remap"]
        self.japanese = {(int(r["cel"], 16), int(r["w"])) for r in self.cr["rules"]}

    def test_no_japanese_label_cel_is_drawn(self):
        # every place a retail frame draws a Japanese label cel now draws an
        # English word cell or nothing (a word cell may sit on the tile id a
        # Japanese glyph had: the words are drawn where the glyphs were)
        words = {(int(c["y"]) // 8) << 4 | (int(c["x"]) // 8): int(c["w"])
                 for c in self.man["cells"] if c["name"].startswith("word_")}
        left = []
        for f, (fb, fr) in enumerate(zip(frames(BUILT.read_bytes(), self.cr),
                                         frames(RETAIL.read_bytes(), self.cr))):
            at = {(c[0], c[1]): c for c in fb}
            for c in fr:
                if ((c[2] & 0xFFFF), c[5]) not in self.japanese:
                    continue
                b = at.get((c[0], c[1]))
                if b is not None and words.get(b[2] & 0xFFFF) != b[5]:
                    left.append((f, c[:2], b))
        self.assertEqual(left, [])

    def test_word_cells_have_ink_and_frames_keep_the_rest(self):
        built, retail = BUILT.read_bytes(), RETAIL.read_bytes()
        words = {}
        for c in self.man["cells"]:
            if c["name"].startswith("word_"):
                words[(int(c["y"]) // 8) << 4 | (int(c["x"]) // 8)] = c
        drawn = set()
        for fb, fr in zip(frames(built, self.cr), frames(retail, self.cr)):
            kept = [c for c in fr if ((c[2] & 0xFFFF), c[5]) not in self.japanese]
            others = [c for c in fb if (c[2] & 0xFFFF) not in words]
            # every cel that is not a label keeps its place (the month list's
            # and the units' cels are the only deletions, all label cels)
            self.assertTrue(set(others) <= set(kept))
            drawn |= {c[2] & 0xFFFF for c in fb if (c[2] & 0xFFFF) in words}
        self.assertEqual(drawn, set(words), "a word cell no frame draws")
        for tile, c in words.items():
            ink = 0
            for y in range(int(c["y"]), int(c["y"]) + 16):
                row = built[0x200 + y * 64:0x200 + y * 64 + 64]
                for x in range(int(c["x"]), int(c["x"]) + int(c["w"])):
                    v = row[x >> 1] >> 4 if x & 1 else row[x >> 1] & 15
                    ink += v == int(c["fg"])
            self.assertGreater(ink, 4, c["name"])

    def test_negative_control_retail_draws_every_japanese_label(self):
        seen = {((c[2] & 0xFFFF), c[5]) for cels in frames(RETAIL.read_bytes(), self.cr) for c in cels}
        self.assertEqual(self.japanese - seen, set())


if __name__ == "__main__":
    unittest.main()
