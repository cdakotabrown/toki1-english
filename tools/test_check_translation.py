"""Regression tests for the sheet QA gate (no retail assets needed)."""
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check_translation


class TranslationGateTests(unittest.TestCase):
    def check_row(self, english, status="draft", japanese="{G}こんにちは"):
        with tempfile.TemporaryDirectory() as directory:
            sheet_dir = Path(directory) / "SERIFU"
            sheet_dir.mkdir()
            with (sheet_dir / "SAMPLE.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("ID", "Japanese", "English", "Status", "MaxBytes"))
                writer.writeheader()
                writer.writerow({"ID": "sample:0x0", "Japanese": japanese, "English": english,
                                 "Status": status, "MaxBytes": "200"})
            output = io.StringIO()
            with patch.object(check_translation, "SHEETS", Path(directory)), contextlib.redirect_stdout(output):
                result = check_translation.main(["check_translation.py"])
            return result, output.getvalue()

    def test_valid_token_and_line_reflow(self):
        result, output = self.check_row("Hello {G}!{br}Welcome.", japanese="{G}こんにちは")
        self.assertEqual(result, 0, output)

    def test_unknown_token_is_not_silent_ascii(self):
        result, output = self.check_row("Hello {G} {bad}")
        self.assertEqual(result, 1)
        self.assertIn("FAIL syntax", output)

    def test_unmatched_brace(self):
        result, output = self.check_row("Hello {G} }", japanese="{G}")
        self.assertEqual(result, 1)
        self.assertIn("FAIL syntax", output)

    def test_unknown_status_cannot_hide_a_row(self):
        result, output = self.check_row("", status="editted")
        self.assertEqual(result, 1)
        self.assertIn("FAIL status", output)

    def test_non_ascii_punctuation_is_rejected(self):
        result, output = self.check_row("Hello {G}…")
        self.assertEqual(result, 1)
        self.assertIn("FAIL charset", output)


if __name__ == "__main__":
    unittest.main()
