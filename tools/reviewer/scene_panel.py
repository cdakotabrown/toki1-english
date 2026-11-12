"""Independent background/character/capture previews for the review desk."""
from tkinter import ttk

from review_model import ReviewError


def layer_options(context, variant):
    backgrounds = variant.get("background_options", [])
    character = context.data.get("characters", {}).get(variant.get("character_id", ""), {})
    sprites = variant.get("sprite_options", character.get("options", []))
    if variant.get("background"):
        backgrounds = [dict(label="Supplied background", image=variant["background"], certainty="Supplied context")]
    if variant.get("sprite"):
        sprites = [dict(label=variant.get("outfit") or "Supplied character sprite", image=variant["sprite"], certainty="Supplied context")]
    for options in (backgrounds, sprites):
        if not isinstance(options, list) or any(not isinstance(option, dict) or
                not isinstance(option.get("image"), str) or
                not isinstance(option.get("label"), str) for option in options):
            raise ReviewError("Scene layer options need label and image strings")
    return backgrounds, sprites


class ScenePanel(ttk.Frame):
    def __init__(self, parent, root):
        super().__init__(parent)
        self.root = root
        self.context = None
        self.photos = {}
        self.options = {"background": [], "character": []}
        self.selectors, self.images, self.details = {}, {}, {}
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True)
        layers = ttk.Frame(tabs, padding=3)
        capture = ttk.Frame(tabs, padding=3)
        tabs.add(layers, text="Separate layers")
        tabs.add(capture, text="Screenshot")
        for key, title in (("background", "BACKGROUND"), ("character", "CHARACTER / COSTUME / FACE")):
            frame = ttk.LabelFrame(layers, text=title, padding=3)
            frame.pack(fill="x", pady=2)
            selector = ttk.Combobox(frame, state="readonly", width=43)
            selector.pack(fill="x")
            selector.bind("<<ComboboxSelected>>", lambda _, layer=key: self.render_layer(layer))
            self.selectors[key] = selector
            image = ttk.Label(frame, text="Unknown", anchor="center")
            image.pack(fill="x", pady=2)
            self.images[key] = image
            details = ttk.Label(frame, text="", wraplength=370)
            details.pack(fill="x")
            self.details[key] = details
        self.capture = ttk.Label(capture, text="No screenshot attached", anchor="center")
        self.capture.pack(fill="both", expand=True)

    def clear(self):
        self.photos.clear()
        for key in self.options:
            self.options[key] = []
            self.selectors[key].configure(values=())
            self.selectors[key].set("")
            self.images[key].configure(image="", text="Unknown")
            self.details[key].configure(text="No established scene binding.")
        self.capture.configure(image="", text="No screenshot attached")

    def show(self, context, variant):
        previous = {key: selector.get() for key, selector in self.selectors.items()}
        self.clear()
        self.context = context
        try:
            backgrounds, sprites = layer_options(context, variant)
        except (ReviewError, AttributeError, TypeError) as exc:
            self.details["background"].configure(text=f"Invalid layer context: {exc}")
            return
        for key, options in (("background", backgrounds), ("character", sprites)):
            self.options[key] = options
            labels = [option["label"] for option in options]
            self.selectors[key].configure(values=labels)
            if labels:
                index = labels.index(previous[key]) if previous[key] in labels else 0
                self.selectors[key].current(index)
                self.render_layer(key)
        if variant.get("screenshot"):
            self.draw_image("capture", self.capture, variant["screenshot"], (430, 400))

    def draw_image(self, key, widget, path, bounds):
        try:
            from PIL import Image, ImageTk
            with Image.open(self.context.image_path(path)) as source:
                image = source.convert("RGBA")
            # Checkerboard makes portrait transparency visible. It is a UI
            # backdrop and is never exported as game artwork.
            scale = min(bounds[0] / image.width, bounds[1] / image.height, 2)
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.NEAREST)
            checker = Image.new("RGBA", image.size)
            from PIL import ImageDraw
            draw = ImageDraw.Draw(checker)
            for y in range(0, image.height, 12):
                for x in range(0, image.width, 12):
                    color = "#e2e5eb" if (x // 12 + y // 12) % 2 else "#f5f6f9"
                    draw.rectangle((x, y, x + 11, y + 11), fill=color)
            checker.alpha_composite(image)
            self.photos[key] = ImageTk.PhotoImage(checker, master=self.root)
            widget.configure(image=self.photos[key], text="")
        except Exception as exc:
            widget.configure(image="", text=f"Preview unavailable:\n{exc}", wraplength=360)

    def render_layer(self, key):
        index = self.selectors[key].current()
        if index < 0 or index >= len(self.options[key]):
            return
        option = self.options[key][index]
        self.details[key].configure(text=option.get("certainty") or "Supplied context; runtime state unverified")
        self.draw_image(key, self.images[key], option["image"], (400, 190 if key == "background" else 225))
