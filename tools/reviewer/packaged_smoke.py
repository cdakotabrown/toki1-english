"""Acceptance checks inside the shipped executable; never open real sheets."""
import csv
import json
from pathlib import Path
import platform
import sys
import tempfile
import traceback
import tkinter as tk
from tkinter import font as tkfont
from unittest.mock import patch

from PIL import Image, __version__ as pillow_version

from review_model import ReviewError, Sheet, japanese_font


def run(report_path):
    report = dict(platform=platform.platform(), python=sys.version,
                  frozen=bool(getattr(sys, "frozen", False)), pillow=pillow_version,
                  checks=[], passed=False)
    root = None

    def check(condition, name):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)

    try:
        from app import ReviewDesk
        with tempfile.TemporaryDirectory(prefix="TokimekiReview-test-") as temporary:
            folder = Path(temporary) / "日本語 review folder"
            folder.mkdir()
            path = folder / "choices.csv"
            columns = ["ID", "Japanese", "English", "Kind", "Speaker", "MaxBytes", "Status", "Notes", "Extra"]
            original = [dict(zip(columns, ["smoke:1", "名前{P}{opt}二つ目{br}続き{opt}三つ目",
                        "Name {P}{opt}Second{br}line{opt}Third", "choice", "Mio Kisaragi",
                        "255", "edited", "Original note", "preserve me"])),
                        dict(zip(columns, ["smoke:2", "こんにちは。", "Hello.", "line", "",
                        "255", "edited", "Second note", "preserve too"]))]
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, columns, lineterminator="\r\n")
                writer.writeheader()
                writer.writerows(original)
            before = path.read_bytes()
            (folder / "CHARACTER-BIBLE.md").write_text(
                "| Code | Name (EN order) | Role | Japanese voice | English voice (defaults) |\n"
                "|---|---|---|---|---|\n| KI | Mio Kisaragi | bookish | hesitant | quiet |\n", encoding="utf-8")
            Image.new("RGBA", (64, 48), "blue").save(folder / "background.png")
            Image.new("RGBA", (16, 32), (255, 0, 0, 128)).save(folder / "sprite.png")
            context_path = path.with_suffix(".context.json")
            context_path.write_text(json.dumps(dict(version=1, rows={"smoke:1": [dict(
                label="Synthetic scene", evidence="Acceptance fixture", background="background.png",
                sprite="sprite.png", screenshot="background.png", outfit="Test costume")]})), encoding="utf-8")
            context_before = context_path.read_bytes()
            root = tk.Tk()
            root.withdraw()
            # An unexpected dialog must fail instead of hanging unattended builds.
            with patch("tkinter.messagebox.showerror", side_effect=AssertionError("Unexpected error dialog")), \
                 patch("tkinter.messagebox.askyesno", side_effect=AssertionError("Unexpected QA dialog")):
                desk = ReviewDesk(root, folder)
                root.update()
                report["tk"] = root.tk.call("info", "patchlevel")
                family = japanese_font(tkfont.families(root))
                report["japanese_font"] = family
                check(bool(family), "Japanese font available")
                check(desk.content_font.actual("family").casefold() == family.casefold(), "Japanese font selected")
                check(desk.dialogue.japanese_fields[1].get("1.0", "end-1c") == "二つ目\n続き", "Japanese text and line breaks")
                check(len(desk.dialogue.english_fields) == 3, "Three separate choice editors")
                check("bookish" in desk.bio.get("1.0", "end-1c"), "Speaker biography loaded")
                check(set(desk.scene_panel.photos) == {"background", "character", "capture"}, "Bundled Pillow/Tk renders all scene previews")
                desk.rows.selection_set("1")
                desk.select_row()
                check("no verified mapping" in desk.context_status.cget("text"), "Unmapped row explains missing art")
                desk.find_scene_art()
                check(desk.row_index == 0 and set(desk.scene_panel.photos) == {"background", "character", "capture"}, "Find mapped scene restores previews")
                check(path.read_bytes() == before and not desk.sheet.changed, "Opening leaves CSV byte exact")
                field = desk.dialogue.english_fields[1]
                field.delete("1.0", "end")
                field.insert("1.0", "Changed\nTwo lines\n")
                desk.rows.selection_set("1")
                desk.select_row()
                desk.dialogue.english_fields[0].insert("end-1c", " Again")
                with patch("tkinter.messagebox.askyesnocancel", return_value=None):
                    check(not desk.leave_sheet(), "Cancel navigation keeps pending edits")
                check(desk.save(), "Explicit save succeeds")
                root.update()
                saved = Sheet(path)
                check(saved.rows[0]["English"] == "Name {P}{opt}Changed{br}Two lines{br}{opt}Third", "Choices and Enter serialize to script tokens")
                check(saved.rows[1]["English"] == "Hello. Again", "Second row edit survives navigation")
                check(all(saved.rows[i][key] == row[key] for i, row in enumerate(original)
                          for key in columns if key != "English"), "Japanese, metadata, notes and extra columns preserved")
                check(path.read_bytes().startswith(b"\xef\xbb\xbf") and b"\r\n" in path.read_bytes(), "Windows CSV BOM and CRLF preserved")
                backups = list((folder / ".review-backups").glob("*.bak"))
                check(len(backups) == 1 and backups[0].read_bytes() == before, "Byte exact backup created")
                saved.edit(1, "English", "Pending")
                external = path.read_bytes() + b"\r\n"
                path.write_bytes(external)
                try:
                    saved.save()
                except ReviewError:
                    check(path.read_bytes() == external and saved.changed == [1], "External changes refused with pending edits retained")
                else:
                    raise AssertionError("External changes were overwritten")
                check(context_path.read_bytes() == context_before, "Scene context remains unchanged")
                report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1
