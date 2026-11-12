#!/usr/bin/env python3
"""The title Options sub-lists (FUKUTEST/OPTION.NBN sprite frames) are
English in the patch build (docs/translation/VISUAL-SWEEP.md).

Reads the frames back out of build/patch/files/CDROM/FUKUTEST/OPTION.NBN
(what build_patched.py / nbn_inject.py wrote) exactly as sprite_slot_disp
draws them, and checks that every rebuilt frame draws only our Latin glyph
cells, in the order of its English text.  Negative control: the retail file
read the same way fails (its frames draw the Japanese glyph cells).
Skipped without the player's extracted disc or the patch build.

    python3 -m unittest tools/patch/test_option_nbn.py
"""
import json
import struct
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
MAN = ART / "OPTION/manifest.json"
BUILT = ROOT / "build" / "patch" / "files" / "CDROM" / "FUKUTEST" / "OPTION.NBN"
RETAIL = DECOMP / "assets" / "extracted_iso" / "CDROM" / "FUKUTEST" / "OPTION.NBN"


def frame_texts(data, man):
    """{frame: text read back through the manifest's glyph cells, or None
    when a cel is not one of them}"""
    sf = man["sprite_frames"]
    ram = int(sf["ram"], 16)
    u32 = lambda a: struct.unpack_from("<I", data, a - ram)[0]      # noqa: E731
    pages = [u32(int(sf["pages"], 16) + 4 * i) for i in range(int(sf["page_count"]))]
    glyph_of = {}
    for c in man["cells"]:
        if "glyph" not in c:
            continue
        page = pages.index(ram + int(c["offset"], 16))
        glyph_of[page << 8 | (c["y"] // 8) << 4 | (c["x"] // 8)] = c["glyph"]
    out = {}
    keep = set(sf["keep"])
    for f in range(int(sf["count"])):
        if f in keep:
            continue
        p = u32(int(sf["table"], 16) + 4 * f) - ram
        n = struct.unpack_from("<h", data, p)[0]
        cels = sorted(struct.unpack_from("<7h", data, p + 8 + 14 * k) for k in range(n))
        chars = [glyph_of.get(c[2] & 0xFFFF) for c in cels]
        out[f] = None if None in chars or not chars else "".join(chars)
    return out


class OptionNbnTest(unittest.TestCase):
    def setUp(self):
        if not RETAIL.exists() or not BUILT.exists():
            self.skipTest("needs the extracted disc and build_patched.py output")
        self.man = json.loads(MAN.read_text(encoding="utf-8"))
        self.want = {fr["frame"]: "".join(s["text"] for s in fr["segs"]).replace(" ", "")
                     for fr in self.man["sprite_frames"]["frames"]}

    def test_every_rebuilt_frame_reads_its_english(self):
        got = frame_texts(BUILT.read_bytes(), self.man)
        self.assertEqual(set(got), set(self.want))
        bad = {f: (got[f], self.want[f]) for f in got if got[f] != self.want[f]}
        self.assertEqual(bad, {})
        # the lists the player opens first (text speed, voice): spot checks
        self.assertEqual(got[14], "Slow")
        self.assertEqual(got[49], "×buttonskips")

    def test_negative_control_retail_frames_are_not_english(self):
        # the same cel ids address Japanese glyphs in the retail page, so
        # some retail cels hit a Latin cell id by position; no frame reads
        # as its English
        got = frame_texts(RETAIL.read_bytes(), self.man)
        same = [f for f in got if got[f] == self.want[f]]
        self.assertEqual(same, [])

    def test_kept_frames_are_byte_identical(self):
        sf = self.man["sprite_frames"]
        ram = int(sf["ram"], 16)
        built, retail = BUILT.read_bytes(), RETAIL.read_bytes()
        for f in sf["keep"]:
            def blob(d):
                p = struct.unpack_from("<I", d, int(sf["table"], 16) + 4 * f - ram)[0] - ram
                n = struct.unpack_from("<h", d, p)[0]
                return d[p:p + 8 + 14 * n]
            self.assertEqual(blob(built), blob(retail), f"kept frame {f}")


if __name__ == "__main__":
    unittest.main()
