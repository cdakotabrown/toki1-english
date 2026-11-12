"""lint_sheets.py and hydrate.py fold: the tracked sheets pass, seeded
mistakes fail, a fold carries only the editable columns (no disc needed;
the hydrate round trip runs when the extracted disc is present)."""
import contextlib
import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TOKI_DECOMP_OPTIONAL", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_sheets as L  # noqa: E402
import hydrate as H  # noqa: E402

FIELDS = L.FIELDS
GOOD = {"ID": "assets/extracted_iso/CDROM/SERIFU/T.BIN:0x10",
        "File": "assets/extracted_iso/CDROM/SERIFU/T.BIN", "Offset": "0x10",
        "MaxBytes": "40", "PtrSite": "0x4", "Kind": "line", "Speaker": "player",
        "Tokens": "G br", "English": "Hello, {G}.{br}Nice day.", "Status": "edited",
        "Notes": "the particle は stays out of the English"}
CHOICE = dict(GOOD, ID="assets/extracted_iso/CDROM/SERIFU/T.BIN:0x40", Offset="0x40",
              Kind="choice", Speaker="player (choice)", Tokens="opt",
              English="Yes.{opt}No.")


def sheet_text(rows, fields=FIELDS):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


class Lint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "SERIFU").mkdir()
        self.path = self.tmp / "SERIFU" / "T.csv"

    def run_lint(self, rows=None, text=None, data=None):
        if data is None:
            data = (text if text is not None else sheet_text(rows)).encode("utf-8")
        self.path.write_bytes(data)
        f, _ = L.lint(sheets=self.tmp, glossary=self.tmp / "none.csv", base=None,
                      repository=False)
        return {k for k, _, _ in f.fails}, f.fails

    def assertFails(self, kind, _choice=False, **change):
        """a seeded mistake in the line row (or, _choice, the menu row)"""
        rows = [GOOD, dict(CHOICE, **change)] if _choice else [dict(GOOD, **change), CHOICE]
        kinds, fails = self.run_lint(rows)
        self.assertIn(kind, kinds, fails)

    def test_good_rows_pass(self):
        kinds, fails = self.run_lint([GOOD, CHOICE])
        self.assertEqual(kinds, set(), fails)

    def test_the_tracked_sheets_pass(self):
        f, stats = L.lint(base=None, repository=True)
        self.assertEqual(f.fails, [])
        self.assertGreater(stats["rows"], 40000)

    # -- mechanical rules
    def test_unknown_token(self):
        self.assertFails("text", English="Hello, {G}.{br}{X} day.")

    def test_unmatched_brace(self):
        self.assertFails("text", English="Hello, {G}. }")

    def test_dropped_name_token(self):
        self.assertFails("text", English="Hello there.{br}Nice day.")

    def test_non_ascii(self):
        self.assertFails("text", English="Hello, {G}… nice day.")

    def test_unknown_status(self):
        self.assertFails("text", Status="editted")

    def test_blank_english(self):
        self.assertFails("text", English="")

    def test_over_the_hard_byte_limit(self):
        self.assertFails("text", English="{G} " + "word " * 60)

    def test_word_wider_than_the_window(self):
        self.assertFails("fit", English="{G} " + "W" * 40)

    def test_over_wide_menu_choice(self):
        self.assertFails("fit", _choice=True,
                         English="Yes, of course I would love to go there with you this "
                                 "Sunday afternoon.{opt}No, I really cannot go there "
                                 "with you this Sunday, sorry about that.{opt}Maybe some "
                                 "other day when the weather is a bit better than today.")

    # -- Japanese
    def test_japanese_in_english(self):
        self.assertFails("japanese", English="Hello, {G}.{br}こんにちは")

    def test_a_japanese_line_in_notes(self):
        # built from two short pieces: no file of the repository holds a
        # Japanese line (the lint's own repository rule)
        self.assertFails("japanese", Notes="JP: " + "今日はいい天気" + "ですね、本当に。")

    def test_a_short_term_in_notes_passes(self):
        kinds, fails = self.run_lint([dict(GOOD, Notes="tsuyogari (強がり)"), CHOICE])
        self.assertEqual(kinds, set(), fails)

    def test_a_hydrated_sheet_copied_back(self):
        f = list(FIELDS)
        f.insert(f.index("Tokens"), "Japanese")
        kinds, fails = self.run_lint(text=sheet_text([dict(GOOD, Japanese="x")], f))
        self.assertIn("japanese", kinds, fails)

    # -- format
    def test_crlf(self):
        kinds, _ = self.run_lint(text=sheet_text([GOOD]).replace("\n", "\r\n"))
        self.assertIn("format", kinds)

    def test_bom(self):
        kinds, _ = self.run_lint(data=b"\xef\xbb\xbf" + sheet_text([GOOD]).encode())
        self.assertIn("format", kinds)

    def test_unescaped_quote(self):
        text = sheet_text([GOOD]).replace("stays out", 'stays "out"') \
            .replace("the particle", '"the particle').rstrip("\n") + '"\n'
        kinds, _ = self.run_lint(text=text.replace('""', '"'))
        self.assertIn("format", kinds)

    def test_extra_column(self):
        kinds, _ = self.run_lint(text=sheet_text([GOOD]).replace("Notes\n", "Notes,Extra\n"))
        self.assertIn("format", kinds)

    def test_id_not_file_offset(self):
        self.assertFails("format", Offset="0x14")

    def test_not_canonical(self):
        kinds, _ = self.run_lint(text=sheet_text([GOOD]).replace(",player,", ',"player",'))
        self.assertIn("format", kinds)

    # -- rows against a base
    def check_rows(self, rows, base, allow=False):
        f = L.Findings()
        L.check_rows_against(self.path, rows, base, f, allow)
        return f.fails

    def test_same_rows_pass(self):
        self.assertEqual(self.check_rows([GOOD, CHOICE], [GOOD, CHOICE]), [])

    def test_removed_row(self):
        self.assertTrue(self.check_rows([GOOD], [GOOD, CHOICE]))

    def test_reordered_rows(self):
        self.assertTrue(self.check_rows([CHOICE, GOOD], [GOOD, CHOICE]))

    def test_added_row_allowed_on_purpose(self):
        self.assertTrue(self.check_rows([GOOD, CHOICE], [GOOD]))
        self.assertEqual(self.check_rows([GOOD, CHOICE], [GOOD], allow=True), [])

    def test_extracted_column_changed(self):
        self.assertTrue(self.check_rows([dict(GOOD, MaxBytes="99"), CHOICE], [GOOD, CHOICE]))

    def test_english_change_passes(self):
        self.assertEqual(self.check_rows([dict(GOOD, English="Hi, {G}."), CHOICE],
                                         [GOOD, CHOICE]), [])


class Fold(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.sheets, self.work = self.tmp / "sheets", self.tmp / "work" / "sheets"
        (self.sheets / "SERIFU").mkdir(parents=True)
        (self.work / "SERIFU").mkdir(parents=True)
        self.tracked = self.sheets / "SERIFU" / "T.csv"
        self.tracked.write_text(sheet_text([GOOD, CHOICE]), encoding="utf-8")
        for name, val in (("SHEETS", self.sheets), ("HYDRATED", self.work),
                          ("BASE", self.tmp / "work" / ".base")):
            old = getattr(H, name)
            setattr(H, name, val)
            self.addCleanup(setattr, H, name, old)

    def hydrated(self, rows):
        """the work copy (and, as `hydrate` leaves it, the base)"""
        jp = [dict(r, Japanese="（日本語）" * 3) for r in rows]
        (self.work / "SERIFU" / "T.csv").write_text(sheet_text(jp, H.HYDRATED_FIELDS),
                                                    encoding="utf-8")
        base = H.base_of(self.tracked)
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_bytes(self.tracked.read_bytes())

    def edit_work(self, rows):
        jp = [dict(r, Japanese="（日本語）" * 3) for r in rows]
        (self.work / "SERIFU" / "T.csv").write_text(sheet_text(jp, H.HYDRATED_FIELDS),
                                                    encoding="utf-8")

    def fold(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = H.main(["fold"])
        return rc, out.getvalue()

    def test_no_edit_is_byte_identical(self):
        before = self.tracked.read_bytes()
        self.hydrated([GOOD, CHOICE])
        rc, _ = self.fold()
        self.assertEqual((rc, self.tracked.read_bytes()), (0, before))

    def test_a_newer_sheet_is_not_overwritten_by_a_stale_copy(self):
        self.hydrated([GOOD, CHOICE])
        self.tracked.write_text(sheet_text([dict(GOOD, English="Pulled, {G}.{br}Newer."), CHOICE]),
                                encoding="utf-8")
        after_pull = self.tracked.read_bytes()
        self.edit_work([GOOD, dict(CHOICE, Notes="mine")])
        rc, out = self.fold()
        self.assertEqual(rc, 0, out)
        text = self.tracked.read_text(encoding="utf-8")
        self.assertIn("Pulled, {G}.{br}Newer.", text)       # the pulled cell stays
        self.assertIn("mine", text)                           # the edit folds
        self.assertNotEqual(self.tracked.read_bytes(), after_pull)

    def test_a_cell_changed_on_both_sides_is_a_conflict(self):
        self.hydrated([GOOD, CHOICE])
        self.tracked.write_text(sheet_text([dict(GOOD, English="Theirs, {G}."), CHOICE]),
                                encoding="utf-8")
        before = self.tracked.read_bytes()
        self.edit_work([dict(GOOD, English="Mine, {G}."), CHOICE])
        rc, out = self.fold()
        self.assertEqual((rc, self.tracked.read_bytes()), (1, before))
        self.assertIn("both here and in the tracked sheet", out)

    def test_an_edit_folds_back_without_japanese(self):
        self.hydrated([GOOD, CHOICE])
        self.edit_work([dict(GOOD, English="Hi, {G}.{br}Lovely day.", Notes="n"), CHOICE])
        rc, out = self.fold()
        self.assertEqual(rc, 0, out)
        text = self.tracked.read_text(encoding="utf-8")
        self.assertIn("Hi, {G}.{br}Lovely day.", text)
        self.assertNotIn("日本語", text)
        self.assertEqual(text.splitlines()[0], ",".join(FIELDS))
        # the untouched row is byte for byte the same
        self.assertEqual(text.splitlines()[2], sheet_text([CHOICE]).splitlines()[1])

    def test_japanese_pasted_into_english_is_refused(self):
        self.hydrated([GOOD, CHOICE])
        self.edit_work([dict(GOOD, English="こんにちは"), CHOICE])
        before = self.tracked.read_bytes()
        rc, out = self.fold()
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", out)
        self.assertEqual(self.tracked.read_bytes(), before)

    def test_moved_rows_are_refused(self):
        self.hydrated([CHOICE, GOOD])
        before = self.tracked.read_bytes()
        rc, _ = self.fold()
        self.assertEqual((rc, self.tracked.read_bytes()), (1, before))


class RoundTrip(unittest.TestCase):
    """hydrate then fold on the real sheets: git sees no change (needs the
    extracted disc, read through toki1-decomp)"""

    def test_round_trip(self):
        try:
            import retail_text
            retail_text.japanese_for({"File": "assets/extracted_iso/CDROM/MASTER/UEKI.BIN",
                                      "Offset": "0x0"})
        except Exception as e:      # noqa: BLE001 - no disc: say so
            self.skipTest(f"no extracted disc ({e})")
        # a temporary work tree: never the contributor's own (its edits)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for name, val in (("WORK", tmp), ("HYDRATED", tmp / "sheets"), ("BASE", tmp / ".base")):
            old = getattr(H, name)
            setattr(H, name, val)
            self.addCleanup(setattr, H, name, old)
        before = {p: p.read_bytes() for p in sorted(L.SHEETS.glob("*/*.csv"))}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(H.main(["hydrate"]), 0)
            self.assertEqual(H.main(["fold"]), 0)
        after = {p: p.read_bytes() for p in sorted(L.SHEETS.glob("*/*.csv"))}
        self.assertEqual(before, after)
        self.assertTrue(any(tmp.glob("sheets/*/*.csv")))
        r = subprocess.run(["git", "status", "--porcelain", "--", str(L.SHEETS)],
                           cwd=L.ROOT, capture_output=True, text=True)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
