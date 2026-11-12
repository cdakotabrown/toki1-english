"""Paired, compact dialogue blocks with lossless script-token serialization."""
import tkinter as tk
from tkinter import ttk

from review_model import editor_to_script, script_to_editor


class DialogueEditor(ttk.Frame):
    def __init__(self, parent, font, on_change):
        super().__init__(parent)
        self.font = font
        self.on_change = on_change
        self.raw = False
        self._loading = True
        self._dirty = False
        self._original = ""
        self._japanese = ""
        self._kind = "line"
        self.english_fields = []
        self.japanese_fields = []
        self._pairs = []
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.mode = ttk.Label(controls, text="Dialogue")
        self.mode.pack(side="left")
        self.toggle = ttk.Button(controls, text="Raw tokens", command=self.toggle_raw)
        self.toggle.pack(side="right")
        headings = ttk.Frame(self)
        headings.pack(fill="x", pady=(0, 1))
        for column, title in enumerate(("JAPANESE · read only", "ENGLISH · editable")):
            headings.columnconfigure(column, weight=1, uniform="heading")
            ttk.Label(headings, text=title).grid(row=0, column=column, sticky="w")
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                background="#f4f5f8", height=210)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.load(dict(Japanese="", English="", Kind="line"))

    def _text(self, parent, text, editable):
        widget = tk.Text(parent, height=2, width=1, wrap="word", undo=True,
                         font=self.font, padx=4, pady=2, spacing1=0, spacing3=0,
                         takefocus=editable,
                         relief="flat", highlightthickness=1,
                         highlightbackground="#cdd3df")
        widget.insert("1.0", text)
        widget.edit_reset()
        widget.edit_modified(False)
        if editable:
            widget.bind("<<Modified>>", self._edited)
            widget.bind("<Tab>", lambda event: self._focus_step(event.widget, 1))
            widget.bind("<Shift-Tab>", lambda event: self._focus_step(event.widget, -1))
            widget.bind("<ISO_Left_Tab>", lambda event: self._focus_step(event.widget, -1))
            widget.bind("<FocusIn>", lambda event: self._reveal(event.widget))
        else:
            widget.configure(state="disabled")
        return widget

    def load(self, row):
        self._japanese = row.get("Japanese", "")
        self._kind = row.get("Kind", "line")
        self._render(row.get("English", ""))

    def _render(self, english):
        self._loading = True
        self._dirty = False
        self._original = english
        for widget in self.body.winfo_children():
            widget.destroy()
        self.english_fields, self.japanese_fields, self._pairs = [], [], []
        blocks = not self.raw and (self._kind == "choice" or "{opt}" in self._japanese or "{opt}" in english)
        jp = self._japanese.split("{opt}") if blocks else [self._japanese]
        en = english.split("{opt}") if blocks else [english]
        count = max(len(jp), len(en))
        self.block_label = "Choice" if self._kind == "choice" else "Message"
        self.mode.configure(text=f"{count} {self.block_label.lower()} block(s)" if blocks else ("Raw script tokens" if self.raw else "Dialogue"))
        self.toggle.configure(text="Reader view" if self.raw else "Raw tokens")
        for index in range(count):
            frame = ttk.LabelFrame(self.body, text=f"{self.block_label} {index + 1}", padding=2) if blocks else ttk.Frame(self.body)
            frame.pack(fill="x", pady=1 if blocks else 0)
            for column in range(2):
                frame.columnconfigure(column, weight=1, uniform="dialogue")
            japanese = jp[index] if index < len(jp) else ""
            translation = en[index] if index < len(en) else ""
            if not self.raw:
                japanese, translation = script_to_editor(japanese), script_to_editor(translation)
            left = self._text(frame, japanese, False)
            right = self._text(frame, translation, True)
            left.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
            right.grid(row=0, column=1, sticky="nsew")
            self.japanese_fields.append(left)
            self.english_fields.append(right)
            self._pairs.append((left, right))
        self._blocks = blocks
        self.canvas.yview_moveto(0)
        self._loading = False
        self.after_idle(self._fit_heights)

    def get_script(self):
        # Empty English must stay empty when just browsing a three-choice row;
        # merely showing three empty cards must not inject two separators.
        # Ctrl+S can arrive before Tk dispatches the queued Modified event.
        if any(widget.edit_modified() for widget in self.english_fields):
            self._dirty = True
        if not self._dirty:
            return self._original
        parts = [editor_to_script(widget.get("1.0", "end-1c")) for widget in self.english_fields]
        return "{opt}".join(parts) if self._blocks else parts[0]

    def toggle_raw(self):
        english = self.get_script()
        self.raw = not self.raw
        self._render(english)

    def _edited(self, event):
        widget = event.widget
        modified = widget.edit_modified()
        widget.edit_modified(False)
        if self._loading or not modified:
            return
        self._dirty = True
        self._fit_heights()
        self.on_change()

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        self._fit_heights()

    def _focus_step(self, widget, direction):
        index = self.english_fields.index(widget) + direction
        if 0 <= index < len(self.english_fields):
            target = self.english_fields[index]
            target.focus_set()
            self._reveal(target)
        else:
            target = widget.tk_focusNext() if direction > 0 else widget.tk_focusPrev()
            if target:
                target.focus_set()
        return "break"

    def _reveal(self, widget):
        frame = widget.master
        height = max(1, self.body.winfo_height())
        top = self.canvas.canvasy(0)
        if frame.winfo_y() < top:
            self.canvas.yview_moveto(frame.winfo_y() / height)
        elif frame.winfo_y() + frame.winfo_height() > top + self.canvas.winfo_height():
            offset = max(0, frame.winfo_y() + frame.winfo_height() - self.canvas.winfo_height())
            self.canvas.yview_moveto(offset / height)

    def _fit_heights(self):
        if not self.winfo_exists():
            return
        for pair in self._pairs:
            lines = 2
            for widget in pair:
                width = max(100, widget.winfo_width() - 10)
                text = widget.get("1.0", "end-1c")
                wrapped = sum(max(1, (self.font.measure(line) + width - 1) // width) for line in text.split("\n"))
                lines = max(lines, wrapped)
            height = min(6 if self._blocks else 12, lines)
            for widget in pair:
                if int(widget.cget("height")) != height:
                    widget.configure(height=height)
