"""Offline Windows-friendly localization review desk. No network or game runtime."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

from review_model import (ReviewError, SceneContext, Sheet, audit, bible_for, encoded_length,
                          japanese_font, read_bible,
                          script_to_editor)
from scene_panel import ScenePanel, layer_options
from dialogue_editor import DialogueEditor


class ReviewDesk:
    def __init__(self, root: tk.Tk, folder: Path | None):
        self.root = root
        self.folder = folder
        self.sheet = None
        self.row_index = None
        self.entries = []
        self.context = None
        self.imported_context = None
        self.auto_context = None
        self.active_context = None
        self.loading = False
        self.search = tk.StringVar()
        self.only_issues = tk.BooleanVar()
        self.variant = tk.StringVar()
        self.status = tk.StringVar(value="Open a sheets folder to begin.")
        self.root.title("Tokimeki • Translation Review")
        width = min(1450, max(800, root.winfo_screenwidth() - 60))
        height = min(920, max(600, root.winfo_screenheight() - 100))
        self.root.geometry(f"{width}x{height}+20+20")
        self.root.minsize(min(1050, width), min(720, height))
        family = japanese_font(tkfont.families(root))
        if family:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                tkfont.nametofont(name, root=root).configure(family=family)
        self.content_font = tkfont.Font(root=root, family=family or "TkDefaultFont", size=12)
        root.option_add("*Font", "TkDefaultFont")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f5f8")
        style.configure("TLabel", background="#f4f5f8", foreground="#233047")
        style.configure("Heading.TLabel", font=(family or "TkDefaultFont", 11, "bold"))
        style.configure("TButton", padding=(5, 2))
        style.configure("TCheckbutton", padding=(2, 0))
        style.configure("TNotebook.Tab", padding=(6, 2))
        style.configure("TCombobox", padding=(3, 1))
        style.configure("Treeview", font="TkDefaultFont", rowheight=tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace") + 2)
        style.configure("Treeview.Heading", font="TkHeadingFont")
        toolbar = ttk.Frame(root, padding=4)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="TRANSLATION REVIEW", style="Heading.TLabel").pack(side="left", padx=(0, 8))
        for label, action in (("Open sheets folder", self.open_folder),
                              ("Import scene context", self.import_context),
                              ("Save CSV  Ctrl+S", self.save)):
            ttk.Button(toolbar, text=label, command=action).pack(side="left", padx=2)
        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=4)
        left, center, right = (ttk.Frame(panes, padding=3) for _ in range(3))
        panes.add(left, weight=1)
        panes.add(center, weight=5)
        panes.add(right, weight=3)
        ttk.Label(left, text="SCRIPT SHEETS", style="Heading.TLabel").pack(anchor="w")
        self.sheets = ttk.Treeview(left, show="tree", selectmode="browse", height=30)
        self.sheets.column("#0", width=180)
        self.sheets.pack(fill="both", expand=True, pady=3)
        self.sheets.bind("<<TreeviewSelect>>", self.select_sheet)
        ttk.Label(center, text="LINE AUDIT", style="Heading.TLabel").pack(anchor="w")
        bar = ttk.Frame(center)
        bar.pack(fill="x", pady=3)
        entry = ttk.Entry(bar, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", lambda *_: self.refresh_rows())
        ttk.Checkbutton(bar, text="QA issues", variable=self.only_issues,
                        command=self.refresh_rows).pack(side="left", padx=3)
        ttk.Label(center, text="Filter by JP, English, speaker, status or row ID").pack(anchor="w")
        self.rows = ttk.Treeview(center, columns=("speaker", "jp", "state"),
                                 show="headings", selectmode="browse", height=11)
        for key, label, width in (("speaker", "Speaker", 115), ("jp", "Japanese / file order", 300), ("state", "Status", 90)):
            self.rows.heading(key, text=label)
            self.rows.column(key, width=width)
        self.rows.pack(fill="both", expand=True, pady=3)
        self.rows.bind("<<TreeviewSelect>>", self.select_row)
        self.identity = ttk.Label(center, text="No line selected", wraplength=620)
        self.identity.pack(anchor="w", pady=2)
        self.dialogue = DialogueEditor(center, self.content_font, self.dialogue_edited)
        self.dialogue.pack(fill="both", expand=True)
        ttk.Label(center, text="Enter = line break. Choices save their separators automatically.").pack(anchor="w", pady=(2, 0))
        ttk.Label(center, text="REVIEW NOTES • required when changing a final line").pack(anchor="w", pady=(3, 0))
        self.notes = self.text_box(center, 2)
        self.notes.pack(fill="x", pady=2)
        self.notes.bind("<<Modified>>", self.edited)
        self.qa = ttk.Label(center, text="", wraplength=620)
        self.qa.pack(fill="x", pady=3)
        reference_tabs = ttk.Notebook(right)
        reference_tabs.pack(fill="both", expand=True)
        scene_page, bible_page = ttk.Frame(reference_tabs), ttk.Frame(reference_tabs)
        reference_tabs.add(scene_page, text="Scene context")
        reference_tabs.add(bible_page, text="Character bible")
        self.context_status = ttk.Label(scene_page, text="Open a sheets folder to load scene context.", wraplength=370)
        self.context_status.pack(fill="x", pady=2)
        ttk.Button(scene_page, text="Find mapped scene", command=self.find_scene_art).pack(fill="x", pady=2)
        self.variants = ttk.Combobox(scene_page, textvariable=self.variant, state="readonly")
        self.variants.pack(fill="x", pady=3)
        self.variants.bind("<<ComboboxSelected>>", lambda _: self.show_scene())
        self.scene_panel = ScenePanel(scene_page, root)
        self.scene_panel.pack(fill="both", expand=True, pady=2)
        self.scene_notes = ttk.Label(scene_page, text="", wraplength=370)
        self.scene_notes.pack(fill="x", pady=2)
        ttk.Button(scene_page, text="Attach scene to this row…", command=self.attach_scene).pack(fill="x", pady=3)
        self.bio = self.text_box(bible_page, 14)
        self.bio.pack(fill="both", expand=True)
        ttk.Label(root, textvariable=self.status, padding=4, wraplength=1300).pack(fill="x")
        root.bind("<Control-s>", self.save)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if folder and folder.exists():
            self.load_folder(folder)
        if not family:
            self.status.set("No Japanese font found. Install Noto Sans CJK JP (Linux), or Meiryo/Yu Gothic (Windows), then restart the reviewer.")

    def text_box(self, parent, height):
        return tk.Text(parent, height=height, width=25, wrap="word", undo=True,
                       font=self.content_font, padx=4, pady=2, spacing1=0,
                       spacing3=0,
                       relief="flat", highlightthickness=1, highlightbackground="#cdd3df")

    @staticmethod
    def read_only(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def leave_sheet(self):
        self.capture_edits()
        if not self.sheet or not self.sheet.changed:
            return True
        result = messagebox.askyesnocancel("Unsaved English", "Save changes to this CSV before leaving it?", parent=self.root)
        if result is None:
            return False
        if result:
            return self.save()
        return True

    def open_folder(self):
        folder = filedialog.askdirectory(title="Choose localization sheets folder", parent=self.root)
        if folder and self.leave_sheet():
            self.load_folder(Path(folder))

    def load_folder(self, folder):
        self.folder = Path(folder).resolve()
        self.files = sorted(self.folder.rglob("*.csv"))
        self.files = [p for p in self.files if ".review-backups" not in p.parts]
        self.entries = []
        self.auto_context = None
        for parent in (self.folder, *self.folder.parents):
            candidates = [parent / "scene-context.json", parent / "extracted_assets/reviewer/scene-context.json"]
            found = next((path for path in candidates if path.is_file()), None)
            if found:
                try:
                    self.auto_context = SceneContext(found)
                except Exception as exc:
                    messagebox.showerror("Generated context unavailable", str(exc), parent=self.root)
                break
        for parent in (self.folder, *self.folder.parents):
            bible = parent / "CHARACTER-BIBLE.md"
            if bible.is_file():
                self.entries = read_bible(bible)
                break
        self.sheets.delete(*self.sheets.get_children())
        self.sheet, self.row_index = None, None
        self.refresh_rows()
        self.clear_editor()
        for i, path in enumerate(self.files):
            self.sheets.insert("", "end", iid=str(i), text=path.relative_to(self.folder).as_posix())
        self.status.set(f"{len(self.files)} CSVs found. Character bible: {'loaded' if self.entries else 'not found; place CHARACTER-BIBLE.md alongside the sheets folder'}. Nothing saved automatically.")
        if self.files:
            self.sheets.selection_set("0")
            self.find_scene_art(notify=False)

    def find_scene_art(self, notify=True):
        """Select a row with supplied art; opening a folder starts with one if available."""
        self.capture_edits()
        paths = ([self.sheet.path] if self.sheet else []) + [path for path in self.files if not self.sheet or path != self.sheet.path]
        for path in paths:
            try:
                context = self.imported_context or SceneContext(path.with_suffix(".context.json"))
                if not context.data["rows"] and not self.auto_context:
                    continue
                sheet = self.sheet if self.sheet and self.sheet.path == path else Sheet(path)
                target = None
                for index, row in enumerate(sheet.rows):
                    source = context if context.variants(row["ID"]) or not self.auto_context else self.auto_context
                    for variant in source.variants(row["ID"]):
                        backgrounds, sprites = layer_options(source, variant)
                        if backgrounds or sprites or variant.get("screenshot"):
                            target = index
                            break
                    if target is not None:
                        break
            except (OSError, ValueError, ReviewError):
                continue
            if target is None:
                continue
            self.sheets.selection_set(str(self.files.index(path)))
            self.select_sheet()
            if not self.sheet or self.sheet.path != path:  # Navigation was cancelled.
                return
            self.only_issues.set(False)
            self.search.set("")
            self.refresh_rows()
            self.rows.selection_set(str(target))
            self.rows.see(str(target))
            self.select_row()
            return
        if notify:
            self.context_status.configure(text="No rows with mapped art found in this folder. Import scene-context.json and keep its image folders beside it.")

    def select_sheet(self, _=None):
        selected = self.sheets.selection()
        if not selected:
            return
        path = self.files[int(selected[0])]
        if self.sheet and self.sheet.path == path:
            return
        if not self.leave_sheet():
            if self.sheet:
                self.sheets.selection_set(str(self.files.index(self.sheet.path)))
            return
        try:
            sheet = Sheet(path)
            context = self.imported_context or SceneContext(path.with_suffix(".context.json"))
        except Exception as exc:
            messagebox.showerror("Cannot open sheet", str(exc), parent=self.root)
            return
        self.sheet, self.context, self.row_index = sheet, context, None
        self.search.set("")
        self.refresh_rows()
        self.clear_editor()
        if self.rows.get_children():
            self.rows.selection_set(self.rows.get_children()[0])

    def refresh_rows(self):
        if not hasattr(self, "rows"):
            return
        self.rows.delete(*self.rows.get_children())
        if not self.sheet:
            return
        query = self.search.get().casefold()
        changed = set(self.sheet.changed)
        for i, row in enumerate(self.sheet.rows):
            if query and query not in " ".join(row.values()).casefold():
                continue
            if self.only_issues.get() and not audit(row):
                continue
            preview = script_to_editor(row["Japanese"]).replace("\n", " ↵ ").replace("{opt}", " | ")
            self.rows.insert("", "end", iid=str(i), values=(row.get("Speaker", "Unknown"), preview, ("* " if i in changed else "") + row.get("Status", "")))
        if self.row_index is not None and self.rows.exists(str(self.row_index)):
            self.rows.selection_set(str(self.row_index))

    def clear_editor(self):
        self.loading = True
        self.row_index = None
        self.dialogue.load(dict(Japanese="", English="", Kind="line"))
        for widget in (self.notes, self.bio):
            self.read_only(widget, "")
        self.identity.configure(text="No line selected")
        self.qa.configure(text="")
        self.variants.configure(values=())
        self.variant.set("")
        self.scene_panel.clear()
        self.scene_notes.configure(text="No exact row mapping available.")
        self.loading = False

    def select_row(self, _=None):
        selected = self.rows.selection()
        if not selected:
            return
        self.capture_edits()
        self.row_index = int(selected[0])
        row = self.sheet.rows[self.row_index]
        self.loading = True
        self.dialogue.load(row)
        for widget, field in ((self.notes, "Notes"),):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            text = row.get(field, "")
            widget.insert("1.0", text)
            widget.edit_reset()
            widget.edit_modified(False)
            if field not in self.sheet.columns:
                widget.configure(state="disabled")
        self.loading = False
        self.identity.configure(text=f"{row.get('Speaker') or 'Speaker unknown'} · {row.get('Kind', '')} · {row.get('Status', '')}\n{row['ID']}")
        entry = bible_for(row.get("Speaker", ""), self.entries)
        bio = "Speaker bio unknown. No character is inferred from the file name."
        if entry:
            bio = f"{entry['name']}\n\n{entry['role']}\n\nJAPANESE VOICE\n{entry['japanese_voice']}\n\nENGLISH VOICE\n{entry['english_voice']}"
        self.read_only(self.bio, bio)
        self.active_context = self.context
        if not self.context.variants(row["ID"]) and self.auto_context:
            self.active_context = self.auto_context
        variants = self.active_context.variants(row["ID"])
        self.variants.configure(values=[f"{i+1}. {v.get('label', 'Unnamed scene')}" for i, v in enumerate(variants)])
        self.variant.set("")
        if variants:
            self.variants.current(0)
        self.show_scene()
        self.update_qa()

    def capture_edits(self):
        if self.loading or not self.sheet or self.row_index is None:
            return
        self.sheet.edit(self.row_index, "English", self.dialogue.get_script())
        if "Notes" in self.sheet.columns:
            self.sheet.edit(self.row_index, "Notes", self.notes.get("1.0", "end-1c"))

    def dialogue_edited(self):
        if self.loading or not self.sheet or self.row_index is None:
            return
        self.sheet.edit(self.row_index, "English", self.dialogue.get_script())
        self.mark_row()

    def edited(self, event):
        widget = event.widget
        modified = widget.edit_modified()
        widget.edit_modified(False)
        if self.loading or not modified or self.row_index is None:
            return
        self.sheet.edit(self.row_index, "Notes", widget.get("1.0", "end-1c"))
        self.mark_row()

    def mark_row(self):
        row = self.sheet.rows[self.row_index]
        if self.rows.exists(str(self.row_index)):
            self.rows.set(str(self.row_index), "state", ("* " if self.row_index in self.sheet.changed else "") + row.get("Status", ""))
        self.update_qa()

    def update_qa(self):
        row = self.sheet.rows[self.row_index]
        issues = audit(row)
        self.qa.configure(text=f"{encoded_length(row['English'])} encoded bytes · in-place budget {row.get('MaxBytes', '?')}\n" + ("\n".join(f"{issue.level.upper()}: {issue.message}" for issue in issues) or "Token, charset and length checks passed."))
        self.status.set(f"{self.sheet.path.name} · {len(self.sheet.changed)} unsaved row(s). CSV order is storage order, not proven dialogue chronology. Ctrl+S saves this sheet only.")

    def show_scene(self):
        if self.row_index is None:
            self.scene_panel.clear()
            return
        context = self.active_context or self.context
        variants = context.variants(self.sheet.rows[self.row_index]["ID"])
        library = self.auto_context or self.imported_context
        available = f"Scene library loaded: {len(library.data['rows'])} mapped row IDs." if library else "Automatic scene library not loaded. Import scene-context.json to load it."
        index = self.variants.current()
        if not variants or index < 0:
            self.context_status.configure(text=available + " This row has no verified mapping. Use Find mapped scene to view available art.")
            self.scene_panel.clear()
            self.scene_notes.configure(text="Background, expression and outfit are unknown. No image is guessed from the speaker or neighboring rows.")
            return
        variant = variants[index]
        self.context_status.configure(text="Scene mapping found for this row. " + (available if library else "Using supplied row context."))
        self.scene_notes.configure(text=f"Source: {variant.get('evidence') or 'unspecified'}\nBackground and character selections are independent. Reference expressions do not establish the line's runtime expression.")
        self.scene_panel.show(context, variant)

    def import_context(self):
        path = filedialog.askopenfilename(title="Open scene-context JSON", filetypes=[("Scene context", "*.json")], parent=self.root)
        if not path:
            return
        try:
            imported = SceneContext(Path(path))
            if imported.data.get("generated"):
                self.auto_context = imported
                self.imported_context = None
                if self.sheet:
                    self.context = SceneContext(self.sheet.path.with_suffix(".context.json"))
            else:
                self.imported_context = imported
                self.context = imported
            if self.row_index is not None:
                self.select_row()
        except Exception as exc:
            messagebox.showerror("Invalid scene context", str(exc), parent=self.root)

    def attach_scene(self):
        if self.row_index is None:
            return
        screenshot = filedialog.askopenfilename(title="Choose a screenshot for this exact row", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp")], parent=self.root)
        if not screenshot:
            return
        label = simpledialog.askstring("Scene variant", "Scene label (include branch/season if known):", parent=self.root)
        if not label:
            return
        evidence = simpledialog.askstring("Context evidence", "Source and why this screenshot belongs to this row:", parent=self.root)
        if not evidence:
            return
        outfit = simpledialog.askstring("Outfit", "Outfit, if known (leave blank if unknown):", parent=self.root)
        if outfit is None:
            return
        if not messagebox.askokcancel("Save scene mapping", "Save this context attachment now? The CSV English will not be saved by this action.", parent=self.root):
            return
        try:
            relative = os.path.relpath(screenshot, self.context.path.parent)
        except ValueError:
            relative = screenshot  # Different Windows drive: document as absolute.
        try:
            self.context.add(self.sheet.rows[self.row_index]["ID"], dict(label=label, evidence=evidence, outfit=outfit, screenshot=relative.replace(os.sep, "/")))
            self.select_row()
            self.variants.current(len(self.context.variants(self.sheet.rows[self.row_index]["ID"])) - 1)
            self.show_scene()
        except Exception as exc:
            messagebox.showerror("Context not saved", str(exc), parent=self.root)

    def save(self, _=None):
        if not self.sheet:
            return True
        self.capture_edits()
        errors = [(self.sheet.rows[i]["ID"], issue.message) for i in self.sheet.changed for issue in audit(self.sheet.rows[i]) if issue.level == "error"]
        allow = False
        if errors:
            details = "\n".join(f"{rid}: {message}" for rid, message in errors[:8])
            allow = messagebox.askyesno("Save with QA errors?", f"{len(errors)} QA error(s) in changed rows:\n\n{details}\n\nSave these edits anyway? Status will remain unchanged.", parent=self.root)
            if not allow:
                return False
        try:
            count = len(self.sheet.changed)
            backup = self.sheet.save(allow_issues=allow)
        except Exception as exc:
            messagebox.showerror("CSV not saved", str(exc), parent=self.root)
            return False
        self.refresh_rows()
        self.status.set(f"Saved {count} changed row(s) to {self.sheet.path}." + (f" Backup: {backup}" if backup else ""))
        return True

    def close(self):
        if self.leave_sheet():
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheets", type=Path)
    parser.add_argument("--self-test", type=Path, metavar="REPORT", help="Test the packaged UI with temporary synthetic data and write a JSON report")
    parser.add_argument("--check", type=Path, help="Validate/load sheets without opening a window or writing files")
    args = parser.parse_args()
    if args.self_test:
        from packaged_smoke import run
        raise SystemExit(run(args.self_test))
    if args.check:
        files = sorted(args.check.rglob("*.csv")) if args.check.is_dir() else [args.check]
        counts = Counter()
        for path in files:
            sheet = Sheet(path)
            counts["sheets"] += 1
            counts["rows"] += len(sheet.rows)
            counts["unknown_speakers"] += sum(not row.get("Speaker") for row in sheet.rows)
        print(json.dumps(counts, indent=2))
        return
    folder = args.sheets
    if folder is None and not getattr(sys, "frozen", False):
        from repo_paths import english_rel   # on sys.path via review_model
        root = Path(__file__).resolve().parents[2]
        candidate = root / english_rel("translation/localization/sheets", root)
        if candidate.exists():
            folder = candidate
    root = tk.Tk()
    ReviewDesk(root, folder)
    root.mainloop()


if __name__ == "__main__":
    main()
