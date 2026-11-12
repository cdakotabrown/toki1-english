#!/usr/bin/env python3
"""Tests for tools/patch/audit_drawn_text.py (synthetic logs, no game data).

    python3 -m unittest tools/patch/test_audit_drawn_text.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_drawn_text as A  # noqa: E402

SJIS_TEST = "テスト表示".encode("shift_jis")      # Japanese (katakana + kanji)
NAME_KANA = "あい".encode("shift_jis")            # a player's kana name
CIRCLE = "○".encode("shift_jis")                  # a symbol the English font keeps


def line(hexbytes, addr=0x800B7000, host=0, sym="", step=52, x=-72, y=50):
    return json.dumps({"f": 100, "scene": 10, "step": step, "sub": 1, "x": x, "y": y,
                       "addr": hex(addr), "host": host, "sym": sym, "hex": hexbytes.hex()})


class AuditDrawnText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.inv = A.Inventory(self.dir / "no_inventory.json")

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, lines, ps1_keys=None):
        p = self.dir / "run.jsonl"
        p.write_text("\n".join(lines) + "\n")
        recs = A.read_pc([str(p)], None)
        return A.classify(recs, self.inv, None, {}, ps1_keys)

    def test_english_is_not_flagged(self):
        self.assertEqual(self.scan([line(b"Joined the Tennis Club.")]), [])

    def test_font_symbols_are_not_flagged(self):
        self.assertEqual(self.scan([line(b"Press " + CIRCLE)]), [])

    def test_japanese_is_flagged(self):
        g = self.scan([line(SJIS_TEST)])
        self.assertEqual(len(g), 1)
        self.assertIn("japanese", g[0]["flags"])
        self.assertEqual(g[0]["class"], "c")     # no inventory row: untranslated / review

    def test_mixed(self):
        g = self.scan([line(b"Swimming" + SJIS_TEST)])
        self.assertIn("mixed", g[0]["flags"])
        self.assertEqual(g[0]["class"], "b")

    def test_host_copy_of_retail_data_is_class_a(self):
        """a draw from a host copy (a pc_retail_init name) is PC-only even in English"""
        if A.PC is None:
            self.skipTest("needs the PC port's host tables (toki1-pc checkout absent)")
        names = A.retail_copy_names()
        self.assertIn("join_club_message_str0", names)
        g = self.scan([line(b"Joined", addr=0x1234560, host=1, sym="join_club_message_str0")])
        self.assertEqual(g[0]["class"], "a")
        # negative control: a native buffer (no retail-copy symbol) in English is fine
        self.assertEqual(self.scan([line(b"Joined", addr=0x1234560, host=1, sym="")]), [])

    def test_pc_only_by_comparison(self):
        """translated per the inventory, Japanese on the PC, not on the PS1: class a"""
        self.inv.rows.append(("PSX.EXE", 0x10, "injected", "x"))
        t = A.jp_only(A.textcodec.decode(SJIS_TEST))
        for i in range(0, max(1, len(t) - A.WIN + 1)):
            self.inv.win[t[i:i + A.WIN]].add(0)
        self.assertEqual(self.scan([line(SJIS_TEST)], ps1_keys=set())[0]["class"], "a")
        # the PS1 draws it Japanese too: a patch bug
        k = A.key_of(A.textcodec.decode(SJIS_TEST))
        self.assertEqual(self.scan([line(SJIS_TEST)], ps1_keys={k})[0]["class"], "b")

    def test_player_kana_name_is_expected(self):
        g = self.scan([line(NAME_KANA)])
        self.assertEqual(g[0]["class"], "expected")

    def test_baseline_check(self):
        """--check fails on a flagged string not in the baseline, passes once
        it is recorded; the baseline holds hashes only (no text)"""
        log = self.dir / "a.jsonl"
        log.write_text(line(SJIS_TEST) + "\n")
        base = self.dir / "base.json"
        cmd = [sys.executable, str(HERE / "audit_drawn_text.py"), "scan", "--pc", str(log),
               "--baseline", str(base)]
        r = subprocess.run(cmd + ["--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        subprocess.run(cmd + ["--write-baseline"], check=True, capture_output=True)
        text = base.read_text(encoding="utf-8")
        self.assertNotIn("テスト", text)
        r = subprocess.run(cmd + ["--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # a second, new string fails again (the regression the gate is for)
        log.write_text(line(SJIS_TEST) + "\n" + line("別の文字列".encode("shift_jis")) + "\n")
        r = subprocess.run(cmd + ["--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
