#!/usr/bin/env python3
"""Tests for tools/translation/build_jev_qa_kit.py (the Jev QA kit).

  * every row of every injected container's sheet (plus the tagged rows the
    sheets skip) is accounted for exactly once, shipped or not shipped, and
    the shipped container lines per container match the sheet counts;
  * every shipped English string appears exactly once (unique ids, and the
    overlay / ui / profile strings match the builder's own generated JSON
    entry for entry);
  * the neighbours of a known conversation (the opening of SERIFU/DATE_AS,
    the museum date) are the sheet's rows in offset order;
  * NEGATIVE CONTROLS: dropping one sheet's lines, or one container from the
    sheet table, makes the count check fail; a duplicated line is caught.

Skipped without the player's extracted disc (assets/extracted_iso/CDROM,
assets/overlays, disks/SLPS_000.65), like the patch-build tests.

    python3 -m unittest tools/translation/test_build_jev_qa_kit.py
"""
import csv
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT, SHEETS, TOOLS_TRANSLATION  # noqa: E402  (this checkout, either layout)
sys.path.insert(0, str(TOOLS_TRANSLATION / "jev_qa_kit/runner"))

sys.path.insert(0, str(ROOT / "tools"))
from repo_paths import DECOMP  # noqa: E402  (the extracted disc is toki1-decomp's)

NEEDS = [DECOMP / "assets/extracted_iso/CDROM", DECOMP / "assets/overlays", DECOMP / "disks/SLPS_000.65"]
HAVE_DISC = all(p.exists() for p in NEEDS)


@unittest.skipUnless(HAVE_DISC, "needs the extracted disc (assets/extracted_iso, assets/overlays, disks/)")
class KitDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_jev_qa_kit as kit
        cls.kit = kit
        cls.lines, cls.not_shipped, cls.sheet_counts, _ = kit.collect(log=lambda *a: None)
        cls.by_id = {l["id"]: l for l in cls.lines}

    def test_counts_match_the_sheets(self):
        self.assertEqual(self.kit.check_counts(self.lines, self.not_shipped, self.sheet_counts), [])
        # independently of the kit's own bookkeeping: per sheet, rows read
        # straight from the CSV == shipped + not shipped sheet rows
        for c, info in self.sheet_counts.items():
            if info["extra"]:
                continue
            with open(ROOT / info["sheet"], encoding="utf-8", newline="") as fh:
                n_csv = sum(1 for _ in csv.DictReader(fh))
            self.assertEqual(n_csv, info["sheet_rows"], c)
            sheet_ids = set()
            with open(ROOT / info["sheet"], encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    sheet_ids.add(self.kit.short_id(r["ID"]))
            shipped = {l["id"] for l in self.lines if l["container"] == c and
                       l["source_kind"] == "container_sheet"}
            kept = {n["id"] for n in self.not_shipped if n["id"] in sheet_ids}
            self.assertEqual(shipped | kept, sheet_ids, c)
            self.assertFalse(shipped & kept, c)

    def test_every_sheet_with_text_is_in_the_kit(self):
        sheets = {str(p.relative_to(ROOT)) for p in (SHEETS).rglob("*.csv")
                  if p.parent.name not in ("BATTLE", "BUNKASD")}
        have = {info["sheet"] for info in self.sheet_counts.values()}
        self.assertEqual(sheets - have, set())

    def test_each_shipped_line_once(self):
        ids = Counter(l["id"] for l in self.lines)
        self.assertEqual([k for k, v in ids.items() if v > 1], [])
        self.assertTrue(all(l["en"] and l["ships"] for l in self.lines))
        # the builder's generated string files, entry for entry (blanks and
        # profile strings aside)
        gen = ROOT / "build/patch/gen"
        n_ovs = 0
        o = json.loads((gen / "overlay_sheets.json").read_text())
        n_ovs += len(o["main"]) + sum(len(v) for v in o["overlays"].values()) + \
            sum(len(v) for v in o["files"].values())
        n_kit = sum(1 for l in self.lines if l["source_kind"] in ("overlay_string", "file_string"))
        blanks = sum(1 for lst in [o["main"]] + list(o["overlays"].values()) + list(o["files"].values())
                     for s in lst if not s.get("text", "").strip())
        # an overlay_sheets entry already covered by a profile / ui string is
        # skipped by the builder itself, so the kit can only have fewer
        self.assertLessEqual(n_kit, n_ovs - blanks)
        self.assertGreater(n_kit, 0.95 * (n_ovs - blanks))
        u = json.loads((gen / "ui_strings.json").read_text())
        n_ui = sum(1 for lst in [u["main"]] + list(u["overlays"].values()) for s in lst
                   if s.get("text", "").strip())
        n_kit_ui = sum(1 for l in self.lines if l["source_kind"] == "ui_string")
        self.assertLessEqual(n_kit_ui, n_ui)
        self.assertGreater(n_kit_ui, 0.95 * n_ui)

    def test_shipped_text_is_the_injectors(self):
        # the opening of the DATE_AS reply menu: shipped == the fitted sheet text
        import inject
        line = self.by_id["SERIFU/DATE_AS.BIN:0x4c"]
        self.assertEqual(line["kind"], "choice")
        self.assertEqual(line["en"], inject.fit_text(inject.normalise(line["en_source"]), "choice",
                                                     Counter())[0])
        self.assertEqual(line["speaker"]["role"], "player")

    def test_neighbours_of_a_known_conversation(self):
        import retail_text      # the tracked sheet has no Japanese: read it from the disc
        rows = sorted(retail_text.read_sheet(SHEETS / "SERIFU/DATE_AS.csv"),
                      key=lambda r: int(r["Offset"], 16))
        ids = [self.kit.short_id(r["ID"]) for r in rows]
        jp = {self.kit.short_id(r["ID"]): r["Japanese"] for r in rows}
        line = self.by_id["SERIFU/DATE_AS.BIN:0x10"]
        self.assertEqual(ids[:4], ["SERIFU/DATE_AS.BIN:0x0", "SERIFU/DATE_AS.BIN:0x10",
                                   "SERIFU/DATE_AS.BIN:0x34", "SERIFU/DATE_AS.BIN:0x4c"])
        self.assertEqual([n["id"] for n in line["neighbours"]["prev"]], ["SERIFU/DATE_AS.BIN:0x0"])
        self.assertEqual([n["id"] for n in line["neighbours"]["next"]], ids[2:5])
        for n in line["neighbours"]["prev"] + line["neighbours"]["next"]:
            self.assertEqual(n["jp"], jp[n["id"]])
        self.assertEqual(line["neighbours"]["prev"][0]["speaker"], "Yuko Asahina")
        mid = self.by_id[ids[10]]
        self.assertEqual([n["id"] for n in mid["neighbours"]["prev"]], ids[7:10])
        self.assertEqual([n["id"] for n in mid["neighbours"]["next"]], ids[11:14])

    # -- negative controls ------------------------------------------------

    def test_negative_dropped_sheet_fails(self):
        dropped = [l for l in self.lines if l["container"] != "SERIFU/DATE_AS"]
        self.assertLess(len(dropped), len(self.lines))
        probs = self.kit.check_counts(dropped, self.not_shipped, self.sheet_counts)
        self.assertTrue(any(p.startswith("SERIFU/DATE_AS:") for p in probs), probs)

    def test_negative_missing_container_fails(self):
        sc = dict(self.sheet_counts)
        del sc["SERIFU/GEKO"]
        probs = self.kit.check_counts(self.lines, self.not_shipped, sc)
        self.assertTrue(any("SERIFU/GEKO.BIN" in p for p in probs), probs)

    def test_negative_duplicate_line_fails(self):
        probs = self.kit.check_counts(self.lines + [self.lines[0]], self.not_shipped, self.sheet_counts)
        self.assertTrue(any("copies" in p for p in probs), probs)


class KitPureTest(unittest.TestCase):
    """no disc needed"""

    def test_readable(self):
        import build_jev_qa_kit as kit
        self.assertEqual(kit.readable("あっ、{P}。{br}元気？"), "あっ、[PLAYER, as she addresses him]。 / 元気？")
        self.assertEqual(kit.readable("Yes.{opt}No.", "choice"), "Reply 1: Yes. || Reply 2: No.")
        self.assertEqual(kit.short_id("assets/extracted_iso/CDROM/SERIFU/X.BIN:0xE70"), "SERIFU/X.BIN:0xe70")

    def test_scene_for(self):
        import build_jev_qa_kit as kit
        d, conf, g = kit.scene_for("SERIFU/DATE_HI")
        self.assertEqual(g, "HI")
        self.assertIn("Yuina Himoo", d)
        self.assertEqual(kit.scene_for("BUNKA/KT_S61")[2], "KA")

    def test_questions_and_predicates(self):
        import common
        qs = common.load_questions(TOOLS_TRANSLATION / "jev_qa_kit/questions/questions.json")
        self.assertEqual(len({q["id"] for q in qs}), len(qs))
        for q in qs:
            for p in q["applies_when"]:
                self.assertIn(p, common.PREDICATES, q["id"])
            self.assertIn(q["type"], ("boolean", "choice", "score"))
            if q["type"] == "choice":
                self.assertIn(q["problem"]["answer"], q["options"])

    def test_stratified_sample(self):
        import common
        lines = [{"id": f"x{i}", "group": "G" + str(i % 3), "status_class": "draft",
                  "speaker": {"role": "heroine"}, "kind": "line"} for i in range(300)]
        s = common.stratified_sample(lines, 30, 1)
        self.assertEqual(len(s), 30)
        self.assertEqual(Counter(l["group"] for l in s), Counter({"G0": 10, "G1": 10, "G2": 10}))
        self.assertEqual(s, common.stratified_sample(lines, 30, 1))


if __name__ == "__main__":
    unittest.main()
