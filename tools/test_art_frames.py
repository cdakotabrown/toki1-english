#!/usr/bin/env python3
"""File-level tests of the 2026-11-03 art (docs/translation/VISUAL-SWEEP.md 3.1.2):

* KARI.BIN: the borrowing race's 失格 stamp is our DISQUALIFIED (the stamp
  is drawn translucent, so the screen-picture gate cannot match its
  colours; this test checks the bytes instead);
* B_BUNGEI.BIN: the five speech-topic boards are laid out from the English
  word cells (nbn_inject frame_layout + copy_rects), every other frame is
  kept;
* MAINROM.NBN: no magazine cell leaves a retail glyph index in its box;
* negative controls: the retail files fail the same checks, and
  frame_layout / copy_rects refuse a list longer than the record and a
  destination that is not unused page space.

Needs the player's extracted files (assets/extracted_iso); skipped without.
"""
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
EXTRACTED = DECOMP / "assets" / "extracted_iso"
OUT = ROOT / "build" / "patch" / "files"


def manifest(name):
    return json.loads((ART / name / "manifest.json").read_text(encoding="utf-8"))


def inject(name):
    r = subprocess.run([sys.executable, str(TOOLS_PATCH / "nbn_inject.py"),
                        str(ART / name / "manifest.json")],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return (OUT / manifest(name)["file"]).read_bytes()


@unittest.skipUnless((EXTRACTED / "CDROM/TAIIKU/KARI.BIN").exists(), "needs the extracted disc")
class ArtFrames(unittest.TestCase):
    def kari_matches_png(self, data):
        from PIL import Image
        m = manifest("KARI")
        c = m["cells"][0]
        png = Image.open(ART / "KARI/stamp_dq.png").convert("RGBA")
        off = int(c["offset"], 16)
        er = set(c["erase"])
        bad = 0
        for y in range(c["h"]):
            for x in range(c["w"]):
                v = data[off + (c["y"] + y) * 128 + c["x"] + x]
                ink = png.getpixel((x, y))[3] >= 128
                bad += (v in er) != ink
        return bad

    def test_kari_stamp_is_english(self):
        self.assertEqual(self.kari_matches_png(inject("KARI")), 0)
        retail = (EXTRACTED / "CDROM/TAIIKU/KARI.BIN").read_bytes()
        self.assertGreater(self.kari_matches_png(retail), 500, "control: the retail 失格 is not DISQUALIFIED")

    def frames(self, data, fl):
        ram, table = int(fl["ram"], 16), int(fl["table"], 16)
        out = {}
        for f in range(196):
            a = struct.unpack_from("<I", data, table - ram + 4 * f)[0]
            p = a - ram
            n = struct.unpack_from("<h", data, p)[0]
            out[f] = [struct.unpack_from("<7h", data, p + 8 + 14 * k) for k in range(n)]
        return out

    def test_speech_topic_boards(self):
        m = manifest("B_BUNGEI")
        fl = m["frame_layout"]
        cells = {c["name"]: c for c in m["cells"]}
        data = inject("B_BUNGEI")
        retail = (EXTRACTED / m["file"]).read_bytes()
        got, ret = self.frames(data, fl), self.frames(retail, fl)
        laid = {int(fr["frame"]): fr for fr in fl["frames"]}
        for f in got:
            if f not in laid:
                self.assertEqual(got[f], ret[f], f"frame {f} must be kept")
                continue
            self.assertLessEqual(len(got[f]), len(ret[f]))
            x = got[f][0][0]
            for (ox, oy, t, tp, attr, w, h), name in zip(got[f], laid[f]["cels"]):
                self.assertEqual(ox, x)
                x += w
                if name.startswith("@"):
                    self.assertEqual(t & 0xFFFF, int(name[1:], 16))
                    continue
                c = cells[name]
                pg = int(c.get("tile_page", fl["page"]))
                self.assertEqual(t, pg << 6 | (int(c["tile_y"]) // 16) << 3 | int(c["x"]) // 16, name)
                self.assertEqual(w, int(c["w"]))
            r0 = min(c[0] for c in ret[f])
            r1 = max(c[0] + c[5] for c in ret[f])
            self.assertLessEqual(abs((got[f][0][0] + x) / 2 - (r0 + r1) / 2), 1, f"frame {f} stays centred")
            self.assertNotEqual(got[f], ret[f], "control: the retail frame differs")

    def test_frame_layout_and_copy_refusals(self):
        import nbn_inject as ni
        m = manifest("B_BUNGEI")
        retail = (EXTRACTED / m["file"]).read_bytes()
        bad = json.loads(json.dumps(m))
        bad["frame_layout"]["frames"][3]["cels"] = ["@0x102"] + ["topic_anemia"] * 4 + ["@0x103"]
        with self.assertRaises(SystemExit):
            ni.apply_frame_layout(bytearray(retail), retail, bad)
        bad = json.loads(json.dumps(m))
        bad["copy_rects"][0]["to"] = {"offset": "0x12000", "x": 32, "y": 32}
        with self.assertRaises(SystemExit):
            ni.copy_rects(bytearray(retail), retail, bad)

    def test_magazine_cells_leave_no_glyph(self):
        import nbn_inject as ni
        m = manifest("MAINROM")
        data = bytearray(inject("MAINROM"))
        retail = bytearray((EXTRACTED / m["file"]).read_bytes())
        mags = [c for c in m["cells"] if c["name"].startswith("mag_")]
        self.assertGreaterEqual(len(mags), 18)
        for c in mags:
            from PIL import Image
            png = Image.open(ART / "MAINROM" / (c["name"] + ".png")).convert("RGBA")
            er = ni.erase_set(c)
            keep = {int(c["fg"])} | {int(i) for _, i in c.get("ramp", [])}
            for k in ("outline", "shadow"):
                if c.get(k) is not None:
                    keep.add(int(c[k]))
            x0, y0, w, h = ni.cell_box(c)
            s_new, s_ret = ni.cell_surface(data, m, c), ni.cell_surface(retail, m, c)
            stray = sum(1 for y in range(h) for x in range(w)
                        if s_new.get(x0 + x, y0 + y) in er and png.getpixel((x, y))[3] < 128)
            self.assertEqual(stray, 0, f"{c['name']}: retail glyph pixels left")
            ret_ink = sum(1 for y in range(h) for x in range(w) if s_ret.get(x0 + x, y0 + y) in er - {0})
            self.assertGreater(ret_ink, 20, f"control: {c['name']} has retail lettering")


if __name__ == "__main__":
    unittest.main()
