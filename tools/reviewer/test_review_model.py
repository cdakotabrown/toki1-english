"""Asset-free storage/context tests. Never write the real localization sheets."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from review_model import (ReviewError, SceneContext, Sheet, audit, bible_for,
                          editor_to_script, encoded_length, japanese_font,
                          read_bible, render_scene, script_to_editor)

COLUMNS = ["ID", "File", "Offset", "MaxBytes", "PtrSite", "Kind", "Speaker",
           "Japanese", "Tokens", "English", "Status", "Notes", "Extra"]


def record(**changes):
    row = dict(zip(COLUMNS, ["test:0x10", "test.bin", "0x10", "80", "0x40",
                            "line", "Mio Kisaragi", "こんにちは、{P}。{br}", "P br",
                            "Hello, {P}.{br}", "edited", "old note", "keep me"]))
    row.update(changes)
    return row


def write_sheet(path, rows=None, bom=False, newline="\n"):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, COLUMNS, lineterminator=newline)
    writer.writeheader()
    writer.writerows(rows if rows is not None else [record()])
    path.write_bytes(buffer.getvalue().encode("utf-8-sig" if bom else "utf-8"))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "script.csv"
        write_sheet(self.path)

    def test_explicit_save_preserves_japanese_all_columns_and_row_order(self):
        rows = [record(Notes='comma, quote " and\nnewline'), record(ID="test:0x20")]
        write_sheet(self.path, rows, bom=True, newline="\r\n")
        before = self.path.read_bytes()
        sheet = Sheet(self.path)
        sheet.edit(1, "English", '"Hi," {P}.{br}')
        self.assertEqual(self.path.read_bytes(), before)
        backup = sheet.save()
        self.assertEqual(backup.read_bytes(), before)
        self.assertTrue(self.path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", self.path.read_bytes())
        saved = Sheet(self.path)
        for i in range(2):
            for field in COLUMNS:
                if (i, field) != (1, "English"):
                    self.assertEqual(saved.rows[i][field], rows[i][field])
        self.assertEqual(saved.rows[1]["English"], '"Hi," {P}.{br}')
        self.assertEqual(sheet.changed, [])

    def test_noop_save_is_byte_exact_and_creates_no_backup(self):
        before = self.path.read_bytes()
        self.assertIsNone(Sheet(self.path).save())
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse((self.path.parent / ".review-backups").exists())

    def test_crlf_in_quoted_notes_does_not_change_lf_record_convention(self):
        write_sheet(self.path, [record(Notes="first\r\nsecond")], newline="\n")
        sheet = Sheet(self.path)
        self.assertEqual(sheet.newline, "\n")
        sheet.edit(0, "English", "Hi {P}.")
        sheet.save()
        self.assertTrue(self.path.read_bytes().split(b"\n", 1)[0].endswith(b"Extra"))
        self.assertEqual(Sheet(self.path).rows[0]["Notes"], "first\r\nsecond")

    def test_external_edit_refused_and_pending_text_retained(self):
        sheet = Sheet(self.path)
        sheet.edit(0, "English", "New {P}.")
        self.path.write_bytes(b"external changes")
        with self.assertRaisesRegex(ReviewError, "changed outside"):
            sheet.save()
        self.assertEqual(self.path.read_bytes(), b"external changes")
        self.assertEqual(sheet.rows[0]["English"], "New {P}.")
        self.assertEqual(sheet.changed, [0])

    def test_failed_replace_keeps_original_backup_and_pending_edits(self):
        sheet = Sheet(self.path)
        before = self.path.read_bytes()
        sheet.edit(0, "English", "New {P}.")
        with patch("review_model.os.replace", side_effect=PermissionError("open in Excel")):
            with self.assertRaises(PermissionError):
                sheet.save()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sheet.changed, [0])
        self.assertEqual(next((self.path.parent / ".review-backups").iterdir()).read_bytes(), before)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))
        self.assertFalse(list(self.path.parent.glob("*.review-save.lock")))

    def test_cooperating_editor_lock_prevents_save(self):
        sheet = Sheet(self.path)
        sheet.edit(0, "English", "New {P}.")
        lock = self.path.with_name("script.csv.review-save.lock")
        lock.write_text("held", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "Another save"):
            sheet.save()
        self.assertEqual(lock.read_text(), "held")

    def test_readonly_fields_cannot_be_changed_even_through_direct_mutation(self):
        sheet = Sheet(self.path)
        with self.assertRaises(ReviewError):
            sheet.edit(0, "Japanese", "changed")
        sheet.rows[0]["ID"] = "new ID"
        with self.assertRaisesRegex(ReviewError, "Read-only"):
            sheet.save()

    def test_invalid_english_requires_explicit_override(self):
        sheet = Sheet(self.path)
        sheet.edit(0, "English", "Missing name")
        with self.assertRaisesRegex(ReviewError, "QA errors"):
            sheet.save()
        sheet.save(allow_issues=True)
        self.assertEqual(Sheet(self.path).rows[0]["English"], "Missing name")

    def test_final_line_change_requires_explanatory_note(self):
        write_sheet(self.path, [record(Status="final")])
        sheet = Sheet(self.path)
        sheet.edit(0, "English", "Revised, {P}.")
        with self.assertRaisesRegex(ReviewError, "explanatory note"):
            sheet.save()
        sheet.edit(0, "Notes", "old note; D: corrected voice")
        sheet.save()
        self.assertEqual(Sheet(self.path).rows[0]["Status"], "final")

    def test_duplicate_missing_and_malformed_records_rejected(self):
        for rows in ([record(), record()], [record(ID="")]):
            write_sheet(self.path, rows)
            with self.assertRaises(ReviewError):
                Sheet(self.path)
        self.path.write_text("ID,Japanese,English\na,b,c,extra\n", encoding="utf-8")
        with self.assertRaises(ReviewError):
            Sheet(self.path)
        self.path.write_text("ID,Japanese,English\na,b\n", encoding="utf-8")
        with self.assertRaises(ReviewError):
            Sheet(self.path)

    def test_legacy_csv_is_not_mistaken_for_exact_sheet(self):
        self.path.write_text("ID,Japanese,Translation\na,b,c\n", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "Legacy"):
            Sheet(self.path)

    def test_sheet_without_japanese_needs_file_and_offset(self):
        self.path.write_text("ID,Japanese,English\na,b,c\n".replace(",Japanese", ""), encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "File and Offset"):
            Sheet(self.path)

    def test_sheet_without_japanese_reads_it_from_the_disc(self):
        """D4: the tracked sheets carry no Japanese; it comes from the retail file."""
        retail = Path(self.directory.name) / "Fake.bin"
        # retail bytes: Shift-JIS plus the single-byte control codes (0x50 = {P}, 0x20 = {br})
        text = ("こんにちは、".encode("shift_jis") + b"\x50" +
                "。".encode("shift_jis") + b"\x20" + b"\0\0")
        retail.write_bytes(b"\0" * 0x10 + text)
        columns = [c for c in COLUMNS if c != "Japanese"]
        path = Path(self.directory.name) / "disc.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, columns, lineterminator="\n")
            writer.writeheader()
            writer.writerow({k: v for k, v in record(File="Fake.bin").items() if k in columns})
        with patch.dict(os.environ, {"TOKI_RETAIL_ROOT": self.directory.name}):
            sheet = Sheet(path)
            self.assertTrue(sheet.external_japanese)
            self.assertEqual(sheet.rows[0]["Japanese"], "こんにちは、{P}。{br}")
            self.assertNotIn("Japanese", sheet.columns)
            sheet.edit(0, "English", "Hello, {P}.{br}")
            sheet.save()
            saved = Sheet(path)
            self.assertEqual(saved.rows[0]["English"], "Hello, {P}.{br}")
        self.assertNotIn(b"Japanese", path.read_bytes())


class AuditTests(unittest.TestCase):
    def test_choice_with_blank_answer_is_reported(self):
        issues = audit(record(Kind="choice", Japanese="一{opt}二{opt}三", English="One{opt}{opt}Three"))
        self.assertTrue(any("Choice 2 is blank" in issue.message for issue in issues))

    def test_name_tokens_cannot_be_moved_into_another_choice(self):
        issues = audit(record(Kind="choice", Japanese="{P}一{opt}二", English="One{opt}Two {P}"))
        self.assertEqual(sum("different name/runtime tokens" in issue.message for issue in issues), 2)

    def test_source_empty_terminal_choice_is_not_invented_as_an_error(self):
        issues = audit(record(Kind="choice", Japanese="一{opt}", English="One{opt}"))
        self.assertFalse(any(issue.level == "error" for issue in issues))

    def test_editor_newlines_roundtrip_tokens_without_touching_other_controls(self):
        script = "{br}Hello {P}.{br}{br}Choice{opt}Other{br}"
        visible = "\nHello {P}.\n\nChoice{opt}Other\n"
        self.assertEqual(script_to_editor(script), visible)
        self.assertEqual(editor_to_script(visible), script)
        self.assertEqual(editor_to_script("one\r\ntwo\rthree"), "one{br}two{br}three")
        self.assertEqual(editor_to_script("one{br}two"), "one{br}two")

    def test_japanese_font_selection_uses_cjk_family_not_latin_default(self):
        self.assertEqual(japanese_font(["DejaVu Sans", "Noto Sans CJK JP"]), "Noto Sans CJK JP")
        self.assertEqual(japanese_font(["Segoe UI", "Meiryo"]), "Meiryo")
        self.assertEqual(japanese_font(["Yu Gothic UI", "Meiryo"]), "Yu Gothic UI")
        self.assertIsNone(japanese_font(["DejaVu Sans", "Segoe UI"]))

    def test_token_multiplicity_preserved_but_br_count_may_change(self):
        self.assertFalse(any(i.level == "error" for i in audit(record(English="Hi {P}."))))
        self.assertTrue(any("tokens differ" in i.message for i in audit(record(English="{P} {P}"))))

    def test_unknown_braces_nonascii_and_literal_newlines_are_errors(self):
        for text in ("{P} {unknown}", "{P} {", "{P} café", "{P}\nline"):
            self.assertTrue(any(i.level == "error" for i in audit(record(English=text))))

    def test_budget_is_warning_hard_limit_is_error(self):
        issues = audit(record(English="Hi {P}", MaxBytes="2"))
        self.assertTrue(any(i.level == "warning" for i in issues))
        self.assertFalse(any(i.level == "error" for i in issues))
        self.assertTrue(any("hard limit" in i.message for i in audit(record(English="{P}" + "a" * 255))))
        self.assertEqual(encoded_length("ab{br}{P}{opt}"), 5)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.path = self.folder / "context.json"

    def test_unknown_rows_have_no_fabricated_visuals(self):
        context = SceneContext(self.path)
        self.assertEqual(context.variants("anything"), [])
        self.assertFalse(self.path.exists())
        with self.assertRaisesRegex(ReviewError, "No screenshot"):
            render_scene(context, {})

    def test_multiple_variants_roundtrip_and_context_conflict(self):
        context = SceneContext(self.path)
        context.add("row:0x10", dict(label="Summer", evidence="Manual capture", outfit="Summer uniform"))
        stale = SceneContext(self.path)
        context.add("row:0x10", dict(label="Winter", evidence="Second capture"))
        self.assertEqual(len(SceneContext(self.path).variants("row:0x10")), 2)
        with self.assertRaisesRegex(ReviewError, "changed outside"):
            stale.add("row:0x10", dict(label="Stale", evidence="Other capture"))
        self.assertEqual(len(stale.variants("row:0x10")), 1)

    def test_context_types_and_evidence_are_validated(self):
        for data in ([1], {"version": 2, "rows": {}}, {"version": 1, "rows": {"id": ["bad"]}},
                     {"version": 1, "rows": {"id": [{"sprite_position": [0, "bad"]}]}}):
            self.path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ReviewError):
                SceneContext(self.path)
        self.path.unlink()
        with self.assertRaisesRegex(ReviewError, "evidence"):
            SceneContext(self.path).add("id", dict(label="Unproven"))

    def test_scene_layers_and_screenshot_use_real_pixels(self):
        from PIL import Image
        Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(self.folder / "bg.png")
        Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(self.folder / "sprite.png")
        context = SceneContext(self.path)
        image = render_scene(context, dict(background="bg.png", sprite="sprite.png", sprite_position=[2, 1]))
        self.assertEqual(image.getpixel((2, 1)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((1, 1)), (0, 0, 255, 255))
        image = render_scene(context, dict(screenshot="sprite.png", background="missing.png"))
        self.assertEqual(image.size, (1, 1))

    def test_bible_uses_speaker_not_file_heroine_and_handles_player(self):
        bible = self.folder / "CHARACTER-BIBLE.md"
        bible.write_text("| Code | Name (EN order) | Role | Japanese voice | English voice (defaults) |\n"
                         "|---|---|---|---|---|\n"
                         "| KI | Mio Kisaragi | bookish | hesitant | quiet |\n"
                         "| — | the player (`{p}`) | boy | plain | awkward |\n", encoding="utf-8")
        entries = read_bible(bible)
        self.assertEqual(len(entries), 2)
        self.assertEqual(bible_for("Mio Kisaragi", entries)["role"], "bookish")
        self.assertEqual(bible_for("player (choice)", entries)["english_voice"], "awkward")
        self.assertIsNone(bible_for("", entries))
        self.assertIsNone(bible_for("system", entries))

    def test_gui_capture_keeps_unselected_edits_in_memory(self):
        from app import ReviewDesk
        write_sheet(self.folder / "test.csv")
        desk = ReviewDesk.__new__(ReviewDesk)
        desk.sheet = Sheet(self.folder / "test.csv")
        desk.row_index, desk.loading = 0, False
        class Widget:
            def __init__(self, value):
                self.value = value
            def get(self, *_):
                return self.value
        class Dialogue:
            def get_script(self):
                return "Hi {P}{br}Second line{br}"
        desk.dialogue, desk.notes = Dialogue(), Widget("reviewed\nnotes")
        desk.capture_edits()
        self.assertEqual(desk.sheet.rows[0]["English"], "Hi {P}{br}Second line{br}")
        self.assertEqual(desk.sheet.rows[0]["Notes"], "reviewed\nnotes")
        self.assertEqual(Sheet(self.folder / "test.csv").rows[0]["English"], "Hello, {P}.{br}")


@unittest.skipUnless(os.environ.get("REVIEW_GUI_TESTS") == "1", "desktop GUI tests; set REVIEW_GUI_TESTS=1")
class ChoiceGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "choices.csv"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def open_desk(self, english="Name {P}{opt}Second{br}line{opt}Third", kind="choice"):
        from app import ReviewDesk
        write_sheet(self.path, [record(Kind=kind, Japanese="名前{P}{opt}二つ目{br}続き{opt}三つ目", English=english, MaxBytes="255")])
        desk = ReviewDesk(self.root, self.path.parent)
        self.root.update()
        return desk

    def test_numbered_choices_align_jp_en_and_roundtrip_save_without_labels(self):
        desk = self.open_desk()
        self.assertEqual(len(desk.dialogue.english_fields), 3)
        self.assertEqual(len(desk.dialogue.japanese_fields), 3)
        self.assertEqual(desk.dialogue.block_label, "Choice")
        self.assertEqual(desk.dialogue.japanese_fields[1].get("1.0", "end-1c"), "二つ目\n続き")
        self.assertFalse(desk.sheet.changed)
        field = desk.dialogue.english_fields[1]
        field.delete("1.0", "end")
        field.insert("1.0", "Changed\nTwo lines\n")
        # Intentionally save BEFORE processing queued Modified events.
        self.assertTrue(desk.save())
        self.root.update()
        saved = Sheet(self.path)
        self.assertEqual(saved.rows[0]["English"], "Name {P}{opt}Changed{br}Two lines{br}{opt}Third")
        self.assertEqual(saved.rows[0]["Japanese"], "名前{P}{opt}二つ目{br}続き{opt}三つ目")
        self.assertEqual(saved.rows[0]["ID"], "test:0x10")
        self.assertFalse(desk.sheet.changed)
        self.assertNotIn("Choice 2", saved.rows[0]["English"])

    def test_open_folder_selects_mapped_row_and_distinguishes_unmapped_rows(self):
        from app import ReviewDesk
        write_sheet(self.path, [record(), record(ID="test:0x20")])
        self.path.with_suffix(".context.json").write_text(json.dumps(dict(version=1, rows={
            "test:0x20": [dict(label="Fixture", evidence="Synthetic", background="missing.png")]})), encoding="utf-8")
        desk = ReviewDesk(self.root, self.path.parent)
        self.root.update()
        self.assertEqual(desk.row_index, 1)
        self.assertIn("Scene mapping found", desk.context_status.cget("text"))
        self.assertIn("Preview unavailable", desk.scene_panel.images["background"].cget("text"))
        desk.rows.selection_set("0")
        desk.select_row()
        self.assertIn("no verified mapping", desk.context_status.cget("text"))
        desk.search.set("no matches")
        desk.only_issues.set(True)
        desk.find_scene_art()
        self.assertEqual(desk.row_index, 1)
        self.assertFalse(desk.only_issues.get())
        self.assertFalse(desk.sheet.changed)
        self.root.update()

    def test_find_scene_respects_cancelled_sheet_switch(self):
        from app import ReviewDesk
        write_sheet(self.path)
        target = self.path.parent / "z-mapped.csv"
        write_sheet(target)
        desk = ReviewDesk(self.root, self.path.parent)
        self.root.update()
        target.with_suffix(".context.json").write_text(json.dumps(dict(version=1, rows={
            "test:0x10": [dict(label="Fixture", evidence="Synthetic", sprite="missing.png")]})), encoding="utf-8")
        desk.dialogue.english_fields[0].insert("end-1c", " Pending")
        with patch("tkinter.messagebox.askyesnocancel", return_value=None):
            desk.find_scene_art()
        self.assertEqual(desk.sheet.path, self.path)
        self.assertIn("Pending", desk.dialogue.get_script())
        self.assertEqual(desk.sheets.selection(), ("0",))
        self.root.update()

    def test_empty_english_browsing_and_view_toggles_do_not_inject_tokens(self):
        desk = self.open_desk(english="")
        self.assertEqual(len(desk.dialogue.english_fields), 3)
        desk.capture_edits()
        self.assertEqual(desk.dialogue.get_script(), "")
        self.assertFalse(desk.sheet.changed)
        desk.dialogue.toggle_raw()
        self.root.update()
        desk.dialogue.toggle_raw()
        self.root.update()
        desk.capture_edits()
        self.assertEqual(desk.dialogue.get_script(), "")
        self.assertFalse(desk.sheet.changed)

    def test_extra_option_is_visible_and_can_be_repaired_in_raw_view(self):
        original = "First {P}{opt}Second{opt}Third{opt}Extra"
        desk = self.open_desk(english=original)
        self.assertEqual(len(desk.dialogue.english_fields), 4)
        self.assertEqual(desk.dialogue.english_fields[3].get("1.0", "end-1c"), "Extra")
        self.assertEqual(desk.dialogue.get_script(), original)
        desk.dialogue.toggle_raw()
        self.root.update()
        field = desk.dialogue.english_fields[0]
        field.delete("1.0", "end")
        field.insert("1.0", "First {P}{opt}Second{opt}Third")
        desk.dialogue.toggle_raw()
        self.root.update()
        self.assertEqual(len(desk.dialogue.english_fields), 3)
        self.assertTrue(desk.save())
        self.assertEqual(Sheet(self.path).rows[0]["English"], "First {P}{opt}Second{opt}Third")

    def test_nonchoice_opt_is_labeled_as_message_blocks(self):
        desk = self.open_desk(kind="line")
        self.assertEqual(desk.dialogue.block_label, "Message")
        self.assertEqual(len(desk.dialogue.english_fields), 3)

    def test_choice_edits_survive_navigation_and_undo(self):
        desk = self.open_desk()
        original = desk.dialogue.get_script()
        field = desk.dialogue.english_fields[0]
        field.insert("end-1c", " updated")
        self.root.update()
        self.assertIn(" updated", desk.sheet.rows[0]["English"])
        field.edit_undo()
        self.root.update()
        self.assertEqual(desk.dialogue.get_script(), original)
        self.assertFalse(desk.sheet.changed)
        desk.refresh_rows()
        self.root.update()
        self.assertEqual(desk.dialogue.get_script(), original)

    def test_compact_lists_and_text_padding(self):
        from tkinter import font as tkfont, ttk
        desk = self.open_desk()
        height = int(ttk.Style(self.root).lookup("Treeview", "rowheight"))
        self.assertEqual(height, tkfont.nametofont("TkDefaultFont", root=self.root).metrics("linespace") + 2)
        self.assertLessEqual(int(desk.notes.cget("padx")), 4)
        self.assertLessEqual(int(desk.notes.cget("pady")), 2)
        self.assertNotIn("{opt}", desk.rows.item("0", "values")[1])

    def test_tab_navigates_choices_without_inserting_a_control_character(self):
        desk = self.open_desk()
        original = desk.dialogue.get_script()
        first, second = desk.dialogue.english_fields[:2]
        with patch.object(second, "focus_set") as focus:
            self.assertEqual(desk.dialogue._focus_step(first, 1), "break")
            focus.assert_called_once()
        self.assertEqual(desk.dialogue.get_script(), original)
        self.assertTrue(first.bind("<Tab>"))


if __name__ == "__main__":
    unittest.main()
