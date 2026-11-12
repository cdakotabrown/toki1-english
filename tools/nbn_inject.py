#!/usr/bin/env python3
"""nbn_inject.py - English for the text baked into the sprite sheets.

A manifest (src/patch/art/<NBN>/manifest.json) describes a sprite file and
the CELLS of it that carry Japanese text.  A cell names

  surface   where its pixels are: "page": N (4-bpp 128x128 pages of 8 KB,
            or `page_bytes`), "offset": "0x24000" (one page at a file
            offset) or "offset": ["0x28000", "0x2c000"] (pages that sit
            side by side in VRAM, addressed as one wider surface: a label
            that crosses a page edge);
  box       x, y, w, h: the retail cell (the label's own box, never a pixel
            wider); the Japanese is erased and the English drawn inside it;
  colours   `fg` (the stroke index), optional `outline` (a 1-px ring in
            that index around the strokes: the hollow kana of the buttons),
            `erase` (the indices the Japanese used; default fg + outline),
            `bg` ("keep" = in-paint from the surrounding pixels, or an
            index), optional `shadow` (an index drawn one pixel down-right of
            the strokes, as the HUD kanji have), the block's CLUT (`clut`: "exe" = the 16 rows at
            D_800CC520 of the exe, "exe@ADDR" = `entries` colours at that
            RAM address of the exe, "file:OFFSET" = 256 RGB1555 colours in
            the NBN, "retail:CDROM/DIR/FILE@OFFSET" = colours another
            retail file uploads (the CLUT a sprite is drawn with when it
            is not the page's own file: TAMA's banner, TASETU's row 15),
            "none");
  copies    optional [{"file", "base"}]: the same picture repeated in other
            files at a byte offset; every cell is applied there too;
  text      the English, `align` (center / left / right / glyph = at the
            retail glyph's left edge / an integer pixel column), `valign`
            ("glyph" = centred on the retail glyph's rows (default),
            "center", or a row offset);
            a text wider than the box is drawn with 1-px tighter spacing
            and refused if it still does not fit.

Two modes:

  --render   manifest -> src/patch/art/<NBN>/<cell>.png: OUR text rendered
             from the patch's 12-px Latin font (tools/patch/font) as an
             RGBA image of the box's size, positioned against the retail
             glyph; text pixels in the fg colour, the ring in the outline
             colour, the rest transparent.  These PNGs are what the repo
             carries: our pixels in two palette colours, never game art.
  (default)  manifest + PNGs -> build/patch/files/<NBN>: starting from the
             retail file every time, the retail glyph is erased (each
             erased pixel takes the value of its nearest non-glyph
             neighbours: along the axis whose two ends agree, so a
             horizontal or a vertical gradient continues under it), then
             every opaque PNG pixel is written as the fg or outline index
             (whichever render colour it is nearest to).  The file keeps
             its exact size; a file whose retail bytes carry a valid
             block checksum (the u16 byte sum the loaders verify with
             block_checksum_check) gets it re-stamped (`"checksum": false`
             in the manifest turns that off).  build_patched.py runs this on every manifest.
  scale     optional: N > 1 draws every font pixel as an N x N block (the
            big banners: KARI's disqualified, TAMA's course-out); fg_rows
            then has one index per OUTPUT row;
  fg_rows   optional: one CLUT index per row of the 12-px font (a vertical
            gradient, as the staff roll's glyphs have) instead of one fg;
            the PNG carries those CLUT colours and every opaque pixel is
            written as the nearest of them or the outline;
  clear     optional manifest-level [{"offset", "bytes"}]: ranges zeroed
            before the cells are drawn (a glyph page rebuilt from scratch);
  sprite_frames  optional: the file's own sprite frames (cel lists in the
            format sprite_slot_disp draws) rebuilt from English strings
            laid out with the cells' glyphs, one cel per character; see
            apply_sprite_frames (the staff roll, STAFF_R.NBN).
  cel_remap optional: point the file's own sprite frames' cels at English
            word cells (labels assembled from glyph cells shared between
            labels: NAME_ENT); see apply_cel_remap.
  frame_layout optional: lay chosen frames out again, left to right, from
            retail cels ("@0xTILE") and English word cells, centred as the
            retail frame was (BUNKA_SD's speech-topic boards); see
            apply_frame_layout.  A cell's "tile_y" (the piece's top row when the
            text box is only its interior) and "tile_page" (the page index of
            the file's page list) give its tile.
  copy_rects optional: move a rectangle of the file's own retail pixels
            (a blank word board) into unused (all-zero) page space before the
            cells are drawn; see copy_rects.
  face      optional: hand-authored display lettering instead of the 12-px
            font (tools/patch/artface.py): "face": "display_caps" names
            tools/patch/font/display_caps.txt, "face_sha1" its SHA-1 (the
            declared source; a face file that no longer hashes so is
            refused, in --render too), "cap" the cap height in px, "gap" /
            "space" / "slant" / "xscale" the face's layout parameters, "outline_w" the
            keyline width, "ramp" [[fraction, index], ...] the palette ramp
            down the cap height (one index per output row, from it),
            "shadow_dx" / "shadow_dy" the shadow offset.  The provenance
            gate re-renders the PNG from the face file + these parameters.
  pixel_font optional: a small hand-drawn bitmap face instead of the
            12-px font, in latin12's format (tools/patch/font/<name>.txt;
            "tiny_caps": 7-px capitals in 8-px rows, the magazine's genre
            tags); the provenance gate renders it like the 12-px font.
  mirror    optional: true renders the cell left-right reversed (the
            surface stores that picture mirrored: TAMA.BIN's name plates);
            the provenance gate re-renders it the same way.
  offset    may also be a list of ROWS of pages ([["0x0","0x4000","0x8000"],
            ["0xc000","0x10000","0x14000"]]: a 384x256 plane of 128x128
            pages laid 3 x 2) for a cell that crosses a page row.
  --preview DIR  also write DIR/<NBN>_<surface>.png: the touched surfaces
             before | after, in the CLUT's colours (x3), for review.

  python3 tools/patch/nbn_inject.py --render src/patch/art/MAINROM/manifest.json
  python3 tools/patch/nbn_inject.py src/patch/art/*/manifest.json --preview build/patch/art/preview
"""
import argparse
import json
import struct
from collections import Counter
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import artface  # noqa: E402
import fontgen  # noqa: E402
import tilemap_panel  # noqa: E402

EXTRACTED = DECOMP / "assets" / "extracted_iso"
OUT_FILES = ROOT / "build" / "patch" / "files"
EXE = DECOMP / "disks" / "SLPS_000.65"
EXE_CLUT = 0x800CC520


def rgb1555(v):
    return ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31)


def load_clut(spec: dict, nbn: bytes, fg: int):
    """[(r,g,b)] of the block's CLUT (16 or 256 entries) or None"""
    src = spec.get("source", "") if isinstance(spec, dict) else str(spec)
    if src == "exe":
        exe = EXE.read_bytes()
        off = EXE_CLUT - 0x80041000 + 0x800
        rows = [[rgb1555(struct.unpack_from("<H", exe, off + (r * 16 + i) * 2)[0])
                 for i in range(16)] for r in range(16)]
        row = spec.get("row", "auto")
        if row == "auto":
            row = max(range(16), key=lambda r: sum(rows[r][fg]))
        return rows[int(row)]
    if src.startswith("exe@"):                 # a CLUT the exe uploads (RAM address)
        exe = EXE.read_bytes()
        off = int(src[4:], 16) - 0x80041000 + 0x800
        n = int(spec.get("entries", 256))
        return [rgb1555(struct.unpack_from("<H", exe, off + 2 * i)[0]) for i in range(n)]
    if src.startswith("file:"):
        off = int(src[5:], 16)
        n = int(spec.get("entries", 256))
        return [rgb1555(struct.unpack_from("<H", nbn, off + 2 * i)[0]) for i in range(n)]
    if src.startswith("retail:"):             # another retail file's CLUT ("retail:CDROM/X/Y.BIN@0x1E00")
        rel, off = src[7:].rsplit("@", 1)
        other = (EXTRACTED / rel).read_bytes()
        n = int(spec.get("entries", 256))
        return [rgb1555(struct.unpack_from("<H", other, int(off, 16) + 2 * i)[0]) for i in range(n)]
    return None


# --- surfaces ---------------------------------------------------------------------

class Surface:
    """one or more 128-px pages side by side (as VRAM holds them)"""

    def __init__(self, data: bytearray, bpp: int, offsets, w=128, h=128):
        offsets = list(offsets)
        if offsets and isinstance(offsets[0], list):      # rows of pages
            self.grid = [list(r) for r in offsets]
        else:
            self.grid = [offsets]
        if len({len(r) for r in self.grid}) != 1:
            raise SystemExit("[nbn] page grid rows differ in length")
        self.d, self.bpp, self.pw, self.ph = data, bpp, w, h
        self.offs = [o for r in self.grid for o in r]
        self.w = w * len(self.grid[0])
        self.h = h * len(self.grid)

    def _addr(self, x, y):
        off = self.grid[y // self.ph][x // self.pw]
        x %= self.pw
        y %= self.ph
        if self.bpp == 4:
            return off + y * (self.pw // 2) + (x >> 1), x & 1
        return off + y * self.pw + x, 0

    def get(self, x, y):
        i, odd = self._addr(x, y)
        if self.bpp == 4:
            return (self.d[i] >> 4) if odd else (self.d[i] & 15)
        return self.d[i]

    def set(self, x, y, v):
        i, odd = self._addr(x, y)
        if self.bpp == 4:
            self.d[i] = ((self.d[i] & 0x0F) | ((v & 15) << 4)) if odd else ((self.d[i] & 0xF0) | (v & 15))
        else:
            self.d[i] = v & 0xFF


def _off(v):
    return int(v, 16) if isinstance(v, str) else int(v)


class PieceSurface:
    """rectangles of one or more pages drawn side by side on screen (a
    label the sprite record assembles from pieces: TITLE's オ|プ|ション),
    addressed as one virtual strip; piece i keeps its own index family"""

    def __init__(self, parts, h):
        self.parts = parts                      # [(Surface, x, y, w, spec)]
        self.h = h
        self.w = sum(p[3] for p in parts)
        self.bpp = parts[0][0].bpp
        self.offs = sorted({o for p in parts for o in p[0].offs})

    def locate(self, x):
        for i, (s, px, py, w, spec) in enumerate(self.parts):
            if x < w:
                return i, s, px + x, py
            x -= w
        raise IndexError(x)

    def get(self, x, y):
        i, s, sx, sy = self.locate(x)
        return s.get(sx, sy + y)

    def set(self, x, y, v):
        i, s, sx, sy = self.locate(x)
        s.set(sx, sy + y, v)


class TilemapSurface:
    """a mod/srn tile-map picture (tools/patch/tilemap_panel.py), decoded
    to its full plane; cells edit the plane and `commit` re-tiles it into
    the file bytes"""
    bpp = 8

    def __init__(self, data, spec, base):
        self.tm = tilemap_panel.Tilemap(data, spec, base)
        self.plane = self.tm.decode()
        self.w, self.h = self.tm.w, self.tm.h
        self.offs = []
        self.key = "tilemap_" + self.tm.name
        self.painted = set()            # pixels our lettering wrote

    def get(self, x, y):
        return self.plane[y][x]

    def set(self, x, y, v):
        self.plane[y][x] = v & 0xFF


_TILEMAPS = []          # [(data, base, name, TilemapSurface)]


def tilemap_surface(data, man, name, base=0):
    for d, b, n, s in _TILEMAPS:
        if d is data and b == base and n == name:
            return s
    specs = {t["name"]: t for t in man.get("tilemaps", [])}
    if name not in specs:
        raise SystemExit(f"[nbn] tilemap {name!r} is not in the manifest's \"tilemaps\"")
    s = TilemapSurface(data, specs[name], base)
    _TILEMAPS.append((data, base, name, s))
    return s


def commit_tilemaps(data, man, base=0):
    """re-tile every edited tile-map picture of `data`; the others of the
    same file are passed along so their bytes stay untouched"""
    notes = []
    names = [t["name"] for t in man.get("tilemaps", [])]
    surfs = [tilemap_surface(data, man, n, base) for n in names]
    for s in surfs:
        # the residue gate: inside the panel's text area no pixel of a text
        # index may survive that our lettering did not write (a Japanese
        # stroke left outside every cell box)
        spec = next(t for t in man["tilemaps"] if t["name"] == s.tm.name)
        if "text_area" in spec:
            areas = spec["text_area"]
            if not isinstance(areas[0], list):
                areas = [areas]
            ink = set(int(v) for v in spec["text_indices"])
            left = [(x, y) for ax, ay, aw, ah in areas
                    for y in range(ay, ay + ah) for x in range(ax, ax + aw)
                    if s.plane[y][x] in ink and (x, y) not in s.painted]
            if left:
                raise SystemExit(f"[nbn] tilemap {s.tm.name}: {len(left)} Japanese text pixels left "
                                 f"in the text area, first at {left[:4]}")
    for s in surfs:
        others = [tilemap_panel.Tilemap(data, t, base) for t in man["tilemaps"] if t["name"] != s.tm.name]
        notes.append(tilemap_panel.retile(s.tm, s.plane, others))
    for s in surfs:                   # every picture, decoded from the final bytes
        spec = next(t for t in man["tilemaps"] if t["name"] == s.tm.name)
        if tilemap_panel.Tilemap(data, spec, base).decode() != s.plane:
            raise SystemExit(f"[nbn] tilemap {s.tm.name}: the written file does not decode to the edit")
    return "; " + "; ".join(notes) if notes else ""


def cell_surface(data, man, cell, base=0):
    if "tilemap" in cell:
        return tilemap_surface(data, man, cell["tilemap"], base)
    if "pieces" in cell:
        parts = []
        for pc in cell["pieces"]:
            sub = cell_surface(data, man, {k: v for k, v in pc.items() if k in ("offset", "page", "bpp")}, base)
            parts.append((sub, int(pc["x"]), int(pc["y"]), int(pc["w"]), pc))
        return PieceSurface(parts, int(cell["h"]))
    bpp = int(cell.get("bpp", man.get("bpp", 4)))
    if "offset" in cell:
        offs = cell["offset"] if isinstance(cell["offset"], list) else [cell["offset"]]
        if offs and isinstance(offs[0], list):
            offs = [[_off(o) + base for o in row] for row in offs]
        else:
            offs = [_off(o) + base for o in offs]
    else:
        pages = cell["page"] if isinstance(cell["page"], list) else [cell["page"]]
        pb = int(man.get("page_bytes", 8192 if bpp == 4 else 16384))
        offs = [int(p) * pb + base for p in pages]
    return Surface(data, bpp, offs, int(man.get("page_w", 128)), int(man.get("page_h", 128)))


def surface_key(surf):
    if isinstance(surf, TilemapSurface):
        return surf.key
    return "+".join(f"{o:x}" for o in surf.offs)


# --- text rendering -----------------------------------------------------------------

_FONT = None
ART_SYMBOLS = TOOLS_PATCH / "font/art_symbols.txt"


def parse_extra_glyphs(src: Path, height=None):
    """the art-only glyphs (art_symbols.txt): latin12's format, any char;
    `height` rows per glyph (latin12's 12 by default; tiny_caps has 8)"""
    height = fontgen.HEIGHT if height is None else height
    glyphs = {}
    lines = src.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] != "glyph" or len(parts) != 4 or parts[2] != "adv" or (len(parts[1]) != 1 and parts[1] != "space"):
            raise SystemExit(f"{src}:{i}: expected 'glyph <char> adv <N>', got {line!r}")
        adv, bits_rows = int(parts[3]), []
        for _ in range(height):
            row = lines[i]
            i += 1
            if any(c not in ".#" for c in row) or len(row) > adv or len(row) > 16:
                raise SystemExit(f"{src}:{i}: bad row {row!r}")
            bits_rows.append(sum(1 << (15 - x) for x, c in enumerate(row) if c == "#"))
        glyphs[" " if parts[1] == "space" else parts[1]] = (adv, bits_rows)
    return glyphs


def font():
    global _FONT
    if _FONT is None:
        _FONT = fontgen.parse(fontgen.DEFAULT_SRC)
        for ch, g in parse_extra_glyphs(ART_SYMBOLS).items():
            if ch in _FONT:
                raise SystemExit(f"[nbn] {ART_SYMBOLS.name}: {ch!r} is already a latin12 glyph")
            _FONT[ch] = g
    return _FONT


PIXEL_FONTS = {"tiny_caps": 8}   # small authored pixel faces: name -> rows per glyph
_PIXEL_FONT = {}


def pixel_font(name):
    """a cell's "pixel_font": a small hand-drawn bitmap face in latin12's
    format (tools/patch/font/<name>.txt, "AUTHORED FOR THIS PROJECT"
    header) for strips the 12-px font cannot fit (the magazine's 8-px
    genre tags: tiny_caps)"""
    if name not in PIXEL_FONTS:
        raise SystemExit(f"[nbn] pixel_font {name!r}: not one of {sorted(PIXEL_FONTS)}")
    if name not in _PIXEL_FONT:
        src = TOOLS_PATCH / "font" / f"{name}.txt"
        if "AUTHORED FOR THIS PROJECT" not in src.read_text(encoding="utf-8").split("glyph", 1)[0]:
            raise SystemExit(f"[nbn] {src}: no 'AUTHORED FOR THIS PROJECT' header")
        _PIXEL_FONT[name] = parse_extra_glyphs(src, PIXEL_FONTS[name])
    return _PIXEL_FONT[name]


def text_layers(text: str, squeeze=False, spacing=0, markup=True, glyphs=None):
    """(pts, hl_pts, width) of the text at the 12-px font.  Text inside
    {braces} is the highlight (the panels' red words), text inside
    <angle brackets> the second highlight (EN_NICHI's blue words): their
    pixels are also in hl_pts, as (x, y) for {} and (x, y, 2) for <>.
    spacing: extra pixels after every glyph; glyphs: another face
    (pixel_font) instead of the 12-px font."""
    g = font() if glyphs is None else glyphs
    pts, hl = set(), set()
    x = 0
    on = 0
    for ch in text:
        if markup and ch in "{}<>":
            on = {"{": 1, "<": 2}.get(ch, 0)
            continue
        if ch not in g:
            raise SystemExit(f"[nbn] {text!r}: no glyph for {ch!r} in the Latin font")
        adv, rows = g[ch]
        for y, bits in enumerate(rows):
            for i in range(16):
                if bits & (1 << (15 - i)):
                    pts.add((x + i, y))
                    if on == 1:
                        hl.add((x + i, y))
                    elif on == 2:
                        hl.add((x + i, y, 2))
        x += adv - (1 if squeeze else 0) + spacing
    w = max((px for px, _ in pts), default=0) + 1
    return pts, hl, w


def text_mask(text: str, squeeze=False):
    """set of (x, y) pixels of the text at the 12-px font; width"""
    pts, _, w = text_layers(text, squeeze, markup=False)
    return pts, w


def cell_box(cell):
    if "pieces" in cell:
        return 0, 0, sum(int(p["w"]) for p in cell["pieces"]), int(cell["h"])
    return int(cell["x"]), int(cell["y"]), int(cell["w"]), int(cell["h"])


def erase_set(cell):
    if "erase" in cell:
        return set(int(v) for v in cell["erase"])
    return ({int(cell["fg"])} | ({int(cell["outline"])} if cell.get("outline") is not None else set())
            | ({int(cell["shadow"])} if cell.get("shadow") is not None else set()))


def retail_glyph_bbox(surf, cell):
    x0, y0, w, h = cell_box(cell)
    er = erase_set(cell)
    pts = [(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w) if surf.get(x, y) in er]
    if not pts:
        return None
    return (min(p[0] for p in pts) - x0, min(p[1] for p in pts) - y0,
            max(p[0] for p in pts) - x0, max(p[1] for p in pts) - y0)


def render_colours(cell, clut):
    fg = int(cell["fg"]) if str(cell["fg"]).lstrip("-").isdigit() else 1 << 20
    ol = cell.get("outline")
    fg_rgb = clut[fg] if clut and fg < len(clut) else (255, 255, 255)
    ol_rgb = clut[int(ol)] if (clut and ol is not None and int(ol) < len(clut)) else (0, 0, 0)
    if ol is not None and ol_rgb == fg_rgb:
        ol_rgb = tuple(255 - c for c in fg_rgb)
    return fg_rgb, ol_rgb


def shadow_colour(cell, clut):
    sh = cell.get("shadow")
    if sh is None:
        return None
    rgb = clut[int(sh)] if clut and int(sh) < len(clut) else (128, 128, 128)
    fg_rgb, ol_rgb = render_colours(cell, clut)
    if rgb in (fg_rgb, ol_rgb):
        rgb = (1, 2, 3)
    return rgb


def render_cell(cell, clut, glyph_bbox):
    if cell.get("mirror"):             # art stored left-right reversed (TAMA's name plates)
        w = cell_box(cell)[2]
        bb = None if glyph_bbox is None else (w - 1 - glyph_bbox[2], glyph_bbox[1],
                                              w - 1 - glyph_bbox[0], glyph_bbox[3])
        return render_cell(dict(cell, mirror=False), clut, bb).transpose(Image.FLIP_LEFT_RIGHT)
    w, h = cell_box(cell)[2:]
    text = cell["text"]
    ring = 1 if cell.get("outline") is not None else 0
    if not text:                       # erase only (a counter word English does without)
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bold = 1 if cell.get("bold") else 0
    spacing = int(cell.get("spacing", 0))
    markup = "hl" in cell or "hl2" in cell     # {} <> are markup only in highlight cells
    if "face" in cell:                 # hand-authored display lettering (artface.py)
        return render_face_cell(cell, clut, glyph_bbox)
    glyphs = pixel_font(cell["pixel_font"]) if "pixel_font" in cell else None
    pts, hl, tw = text_layers(text, spacing=spacing, markup=markup, glyphs=glyphs)
    tw += bold
    if tw + 2 * ring > w:
        pts, hl, tw = text_layers(text, squeeze=True, spacing=spacing, markup=markup, glyphs=glyphs)
        tw += bold
    if any(len(p) == 2 for p in hl) and cell.get("hl") is None:
        raise SystemExit(f"[nbn] cell {cell['name']}: {{highlight}} text needs an \"hl\" index")
    if any(len(p) == 3 for p in hl) and cell.get("hl2") is None:
        raise SystemExit(f"[nbn] cell {cell['name']}: <highlight> text needs an \"hl2\" index")
    scale = int(cell.get("scale", 1))
    if scale > 1:                      # big banner lettering: each font pixel a scale x scale block
        if hl:
            raise SystemExit(f"[nbn] cell {cell['name']}: highlights are not supported with \"scale\"")
        if tw * scale + 2 * ring > w:  # the 1-px squeeze, then the scale
            pts, hl, tw = text_layers(text, squeeze=True, spacing=spacing, markup=markup, glyphs=glyphs)
            tw += bold
        pts = [(x * scale + i, y * scale + j) for x, y in pts for i in range(scale) for j in range(scale)]
        tw *= scale
    if tw + 2 * ring > w:
        raise SystemExit(f"[nbn] cell {cell['name']}: {text!r} is {tw + 2 * ring} px, the box is {w} px")
    ink_y0 = min(p[1] for p in pts)
    ink_y1 = max(p[1] for p in pts)
    align = cell.get("align", "center")
    if isinstance(align, int):         # a pixel column (a letter placed on the
        x0 = align                     # 8-px cel grid, e.g. MAINROM's weekdays)
        if x0 < ring or x0 + tw + ring > w:
            raise SystemExit(f"[nbn] cell {cell['name']}: align {x0} puts {text!r} "
                             f"({tw} px) outside the {w}-px box")
    elif align == "left":
        x0 = ring
    elif align == "right":
        x0 = w - tw - ring
    elif align == "glyph" and glyph_bbox:
        x0 = max(ring, min(glyph_bbox[0] + ring, w - tw - ring))
    else:
        x0 = (w - tw) // 2
    va = cell.get("valign", "glyph")
    if isinstance(va, int) or (isinstance(va, str) and va.lstrip("-").isdigit()):
        y0 = int(va)
    elif va == "glyph" and glyph_bbox:
        # centre the Latin ink rows (cap height + descenders) on the retail glyph rows
        gc2 = glyph_bbox[1] + glyph_bbox[3]
        y0 = (gc2 - (ink_y0 + ink_y1) + 1) // 2
    else:
        y0 = (h - (ink_y1 - ink_y0 + 1)) // 2 - ink_y0
    y0 = max(ring - ink_y0, min(y0, h - 1 - ring - ink_y1))
    fg_rgb, ol_rgb = render_colours(cell, clut)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    shifted = {(x + x0, y + y0) for x, y in pts}
    hl_shifted = {(p[0] + x0, p[1] + y0) for p in hl if len(p) == 2}
    hl2_shifted = {(p[0] + x0, p[1] + y0) for p in hl if len(p) == 3}
    if cell.get("bold"):              # 2-px strokes, as the chunky retail menu glyphs
        shifted |= {(x + 1, y) for x, y in shifted}
        hl_shifted |= {(x + 1, y) for x, y in hl_shifted}
        hl2_shifted |= {(x + 1, y) for x, y in hl2_shifted}
    hl_rgb = highlight_colour(cell, clut)
    hl2_rgb = highlight_colour(cell, clut, "hl2")
    if ring:
        for (x, y) in list(shifted):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q not in shifted and 0 <= q[0] < w and 0 <= q[1] < h:
                        px[q[0], q[1]] = ol_rgb + (255,)
    sh_rgb = shadow_colour(cell, clut)
    if sh_rgb is not None:            # the retail kanji's 1-px drop shadow (down-right)
        for (x, y) in shifted:
            q = (x + 1, y + 1)
            if q not in shifted and q[0] < w and q[1] < h:
                px[q[0], q[1]] = sh_rgb + (255,)
    rows = cell.get("fg_rows")
    for (x, y) in shifted:
        if 0 <= x < w and 0 <= y < h:
            if rows:
                r = min(max(y - y0, 0), len(rows) - 1)
                px[x, y] = tuple(clut[int(rows[r])]) + (255,)
            elif (x, y) in hl_shifted:
                px[x, y] = hl_rgb + (255,)
            elif (x, y) in hl2_shifted:
                px[x, y] = hl2_rgb + (255,)
            else:
                px[x, y] = fg_rgb + (255,)
    return im


def check_face(cell):
    """the declared source of a face cell: the face file must hash as the
    manifest records (a changed file is a new source, to be re-declared)"""
    face = cell["face"]
    got = artface.sha1(face)
    want = str(cell.get("face_sha1", "")).lower()
    if got != want:
        raise SystemExit(f"[nbn] cell {cell['name']}: face {face!r} hashes {got}, the manifest "
                         f"declares {want or 'nothing'} (\"face_sha1\"): the source changed; "
                         f"re-author the PNG and record the new hash deliberately")
    return face


def ramp_rows(cell, cap):
    """one CLUT index per row of the cap height from "ramp"
    [[fraction, index], ...] (fraction 0 = cap top, 1 = baseline)"""
    ramp = sorted((float(f), int(i)) for f, i in cell["ramp"])
    rows = []
    for r in range(cap):
        frac = r / max(cap - 1, 1)
        idx = ramp[0][1]
        for f, i in ramp:
            if frac >= f:
                idx = i
        rows.append(idx)
    return rows


def render_face_cell(cell, clut, glyph_bbox):
    """a cell set in a hand-authored face: fill rows from "ramp" (or fg),
    an "outline_w"-px keyline ring, an optional shadow at
    ("shadow_dx", "shadow_dy"); positioned like a font cell"""
    w, h = cell_box(cell)[2:]
    face = check_face(cell)
    cap = int(cell["cap"])
    pts, tw = artface.render(face, cell["text"], cap, gap=float(cell.get("gap", 8)),
                             space=float(cell.get("space", 28)), slant=float(cell.get("slant", 0)),
                             xscale=float(cell.get("xscale", 1)))
    ring = int(cell.get("outline_w", 1)) if cell.get("outline") is not None else 0
    sdx, sdy = int(cell.get("shadow_dx", 1)), int(cell.get("shadow_dy", 1))
    if cell.get("shadow") is None:
        sdx = sdy = 0
    if tw + 2 * ring + max(sdx, 0) > w or cap + 2 * ring + max(sdy, 0) > h:
        raise SystemExit(f"[nbn] cell {cell['name']}: {cell['text']!r} is {tw}x{cap} px (+ring {ring}), "
                         f"the box is {w}x{h} px")
    align = cell.get("align", "center")
    if align == "left":
        x0 = ring
    elif align == "right":
        x0 = w - tw - ring - max(sdx, 0)
    elif align == "glyph" and glyph_bbox:
        x0 = max(ring, min(glyph_bbox[0] + ring, w - tw - ring))
    else:
        x0 = (w - tw) // 2
    va = cell.get("valign", "glyph")
    if isinstance(va, int) or (isinstance(va, str) and va.lstrip("-").isdigit()):
        y0 = int(va)
    elif va == "glyph" and glyph_bbox:
        y0 = (glyph_bbox[1] + glyph_bbox[3] + 1 - cap) // 2
    else:
        y0 = (h - cap) // 2
    y0 = max(ring, min(y0, h - cap - ring - max(sdy, 0)))
    fg_rgb, ol_rgb = render_colours(cell, clut)
    rows = ramp_rows(cell, cap) if cell.get("ramp") else None
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    fill = {(x + x0, y + y0) for x, y in pts}
    ringset = set()
    if ring:
        for (x, y) in fill:
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    q = (x + dx, y + dy)
                    if q not in fill and 0 <= q[0] < w and 0 <= q[1] < h:
                        ringset.add(q)
    sh_rgb = shadow_colour(cell, clut)
    if sh_rgb is not None:
        for (x, y) in fill | ringset:
            q = (x + sdx, y + sdy)
            if q not in fill and q not in ringset and 0 <= q[0] < w and 0 <= q[1] < h:
                px[q[0], q[1]] = sh_rgb + (255,)
    for q in ringset:
        px[q[0], q[1]] = ol_rgb + (255,)
    for (x, y) in fill:
        if rows:
            px[x, y] = tuple(clut[rows[min(max(y - y0, 0), cap - 1)]]) + (255,)
        else:
            px[x, y] = fg_rgb + (255,)
    return im


def highlight_colour(cell, clut, key="hl"):
    """render colour of the {highlight} ("hl") or <highlight> ("hl2")
    index, kept distinct from the other render colours so apply_cell can
    tell them apart"""
    hl = cell.get(key)
    if hl is None:
        return None
    rgb = tuple(clut[int(hl)]) if clut and int(hl) < len(clut) else (255, 0, 0)
    fg_rgb, ol_rgb = render_colours(cell, clut)
    taken = [fg_rgb, ol_rgb, shadow_colour(cell, clut)]
    if key == "hl2":
        taken.append(highlight_colour(cell, clut))
    if rgb in taken:
        raise SystemExit(f"[nbn] cell {cell['name']}: {key} index {hl} has the colour of another layer")
    return rgb


# --- apply --------------------------------------------------------------------------

def inpaint(surf, cell):
    """replace the retail glyph pixels with the background around them"""
    x0, y0, w, h = cell_box(cell)
    er = erase_set(cell)
    bg = cell.get("bg", "keep")
    if bg != "keep":
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if surf.get(x, y) in er:
                    surf.set(x, y, int(bg))
        return
    snap = {(x, y): surf.get(x, y) for y in range(y0 - 1, y0 + h + 1) for x in range(x0 - 1, x0 + w + 1)
            if 0 <= x < surf.w and 0 <= y < surf.h}

    def is_bg(x, y):
        return (x, y) in snap and snap[(x, y)] not in er

    def probe(x, y, dx, dy):
        n = 1
        while True:
            q = (x + dx * n, y + dy * n)
            if q not in snap:
                return None
            if is_bg(*q):
                return n, snap[q]
            n += 1

    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            if snap[(x, y)] not in er:
                continue
            l, r, u, d = probe(x, y, -1, 0), probe(x, y, 1, 0), probe(x, y, 0, -1), probe(x, y, 0, 1)
            choice = None
            if u and d and u[1] == d[1]:
                choice = u[1]                         # a column of one value (horizontal gradient)
            elif l and r and l[1] == r[1]:
                choice = l[1]                         # a row of one value (vertical gradient)
            else:
                cands = [c for c in (l, r, u, d) if c]
                choice = min(cands)[1] if cands else 0
            surf.set(x, y, choice)


def row_fills(surf, cell):
    """fg "row": per piece, the fill index the retail glyph uses on each row
    (a vertical gradient), sampled before the erase; rows without a sample
    take the nearest sampled row"""
    x0, y0, w, h = cell_box(cell)
    parts = surf.parts if isinstance(surf, PieceSurface) else [(surf, x0, y0, w, cell)]
    out = []
    for (s, px, py, pw, spec) in parts:
        fs = set(int(v) for v in spec.get("fill_set", cell.get("fill_set", [])))
        rows = {}
        for y in range(h):
            c = Counter(s.get(px + x, py + y) for x in range(pw))
            c = Counter({k: n for k, n in c.items() if k in fs})
            if c:
                rows[y] = c.most_common(1)[0][0]
        if not rows:
            raise SystemExit(f"[nbn] {cell['name']}: no fill sample in a piece (fill_set {sorted(fs)})")
        full = [rows[min(rows, key=lambda r: abs(r - y))] for y in range(h)]
        out.append((pw, full, int(spec.get("outline", cell.get("outline", 0)))))
    return out


def apply_cell(surf, cell, png: Image.Image, clut):
    x0, y0, w, h = cell_box(cell)
    fills = row_fills(surf, cell) if cell["fg"] == "row" else None
    inpaint(surf, cell)
    fg_rgb, ol_rgb = render_colours(cell, clut)
    fg = int(cell["fg"]) if fills is None else 0
    ol = int(cell["outline"]) if cell.get("outline") is not None else fg

    def piece_of(x):
        for pw, full, pol in fills:
            if x < pw:
                return full, pol
            x -= pw
        return fills[-1][1], fills[-1][2]
    sh_rgb = shadow_colour(cell, clut)
    hl_rgb = highlight_colour(cell, clut)
    hl2_rgb = highlight_colour(cell, clut, "hl2")
    px = png.convert("RGBA").load()
    if cell.get("fg_rows") or cell.get("ramp"):
        idx = sorted({int(v) for v in cell.get("fg_rows", [])} | {int(i) for _, i in cell.get("ramp", [])} |
                     ({int(cell["outline"])} if cell.get("outline") is not None else set()) |
                     ({int(cell["shadow"])} if cell.get("shadow") is not None else set()))
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a < 128:
                    continue
                surf.set(x0 + x, y0 + y, min(idx, key=lambda i: sum(
                    (p - q) ** 2 for p, q in zip((r, g, b), clut[i]))))
        return
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            dfg = sum((p - q) ** 2 for p, q in zip((r, g, b), fg_rgb))
            dol = sum((p - q) ** 2 for p, q in zip((r, g, b), ol_rgb))
            if sh_rgb is not None and (r, g, b) == sh_rgb:
                surf.set(x0 + x, y0 + y, int(cell["shadow"]))
                continue
            if hl_rgb is not None and (r, g, b) == hl_rgb:
                surf.set(x0 + x, y0 + y, int(cell["hl"]))
                continue
            if hl2_rgb is not None and (r, g, b) == hl2_rgb:
                surf.set(x0 + x, y0 + y, int(cell["hl2"]))
                continue
            if fills is not None:
                full, pol = piece_of(x)
                surf.set(x0 + x, y0 + y, full[y] if dfg <= dol else pol)
                continue
            surf.set(x0 + x, y0 + y, fg if dfg <= dol else ol)


def block_checksum_ok(d) -> bool:
    """the loaders' block_checksum_check(blocks, buf) (src/main/matched/
    block_checksum_check.c): the byte sum of the first blocks*2048 - 4
    bytes, as a u16, equals the big-endian u16 in the next two bytes"""
    n = len(d)
    return n % 2048 == 0 and (sum(d[:n - 4]) & 0xFFFF) == (d[n - 4] << 8 | d[n - 3])


def fix_block_checksum(retail: bytes, data: bytearray, mode="auto") -> str:
    """keep a file the game checksums loadable: when the RETAIL file
    carries a valid block checksum (OMIKUJI.BIN: SHOUGATU's
    shougatu_data_check refuses the file and retries forever otherwise),
    re-stamp it over the edited bytes.  mode: "auto" (re-stamp when the
    retail sum is valid), "always", or false."""
    if mode is False or mode == "off":
        return ""
    if mode == "auto" and not block_checksum_ok(retail):
        return ""
    n = len(data)
    s = sum(data[:n - 4]) & 0xFFFF
    data[n - 4], data[n - 3] = s >> 8, s & 0xFF
    assert block_checksum_ok(data)
    return f" (block checksum 0x{s:04x})"


def sprite_frame_texts(man):
    """[(frame, seg_index, seg, english)]: the manifest's English, an edited
    sheet (sprite_frames.editor_sheet, columns ID / English as
    export_drafts.py writes them) winning over the draft"""
    sf = man["sprite_frames"]
    edited = {}
    sheet = locate(sf.get("editor_sheet", ""))
    if sf.get("editor_sheet") and sheet.is_file():
        import csv
        with open(sheet, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("English", "").strip():
                    edited[r["ID"]] = r["English"]
    out = []
    for fr in sf["frames"]:
        for i, seg in enumerate(fr["segs"]):
            key = f"{sf['id_prefix']}:f{int(fr['frame']):03d}.{i}"
            out.append((int(fr["frame"]), i, seg, edited.get(key, seg["text"]), key))
    return out


def apply_sprite_frames(data, retail, man, base=0):
    """Rebuild the file's sprite frames (cel lists) from English.

    The format is the one sprite_slot_disp (src/main/matched/) draws for a
    class slot in direct-frame mode: slot+12 points at a table of frame
    pointers, a frame is `s16 count, w, h, pad` + count x `s16 ox, oy,
    cel, tp, attr, w, h`, cel = page << 8 | tile (8-px tiles, 16 per
    row), the page an index into the slot+52 table of page buffers
    (search_tpage8 maps a buffer to its VRAM slot).  Every listed frame
    is laid out from its segments: one cel per character, the glyph cell
    of that character (a manifest cell with "glyph"), pen advance = the
    12-px font's advance + `letter_gap`; a segment starts at its retail
    ox ("left") or is centred on the retail segment ("center").  Frames
    in `keep` are copied verbatim.  The lists are placed first-fit into
    `regions` (RAM ranges inside the loaded file that nothing overwrites
    while the frames are drawn) and the frame table is rewritten.
    Refused: a character without a glyph cell, two segments of one row
    closer than 4 px, a line that leaves `screen` at any x the retail
    `sequence` table draws its frame at, lists that do not fit."""
    sf = man["sprite_frames"]
    ram = _off(sf["ram"])
    fo = lambda addr: addr - ram + base                       # noqa: E731
    u32 = lambda addr: struct.unpack_from("<I", retail, fo(addr))[0]   # noqa: E731
    pages = [u32(_off(sf["pages"]) + 4 * i) for i in range(int(sf["page_count"]))]
    table = _off(sf["table"])
    count = int(sf["count"])
    fnt = font()
    gap = int(sf.get("letter_gap", 1))
    dy = int(sf.get("glyph_dy", 0))
    # "tp": "retail" -- each rebuilt frame keeps the tp (CLUT row / texture
    # page bits) and attr of its own retail frame's first cel: the menus
    # draw one frame of a pair normal and the other highlighted (OPTION.NBN)
    tp_retail = sf.get("tp") == "retail"
    tp = 0 if tp_retail else int(sf.get("tp", 4096))

    glyphs = {}
    font_pages = set()
    for cell in man["cells"]:
        ch = cell.get("glyph")
        if ch is None:
            continue
        addr = ram + _off(cell["offset"])
        if addr not in pages:
            raise SystemExit(f"[nbn] glyph {ch!r}: page 0x{addr:08X} is not in the frame page table")
        x, y, w, h = int(cell["x"]), int(cell["y"]), int(cell["w"]), int(cell["h"])
        if x % 8 or y % 8 or w % 8 or h % 8:
            raise SystemExit(f"[nbn] glyph {ch!r}: the cell must sit on the 8-px tile grid")
        glyphs[ch] = (pages.index(addr) << 8 | (y // 8) << 4 | (x // 8), w, h)
        font_pages.add(addr)

    def ink_w(ch):
        rows = fnt[ch][1]
        return max((16 - (r & -r).bit_length() + 1 for r in rows if r), default=0)

    def layout(text):
        cels, pen, right = [], 0, 0
        for ch in text:
            if ch not in fnt:
                raise SystemExit(f"[nbn] {text!r}: {ch!r} is not in the Latin font")
            if ch != " ":
                if ch not in glyphs:
                    raise SystemExit(f"[nbn] {text!r}: no glyph cell for {ch!r}")
                cels.append((pen, glyphs[ch]))
                right = pen + ink_w(ch) + 2
            pen += fnt[ch][0] + gap
        return cels, right

    # the x each frame is drawn at (the retail roll table)
    seq = sf.get("sequence")
    xs = {}
    if seq:
        sdata = (EXTRACTED / seq["file"]).read_bytes()
        so = _off(seq["addr"]) - _off(seq["load"])
        for i in range(int(seq["count"])):
            f, x = sdata[so + 2 * i], sdata[so + 2 * i + 1]
            if f < int(seq.get("blank_from", 256)):
                xs.setdefault(f, set()).add(x + int(seq.get("x_bias", 0)))
    lo_s, hi_s = sf.get("screen", [-10000, 10000])

    built = {}
    rows_of = {}
    for f, i, seg, text, key in sprite_frame_texts(man):
        cels, width = layout(text)
        ox, oy = int(seg["ox"]), int(seg["oy"])
        if seg.get("align", "left") == "center":
            ox = ox + (int(seg["w"]) - width) // 2
        for sx in xs.get(f, {0}):
            if sx + ox < lo_s or sx + ox + width > hi_s:
                raise SystemExit(f"[nbn] {key} {text!r}: {width} px at x {sx + ox} leaves the "
                                 f"screen ({lo_s}..{hi_s})")
        rows_of.setdefault((f, oy), []).append((ox, ox + width, text))
        ftp, fattr = tp, 0
        if tp_retail:
            first = _frame_cels(retail, fo, u32(table + 4 * f))
            if not first:
                raise SystemExit(f"[nbn] frame {f}: \"tp\": \"retail\" needs a retail cel")
            ftp, fattr = first[0][3], first[0][4]
        built.setdefault(f, []).extend(
            (ox + px, oy + dy, cel, ftp, fattr, w, h) for px, (cel, w, h) in cels)
    for (f, oy), segs in rows_of.items():
        segs.sort()
        for a_, b_ in zip(segs, segs[1:]):
            if a_[1] + 4 > b_[0]:
                raise SystemExit(f"[nbn] frame {f}: {a_[2]!r} runs into {b_[2]!r}")

    keep = {int(k) for k in sf.get("keep", [])}
    regions = [[_off(lo), _off(hi)] for lo, hi in sf["regions"]]
    for lo, hi in regions:
        for pg in font_pages | {pages[c[2] >> 8] for k in keep for c in _frame_cels(retail, fo, u32(table + 4 * k))}:
            if lo < pg + int(man.get("page_bytes", 8192)) and pg < hi:
                raise SystemExit(f"[nbn] region 0x{lo:08X}-0x{hi:08X} overlaps a page the frames draw from")
        data[fo(lo):fo(hi)] = bytes(hi - lo)
    cursor = [lo for lo, _ in regions]
    n_cels = n_bytes = 0
    for f in range(count):
        if f in keep:
            old = u32(table + 4 * f)
            n = struct.unpack_from("<h", retail, fo(old))[0]
            blob = retail[fo(old):fo(old) + 8 + 14 * n]
        elif f in built:
            cs = built[f]
            blob = struct.pack("<4h", len(cs), 0, 0, 0) + b"".join(struct.pack("<7h", *c) for c in cs)
        else:
            raise SystemExit(f"[nbn] frame {f}: neither laid out nor kept")
        for k, (lo, hi) in enumerate(regions):
            if cursor[k] + len(blob) <= hi:
                addr = cursor[k]
                data[fo(addr):fo(addr) + len(blob)] = blob
                cursor[k] = (addr + len(blob) + 3) & ~3
                break
        else:
            raise SystemExit(f"[nbn] frame {f}: {len(blob)} B do not fit the free regions")
        struct.pack_into("<I", data, fo(table + 4 * f), addr)
        n_cels += (len(blob) - 8) // 14
        n_bytes += len(blob)
    free = sum(hi - c for c, (_, hi) in zip(cursor, regions))
    return (f"; {count} sprite frames rebuilt ({n_cels} cels, {n_bytes} B in "
            f"{sum(1 for c, (lo, _) in zip(cursor, regions) if c > lo)} regions, {free} B free)")


def apply_cel_remap(data, retail, man, base=0):
    """Point the existing sprite frames' cels at English word cells.

    For labels that the retail frames assemble from glyph cells SHARED
    between labels (NAME_ENT: 名 in both 名前 and あだ名, い in はい and
    いいえ, 日 in 誕生日 and the day unit), no in-place pixel edit reads
    right everywhere.  Here every frame of the table keeps its cels and
    positions; a cel whose (cel, w) matches a rule is pointed at a manifest
    cell (the English word drawn into page space the retail glyphs freed:
    cel = tile of the cell, w = the cell's width) or deleted (a unit the
    English does without), and `at` overrides a rule for one frame and
    position.  Lists only shrink, so every frame is rewritten in place.
    Refused: a rule cell that is not a manifest cell on the 8-px grid of
    page `page`, a rule or override that matches nothing."""
    cr = man["cel_remap"]
    ram = _off(cr["ram"])
    fo = lambda addr: addr - ram + base                       # noqa: E731
    cells = {c["name"]: c for c in man["cells"]}
    page = int(cr.get("page", 0))

    def target(name):
        if name is None:
            return None
        c = cells.get(name)
        if c is None:
            raise SystemExit(f"[nbn] cel_remap: no manifest cell {name!r}")
        x, y, w, h = int(c["x"]), int(c["y"]), int(c["w"]), int(c["h"])
        if x % 8 or y % 8 or w % 8 or h % 8:
            raise SystemExit(f"[nbn] cel_remap: cell {name!r} is not on the 8-px tile grid")
        return page << 8 | (y // 8) << 4 | (x // 8), w, h

    rules = {(_off(r["cel"]), int(r["w"])): r for r in cr["rules"]}
    at = {(int(r["frame"]), int(r["ox"]), int(r["oy"])): r for r in cr.get("at", [])}
    used = set()
    n_changed = n_deleted = 0
    table = _off(cr["table"])
    for f in range(int(cr["count"])):
        addr = struct.unpack_from("<I", retail, fo(table + 4 * f))[0]
        cels = _frame_cels(retail, fo, addr)
        out = []
        for c in cels:
            ox, oy, cel, tp, attr, w, h = c
            r = at.get((f, ox, oy)) if (f, ox, oy) in at else None
            if r is not None:
                used.add(("at", f, ox, oy))
            else:
                r = rules.get((cel & 0xFFFF, w))
                if r is not None:
                    used.add(("rule", cel & 0xFFFF, w))
            if r is None:
                out.append(c)
                continue
            if r.get("delete"):
                n_deleted += 1
                continue
            cel2, w2, h2 = target(r["cell"])
            out.append((ox, oy, cel2, tp, attr, w2, h2))
            n_changed += 1
        if out != cels:
            p = fo(addr)
            struct.pack_into("<h", data, p, len(out))
            data[p + 8:p + 8 + 14 * len(cels)] = bytes(14 * len(cels))
            for k, c in enumerate(out):
                struct.pack_into("<7h", data, p + 8 + 14 * k, *c)
    for r in cr["rules"]:
        if ("rule", _off(r["cel"]), int(r["w"])) not in used:
            raise SystemExit(f"[nbn] cel_remap: rule {r} matches no cel")
    for r in cr.get("at", []):
        if ("at", int(r["frame"]), int(r["ox"]), int(r["oy"])) not in used:
            raise SystemExit(f"[nbn] cel_remap: override {r} matches no cel")
    return f"; {n_changed} cels pointed at English word cells, {n_deleted} unit cels dropped"


def copy_rects(data, retail, man, base=0):
    """`copy_rects`: [{"from": {"offset", "x", "y"}, "to": {"offset", "x", "y"}, "w", "h"}]
    -- move a rectangle of the file's OWN retail pixels to unused page space
    before the cells are drawn (a blank word board for an English piece
    that does not fit where the retail pieces were).  Only 8-bpp pages of
    `page_w`; the destination must be all zero (unused) in the retail file,
    so nothing the game draws is overwritten."""
    pw = int(man.get("page_w", 128))
    for c in man.get("copy_rects", []):
        if int(man.get("bpp", 4)) != 8:
            raise SystemExit("[nbn] copy_rects: 8-bpp pages only")
        f, t, w, h = c["from"], c["to"], int(c["w"]), int(c["h"])
        fo, to = _off(f["offset"]) + base, _off(t["offset"]) + base
        for y in range(h):
            s = fo + (int(f["y"]) + y) * pw + int(f["x"])
            d = to + (int(t["y"]) + y) * pw + int(t["x"])
            if any(retail[d:d + w]):
                raise SystemExit(f"[nbn] copy_rects: destination {t} row {y} is not unused (non-zero) page space")
            data[d:d + w] = retail[s:s + w]


def apply_frame_layout(data, retail, man, base=0):
    """Lay chosen sprite frames out again from English word cells.

    For labels assembled from word pieces SHARED between labels whose
    English needs a different number of pieces (BUNKA_SD's speech-topic
    boards: 僕の / 高校 / 生活 ... serve five titles), `cel_remap`'s
    one-for-one rule is not enough.  `frame_layout` lists, per frame, the
    cels left to right: "@0xTILE" keeps a retail cel of that frame (its
    width; the board's end caps), a name is a manifest cell (the English
    piece drawn where the retail pieces were).  The cels are set side by
    side, centred on the retail frame's centre, every one with the first
    retail cel's oy / tp / attr / h.  Tiles are `tile`-px (16: page << 6 |
    row << 3 | column, sprite_slot_disp's 16-px tile form; 8: page << 8 |
    row << 4 | column).  A frame keeps its record: refused when the new
    list is longer than the retail one, a cell is off the tile grid, or an
    "@" tile is not one of the frame's own cels."""
    fl = man["frame_layout"]
    ram = _off(fl["ram"])
    fo = lambda addr: addr - ram + base                       # noqa: E731
    cells = {c["name"]: c for c in man["cells"]}
    page = int(fl.get("page", 0))
    tile = int(fl.get("tile", 16))
    table = _off(fl["table"])
    n_frames = 0
    for fr in fl["frames"]:
        f = int(fr["frame"])
        addr = struct.unpack_from("<I", retail, fo(table + 4 * f))[0]
        cels = _frame_cels(retail, fo, addr)
        ox0 = min(c[0] for c in cels)
        ox1 = max(c[0] + c[5] for c in cels)
        _, oy, _, tp, attr, _, h = cels[0]
        layout = []
        for name in fr["cels"]:
            if name.startswith("@"):
                t = _off(name[1:])
                own = [c for c in cels if c[2] & 0xFFFF == t]
                if not own:
                    raise SystemExit(f"[nbn] frame_layout: frame {f} has no cel {name}")
                layout.append((t, own[0][5]))
                continue
            c = cells.get(name)
            if c is None:
                raise SystemExit(f"[nbn] frame_layout: no manifest cell {name!r}")
            x, y, w = int(c["x"]), int(c.get("tile_y", c["y"])), int(c["w"])
            if x % tile or y % tile or w % tile:
                raise SystemExit(f"[nbn] frame_layout: cell {name!r} is not on the {tile}-px tile grid")
            pg = int(c.get("tile_page", page))
            if tile == 16:
                t = pg << 6 | (y // 16) << 3 | (x // 16)
            else:
                t = pg << 8 | (y // 8) << 4 | (x // 8)
            layout.append((t, w))
        if len(layout) > len(cels):
            raise SystemExit(f"[nbn] frame_layout: frame {f} needs {len(layout)} cels, "
                             f"its record holds {len(cels)}")
        width = sum(w for _, w in layout)
        x = (ox0 + ox1) // 2 - width // 2
        out = []
        for t, w in layout:
            out.append((x, oy, t, tp, attr, w, h))
            x += w
        p = fo(addr)
        struct.pack_into("<h", data, p, len(out))
        data[p + 8:p + 8 + 14 * len(cels)] = bytes(14 * len(cels))
        for k, c in enumerate(out):
            struct.pack_into("<7h", data, p + 8 + 14 * k, *c)
        n_frames += 1
    return f"; {n_frames} frames laid out from English word cells"


def _frame_cels(data, fo, addr):
    n = struct.unpack_from("<h", data, fo(addr))[0]
    return [struct.unpack_from("<7h", data, fo(addr) + 8 + 14 * k) for k in range(n)]


def surface_image(surf, clut, k=3):
    im = Image.new("RGB", (surf.w, surf.h))
    p = im.load()
    for y in range(surf.h):
        for x in range(surf.w):
            v = surf.get(x, y)
            p[x, y] = clut[v] if clut and v < len(clut) else (v * 17 if surf.bpp == 4 else v,) * 3
    return im.resize((surf.w * k, surf.h * k), Image.NEAREST)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", nargs="+")
    ap.add_argument("--render", action="store_true", help="write the cell PNGs from the font")
    ap.add_argument("--preview", help="directory for before|after images of the touched surfaces")
    a = ap.parse_args()
    for mpath in a.manifest:
        mpath = Path(mpath).resolve()
        man = json.loads(mpath.read_text())
        for i, (rel, base) in enumerate(manifest_targets(man)):
            if a.render and i:
                break                     # the PNGs come from the first file
            inject_file(a, mpath, man, rel, base)


def manifest_targets(man):
    """[(file, base)]: the manifest's file at base 0, then every `copies`
    entry ({"file", "base"}): the same picture repeated inside another
    file at that byte offset (the battle HUD page in each VS_*.BIN)"""
    return [(man["file"], 0)] + [(c["file"], _off(c["base"])) for c in man.get("copies", [])]


def inject_file(a, mpath, man, rel, base):
    retail = bytes((EXTRACTED / rel).read_bytes())
    data = bytearray(retail)      # always from the retail file
    size = len(data)
    done = 0
    touched = {}
    if not a.render:
        for c in man.get("clear", []):
            o = _off(c["offset"]) + base
            data[o:o + int(c["bytes"])] = bytes(int(c["bytes"]))
    copy_rects(data, retail, man, base)
    for cell in man["cells"]:
        surf = cell_surface(data, man, cell, base)
        clut = load_clut(cell.get("clut", man.get("clut", {})), retail,
                         int(cell["fg"]) if str(cell["fg"]).isdigit() else 0)
        png_path = mpath.parent / cell.get("png", cell["name"] + ".png")
        if a.render:
            rsurf = cell_surface(bytearray(retail), man, cell, base)
            im = render_cell(cell, clut, retail_glyph_bbox(rsurf, cell))
            im.save(png_path)
            print(f"[nbn] {rel} {cell['name']}: {cell['text']!r} -> {png_path.relative_to(ROOT)} "
                  f"({im.width}x{im.height})")
            continue
        if not png_path.exists():
            raise SystemExit(f"[nbn] {png_path} missing: run --render first and commit it")
        im = Image.open(png_path)
        bw, bh = cell_box(cell)[2:]
        if (im.width, im.height) != (bw, bh):
            raise SystemExit(f"[nbn] {png_path}: {im.width}x{im.height} is not the cell's "
                             f"{bw}x{bh}")
        # provenance: the PNG must be exactly what --render draws from the
        # manifest text with our fonts (no hand-painted or foreign pixels)
        rsurf = cell_surface(bytearray(retail), man, cell, base)
        fresh = render_cell(cell, clut, retail_glyph_bbox(rsurf, cell))
        if fresh.tobytes() != im.convert("RGBA").tobytes():
            what = (f"not the render of its declared face {cell['face']!r}" if "face" in cell
                    else "not the font render")
            raise SystemExit(f"[nbn] {png_path}: {what} of its text "
                             f"{cell['text']!r}: run --render (a PNG must not carry other pixels)")
        touched.setdefault(surface_key(surf), (cell, clut))
        apply_cell(surf, cell, im, clut)
        if isinstance(surf, TilemapSurface):
            x0, y0 = cell_box(cell)[:2]
            rgba = im.convert("RGBA")
            surf.painted |= {(x0 + x, y0 + y) for y in range(bh) for x in range(bw)
                             if rgba.getpixel((x, y))[3] >= 128}
        done += 1
    if a.render:
        return
    frames_note = ""
    if "sprite_frames" in man:
        frames_note = apply_sprite_frames(data, retail, man, base)
    if "cel_remap" in man:
        frames_note += apply_cel_remap(data, retail, man, base)
    if "frame_layout" in man:
        frames_note += apply_frame_layout(data, retail, man, base)
    if "tilemaps" in man:
        frames_note += commit_tilemaps(data, man, base)
        _TILEMAPS.clear()             # previews below decode the written bytes again
    assert len(data) == size
    ck = fix_block_checksum(retail, data, man.get("checksum", "auto"))
    out = OUT_FILES / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(data))
    if a.preview:
        pv = Path(a.preview)
        pv.mkdir(parents=True, exist_ok=True)
        for key, (cell, clut) in touched.items():
            before = surface_image(cell_surface(bytearray(retail), man, cell, base), clut)
            after = surface_image(cell_surface(data, man, cell, base), clut)
            sheet = Image.new("RGB", (before.width * 2 + 6, before.height), (255, 0, 255))
            sheet.paste(before, (0, 0))
            sheet.paste(after, (before.width + 6, 0))
            sheet.save(pv / f"{Path(rel).stem}_{key}.png")
    print(f"[nbn] {rel}: {done} cells written in place{frames_note}{ck} -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
