#!/usr/bin/env python3
"""artface.py - hand-authored display lettering for the art pipeline.

The 12-px Latin font (tools/patch/font/latin12.txt) sets the game's small
labels; the two designed logotypes the patch replaces (Rei Ijuin's gold
prologue name card, the Memorial Spot masthead) need large letterforms.
Those are authored here as vector shapes in a FACE file
(tools/patch/font/<name>.txt, header "AUTHORED FOR THIS PROJECT"):

  glyph <char> adv <units>       a capital in a 100-unit cap-height box
                                 (x right, y DOWN, baseline at y = 100)
  rect x0,y0 x1,y1               filled rectangle
  poly x,y x,y ...               filled simple polygon
  ring cx,cy rx,ry wx,wy a0,a1   elliptical band (outer radii rx,ry, band
                                 thickness wx,wy) over angles a0..a1 in
                                 degrees, 0 = right, 90 = down; drawn as
                                 a polygon with one vertex per 7.5 degrees

`render(face, text, cap, ...)` scales the shapes to a cap height of `cap`
pixels and fills them with the even-odd scanline rule evaluated at pixel
centres in exact integer arithmetic (vertex positions are rounded to
1/16 px first), so the same source, text and parameters give the same
pixels on every machine: that is what lets nbn_inject's provenance gate
re-render a committed PNG from its declared source and refuse any other
pixels.  `slant` shears the letters (an italic: x grows by slant * the
height above the baseline), `xscale` condenses them, `gap` is the extra
advance between letters and `space` the width of a word space, both in
face units.

The styling (a keyline ring of N px, a drop shadow, a vertical palette
ramp through the fill) is nbn_inject's: this module only makes the
letter pixels.  `sha1(face)` is the hash a manifest records for the
source file.
"""
import hashlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import locate                          # noqa: E402
FONT_DIR = TOOLS_PATCH / "font"
TICK = 16                      # sub-pixel ticks per pixel for vertex rounding
UNITS = 100                    # cap height of the face box


def face_path(name):
    p = Path(name)
    if p.suffix != ".txt":
        p = FONT_DIR / (name + ".txt")
    elif not p.is_absolute():
        p = locate(p)
    return p


def sha1(name):
    return hashlib.sha1(face_path(name).read_bytes()).hexdigest()


def _pt(tok):
    x, y = tok.split(",")
    return float(x), float(y)


def parse(name):
    """{char: (adv_units, [polygon], ...)}; a polygon is a list of (x, y)
    in face units.  Refuses a file without the authorship header."""
    src = face_path(name)
    text = src.read_text(encoding="utf-8")
    if "AUTHORED FOR THIS PROJECT" not in text.split("glyph", 1)[0]:
        raise SystemExit(f"[artface] {src}: no 'AUTHORED FOR THIS PROJECT' header")
    glyphs, cur = {}, None
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "glyph":
            if len(parts) != 4 or parts[2] != "adv" or len(parts[1]) != 1:
                raise SystemExit(f"{src}:{n}: expected 'glyph <char> adv <N>'")
            cur = parts[1]
            if cur in glyphs:
                raise SystemExit(f"{src}:{n}: glyph {cur!r} twice")
            glyphs[cur] = (float(parts[3]), [])
            continue
        if cur is None:
            raise SystemExit(f"{src}:{n}: shape before any glyph")
        shapes = glyphs[cur][1]
        if parts[0] == "rect" and len(parts) == 3:
            (x0, y0), (x1, y1) = _pt(parts[1]), _pt(parts[2])
            shapes.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        elif parts[0] == "poly" and len(parts) >= 4:
            shapes.append([_pt(t) for t in parts[1:]])
        elif parts[0] == "ring" and len(parts) == 5:
            (cx, cy), (rx, ry), (wx, wy), (a0, a1) = (_pt(t) for t in parts[1:])
            if not (0 < wx <= rx and 0 < wy <= ry and a1 > a0):
                raise SystemExit(f"{src}:{n}: bad ring")
            steps = max(2, int(round((a1 - a0) / 7.5)))
            outer, inner = [], []
            for k in range(steps + 1):
                a = math.radians(a0 + (a1 - a0) * k / steps)
                outer.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
                inner.append((cx + (rx - wx) * math.cos(a), cy + (ry - wy) * math.sin(a)))
            if a1 - a0 >= 360:          # a closed band: two polygons, even-odd
                shapes.append(outer[:-1])
                shapes.append(inner[:-1])
                shapes[-2:] = [("ring", outer[:-1], inner[:-1])]
            else:
                shapes.append(outer + inner[::-1])
        else:
            raise SystemExit(f"{src}:{n}: cannot parse {line!r}")
    return glyphs


def _fill(poly_ticks, pts, bbox_w, bbox_h):
    """add the pixels whose centre is inside the polygon (even-odd) to pts;
    polygon vertices are integer ticks (TICK per pixel)"""
    xs = [p[0] for p in poly_ticks]
    ys = [p[1] for p in poly_ticks]
    y_lo = max(0, min(ys) // TICK)
    y_hi = min(bbox_h - 1, max(ys) // TICK + 1)
    x_lo = max(0, min(xs) // TICK)
    x_hi = min(bbox_w - 1, max(xs) // TICK + 1)
    n = len(poly_ticks)
    for py in range(y_lo, y_hi + 1):
        cy = py * TICK + TICK // 2
        cross = []                       # (num, den) with den > 0: x of each crossing
        for i in range(n):
            x1, y1 = poly_ticks[i]
            x2, y2 = poly_ticks[(i + 1) % n]
            if (y1 > cy) == (y2 > cy):
                continue
            num = x1 * (y2 - y1) + (cy - y1) * (x2 - x1)
            den = y2 - y1
            if den < 0:
                num, den = -num, -den
            cross.append((num, den))
        if not cross:
            continue
        for px in range(x_lo, x_hi + 1):
            cx = px * TICK + TICK // 2
            inside = 0
            for num, den in cross:
                if num < cx * den:
                    inside ^= 1
            if inside:
                pts.add((px, py))


def glyph_pixels(shapes, cap, slant=0.0, xscale=1.0):
    """set of (x, y) pixels of one glyph's shapes at cap height `cap` px;
    xscale < 1 condenses the letter (a narrower set of the same face)"""
    s = cap * TICK / UNITS
    out = set()
    w = int(math.ceil(cap * 1.2)) + int(math.ceil(cap * abs(slant))) + 2
    for sh in shapes:
        if isinstance(sh, tuple) and sh[0] == "ring":
            o, i = set(), set()
            _fill(_ticks(sh[1], s, slant, xscale), o, w, cap)
            _fill(_ticks(sh[2], s, slant, xscale), i, w, cap)
            out |= o - i
        else:
            _fill(_ticks(sh, s, slant, xscale), out, w, cap)
    return out


def _ticks(poly, s, slant, xscale):
    out = []
    for x, y in poly:
        xs = (x + (UNITS - y) * slant) * xscale
        out.append((int(round(xs * s)), int(round(y * s))))
    return out


def render(face, text, cap, gap=8.0, space=28.0, slant=0.0, xscale=1.0):
    """(pixels, width): the text set in the face at `cap` px cap height;
    pixels are (x, y) with y = 0 the cap top"""
    glyphs = parse(face) if isinstance(face, str) else face
    pts = set()
    pen = 0.0
    for ch in text:
        if ch == " ":
            pen += space
            continue
        if ch not in glyphs:
            raise SystemExit(f"[artface] no glyph {ch!r} in the face for {text!r}")
        adv, shapes = glyphs[ch]
        dx = int(round(pen * xscale * cap / UNITS))
        pts |= {(x + dx, y) for x, y in glyph_pixels(shapes, cap, slant, xscale)}
        pen += adv + gap
    w = max((x for x, _ in pts), default=-1) + 1
    return pts, w


def preview(face, text, cap, path, **kw):
    from PIL import Image
    pts, w = render(face, text, cap, **kw)
    im = Image.new("L", (w + 2, cap + 2), 255)
    px = im.load()
    for x, y in pts:
        px[x + 1, y + 1] = 0
    im.save(path)
    return w


if __name__ == "__main__":
    import sys
    face, text, cap, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    print(preview(face, text, cap, out, slant=float(sys.argv[5]) if len(sys.argv) > 5 else 0.0))
