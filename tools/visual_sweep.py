#!/usr/bin/env python3
"""visual_sweep.py - the English visual sweep.

The drawn-text log (audit_drawn_text.py) sees every string the engine draws,
but not text baked into pictures.  This tool works on screenshots instead:
the PC port writes them with PC_SWEEP_DIR (pc/hal/sweep_shot.c: a capture
every N frames and after every step change, deduplicated per process), and

  collect RUN_ROOT... --db DIR   gather every run's frames into one database:
                                 DIR/frames.json (one row per UNIQUE picture
                                 across all runs: perceptual hash, route,
                                 step triple, path of one exemplar);
                                 near-identical pictures (petals, cursor
                                 blink) collapse by a 40x30 luma hash
  sheets --db DIR [--per 16]     contact sheets DIR/sheets/NNNN.png: 4x4
                                 grids of unique frames at 1x, each labelled
                                 with its id, route and step triple
  detect --db DIR                the Japanese-glyph detector over every
                                 unique frame -> DIR/detect.json (frames
                                 ranked by hits) and DIR/detect_sheets/
  art MANIFEST CELL PNG...       where a manifest cell's English / retail
                                 lettering shows (banners and logos the
                                 detector cannot read)
  scan PNG...                    the detector on single pictures (prints the
                                 hits; exit 1 if any)

The detector compares every 12x12 window of every single-colour ink mask of
the picture with the retail 12x12 font's kana and kanji (read from the
player's executable at run time; no glyph is stored): a window whose ink
is within a few pixels of a glyph is a hit.  Engine-drawn Japanese is caught
exactly; baked art drawn from the same font (most of the small UI labels)
is caught fuzzily; large or stylised lettering is not, which is why the
contact sheets exist and the review is visual.

Screenshots, sheets and databases live under build/ (never committed).
"""
import os
# one BLAS thread per process: the detector runs one process per core
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import argparse  # noqa: E402
import hashlib  # noqa: E402
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
EXE = DECOMP / "disks" / "SLPS_000.65"
FONT_BASE = 0x800BD250
RANGE_TABLE, RANGE_TABLE_END, FONT_MIN_CODE = 0x800BA530, 0x800BA5E4, 0x800BA52C

# Shift-JIS rows that are Japanese script (kana, kanji); symbols, Latin,
# digits, Greek and Cyrillic rows are left out on purpose
JP_RANGES = [(0x829F, 0x82F1), (0x8340, 0x8396)] + [
    (lead << 8 | 0x40, lead << 8 | 0xFC) for lead in range(0x88, 0x99)]


def _fo(addr):
    return addr - 0x80041000 + 0x800


def font_templates(exe_path=EXE, ranges=JP_RANGES):
    """(codes, bits[N,144] bool) of the retail font's Japanese glyphs"""
    exe = Path(exe_path).read_bytes()
    lo = struct.unpack_from("<H", exe, _fo(FONT_MIN_CODE))[0]
    n = (RANGE_TABLE_END - RANGE_TABLE) // 2
    tab = struct.unpack_from(f"<{n}H", exe, _fo(RANGE_TABLE))

    def gi(code):
        if code < lo:
            return None
        for i in range(0, n, 2):
            if code < tab[i]:
                return tab[i - 1] + (code - tab[i - 2])
        return None
    codes, rows = [], []
    seen = set()
    for a, b in ranges:
        for c in range(a, b + 1):
            if (c & 0xFF) == 0x7F:
                continue
            g = gi(c)
            if g is None or g >= 3418 or g in seen:
                continue
            raw = exe[_fo(FONT_BASE) + 18 * g:_fo(FONT_BASE) + 18 * g + 18]
            v = int.from_bytes(raw, "big")
            bits = np.array([(v >> (143 - i)) & 1 for i in range(144)], dtype=bool)
            if bits.sum() < 20:      # empty slots and glyphs too plain to tell
                                     # from a stroke of a picture (一 ー 二 ノ)
                continue
            seen.add(g)
            codes.append(c)
            rows.append(bits)
    return codes, np.array(rows)


class Detector:
    """fuzzy 12x12 font-glyph matcher over single-colour ink masks"""

    def __init__(self, exe_path=EXE, max_dist=None):
        self.codes, t = font_templates(exe_path)
        self.ink = t.sum(1).astype(np.float32)
        self.t = t.astype(np.float32)                # [N, 144]
        self.max_dist = max_dist or 0.18

    def scan(self, img, limit=60000):
        """hits [(x, y, code, dist)] in an RGB picture"""
        from numpy.lib.stride_tricks import sliding_window_view
        a = np.asarray(img.convert("RGB"), dtype=np.uint8)
        h, w = a.shape[:2]
        key = (a[:, :, 0].astype(np.uint32) << 16) | (a[:, :, 1].astype(np.uint32) << 8) | a[:, :, 2]
        vals, counts = np.unique(key, return_counts=True)
        hits = []
        for v, c in zip(vals, counts):
            if c < 12 or c > h * w // 6:
                continue
            mask = key == v
            ii = np.zeros((h + 1, w + 1), np.int32)
            ii[1:, 1:] = mask.cumsum(0).cumsum(1)
            ink = ii[12:, 12:] - ii[:-12, 12:] - ii[12:, :-12] + ii[:-12, :-12]   # [h-11, w-11]
            # the 14x14 ring around the window must be empty: a glyph is
            # drawn on a 14-px pitch, so its cell is isolated from its
            # neighbours (a long line or a busy picture is not)
            jj = np.zeros((h + 3, w + 3), np.int32)
            jj[2:h + 2, 2:w + 2] = ii[1:, 1:]
            jj[2:h + 2, w + 2] = ii[1:, w]
            jj[h + 2, 2:w + 2] = ii[h, 1:]
            jj[h + 2, w + 2] = ii[h, w]
            jj[h + 2, :2] = 0
            ring = jj[14:h + 3, 14:w + 3] - jj[:h - 11, 14:w + 3] - jj[14:h + 3, :w - 11] + jj[:h - 11, :w - 11]
            ys, xs = np.nonzero((ink >= 12) & (ink <= 90) & (ring[:h - 11, :w - 11] == ink))
            if len(ys) == 0 or len(ys) > limit:
                continue
            win = sliding_window_view(mask, (12, 12))[ys, xs].reshape(len(ys), 144).astype(np.float32)
            wink = ink[ys, xs].astype(np.float32)
            for s0 in range(0, len(ys), 4096):
                W = win[s0:s0 + 4096]
                d = wink[s0:s0 + 4096, None] + self.ink[None, :] - 2.0 * (W @ self.t.T)   # Hamming
                best = d.argmin(1)
                bd = d[np.arange(len(W)), best]
                lim = np.maximum(3, (self.ink[best] * self.max_dist).astype(int))
                for i in np.nonzero(bd <= lim)[0]:
                    hits.append((int(xs[s0 + i]), int(ys[s0 + i]),
                                 self.codes[best[i]], int(bd[i])))
        return _nms(hits)


def _nms(hits):
    """one hit per 12x12 cell: keep the best distance"""
    hits.sort(key=lambda h: h[3])
    kept = []
    for h in hits:
        if all(abs(h[0] - k[0]) >= 10 or abs(h[1] - k[1]) >= 10 for k in kept):
            kept.append(h)
    return kept


def sjis_char(code):
    try:
        return bytes([code >> 8, code & 0xFF]).decode("shift_jis")
    except UnicodeDecodeError:
        return "?"


# --- the database -------------------------------------------------------------------

def phash(img):
    g = np.asarray(img.convert("L").resize((40, 30), Image.BILINEAR), dtype=np.int16)
    q = (g // 24).astype(np.uint8)
    return hashlib.sha1(q.tobytes()).hexdigest()[:16]


def route_of(run_dir):
    meta = {}
    p = Path(run_dir) / "meta.txt"
    if p.exists():
        for line in p.read_text().splitlines():
            k, _, v = line.partition("=")
            meta[k] = v
    route = meta.get("PC_SWEEP_ROUTE") or ""
    inp = meta.get("PC_INPUT") or ""
    if inp:
        route = (route + ":" if route else "") + Path(inp).parent.name + "/" + Path(inp).stem
    scene = meta.get("SCENE") or meta.get("SCENE_NAV")
    if scene:
        route = (route + ":" if route else "") + "scene" + scene
    return route or Path(run_dir).name


def cmd_collect(args):
    db = Path(args.db)
    db.mkdir(parents=True, exist_ok=True)
    frames = {}
    old = db / "frames.json"
    if old.exists() and not args.fresh:
        for r in json.loads(old.read_text()):
            frames[r["phash"]] = r
    runs = []
    for root in args.roots:
        runs += sorted(p.parent for p in Path(root).rglob("index.tsv"))
    nimg = 0
    for run in runs:
        route = route_of(run)
        for line in (run / "index.tsv").read_text().splitlines():
            f = line.split("\t")
            if len(f) < 8:
                continue
            png = run / f[7]
            if not png.exists():
                continue
            nimg += 1
            try:
                img = Image.open(png)
                h = phash(img)
            except OSError:
                continue
            triple = f"{int(f[2]):02x}/{int(f[3]):02x}/{int(f[4]):02x}"
            r = frames.get(h)
            if r is None:
                frames[h] = {"phash": h, "path": str(png), "route": route,
                             "frame": int(f[0]), "step": triple, "girl": int(f[5]),
                             "seen": 1, "routes": [route]}
            else:
                r["seen"] += 1
                if route not in r["routes"] and len(r["routes"]) < 12:
                    r["routes"].append(route)
    rows = sorted(frames.values(), key=lambda r: (r["step"], r["route"], r["frame"]))
    for i, r in enumerate(rows):
        r["id"] = i
    old.write_text(json.dumps(rows, indent=0))
    print(f"collect: {len(runs)} runs, {nimg} pictures -> {len(rows)} unique "
          f"({len({r['step'] for r in rows})} step triples, "
          f"{len({r['step'][:2] for r in rows})} steps)")


def _label(r, extra=""):
    return f"#{r['id']} {r['step']} {r['route'][:30]}{extra}"


def write_sheets(rows, out, per=16, cols=4, mark=None):
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.png"):
        f.unlink()
    n = 0
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        rws = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 324, rws * 254), (40, 40, 40))
        d = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            x, y = (i % cols) * 324 + 2, (i // cols) * 254 + 12
            try:
                im = Image.open(r["path"]).convert("RGB")
            except OSError:
                continue
            if mark and r["id"] in mark:
                dd = ImageDraw.Draw(im)
                for hx, hy, *_ in mark[r["id"]]:
                    dd.rectangle([hx - 1, hy - 1, hx + 12, hy + 12], outline=(255, 0, 255))
            sheet.paste(im, (x, y))
            d.text((x, y - 11), _label(r), fill=(255, 255, 0))
        sheet.save(out / f"{n:04d}.png")
        n += 1
    return n


def cmd_sheets(args):
    db = Path(args.db)
    rows = json.loads((db / "frames.json").read_text())
    if args.steps:
        want = {s.lower() for s in args.steps.split(",")}
        rows = [r for r in rows if r["step"][:2] in want]
    if args.per_triple:
        # an animated background makes every frame unique: keep K frames
        # per step triple (and route), evenly spread, for the review
        groups = {}
        for r in rows:
            key = (r["step"], r["route"]) if args.by_route else r["step"]
            groups.setdefault(key, []).append(r)
        rows = []
        for g in groups.values():
            g.sort(key=lambda r: (r["route"], r["frame"]))
            k = args.per_triple
            rows += g if len(g) <= k else [g[round(i * (len(g) - 1) / (k - 1))] for i in range(k)] if k > 1 else g[:1]
        rows.sort(key=lambda r: (r["step"], r["route"], r["frame"]))
    out = Path(args.out) if args.out else db / "sheets"
    n = write_sheets(rows, out, args.per)
    print(f"sheets: {len(rows)} frames -> {n} sheets in {out}")


_DET = None


def _detect_init():
    global _DET
    _DET = Detector()


def _detect_one(path):
    det = _DET
    try:
        return det.scan(Image.open(path))
    except OSError:
        return []


def cmd_detect(args):
    from concurrent.futures import ProcessPoolExecutor
    db = Path(args.db)
    rows = json.loads((db / "frames.json").read_text())
    with ProcessPoolExecutor(args.jobs, initializer=_detect_init) as ex:
        res = list(ex.map(_detect_one, [r["path"] for r in rows], chunksize=8))
    out, mark = [], {}
    for r, hits in zip(rows, res):
        if len(hits) >= args.min_hits:
            out.append({"id": r["id"], "path": r["path"], "route": r["route"],
                        "step": r["step"], "hits": len(hits),
                        "text": "".join(sjis_char(h[2]) for h in sorted(hits, key=lambda h: (h[1] // 8, h[0])))[:60],
                        "boxes": [h[:2] for h in hits][:80]})
            mark[r["id"]] = hits
    out.sort(key=lambda o: -o["hits"])
    (db / "detect.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    flagged = [r for r in rows if r["id"] in mark]
    n = write_sheets(flagged, db / "detect_sheets", 16, mark=mark)
    print(f"detect: {len(out)} of {len(rows)} frames with >= {args.min_hits} hits "
          f"-> {db / 'detect.json'}, {n} sheets")


# ------------------------------------------------------------ art presence
# Large or stylised lettering (banners, logos) is invisible to the glyph
# detector, so its gate looks for the lettering itself: a manifest cell's
# ENGLISH picture is its committed PNG (our font render), its JAPANESE
# picture is cut at run time from the player's retail file (the pixels of
# the cell box whose index is one of the cell's `erase` indices, in the
# cell's CLUT); nothing of the game is stored.  A screenshot "shows" a
# picture when every opaque pixel of it appears at one position at 5-bit
# precision (the PC draws a 1:1 textured sprite as CLUT colour << 3),
# allowing `tol` of the pixels to differ (an overlapping sprite).

def _art_tools():
    sys.path.insert(0, str(TOOLS_PATCH))
    import nbn_inject
    return nbn_inject


def cell_pictures(manifest_path, cell_name, region=None):
    """(english, japanese) RGBA arrays of one manifest cell; `region`
    [x, y, w, h] inside the cell crops both (the part a sprite drawn in
    front of the cell leaves visible)"""
    ni = _art_tools()
    mpath = Path(manifest_path)
    if not mpath.is_absolute():
        mpath = locate(mpath)
    man = json.loads(mpath.read_text(encoding="utf-8"))
    cell = next(c for c in man["cells"] if c["name"] == cell_name)
    retail = (ni.EXTRACTED / man["file"]).read_bytes()
    clut = ni.load_clut(cell.get("clut", man.get("clut", {})), retail,
                        int(cell["fg"]) if str(cell["fg"]).isdigit() else 0)
    en = np.array(Image.open(mpath.parent / cell.get("png", cell["name"] + ".png")).convert("RGBA"))
    surf = ni.cell_surface(bytearray(retail), man, cell)
    x0, y0, w, h = ni.cell_box(cell)
    er = ni.erase_set(cell)
    ja = np.zeros((h, w, 4), np.uint8)
    for y in range(h):
        for x in range(w):
            v = surf.get(x0 + x, y0 + y)
            if v in er:
                ja[y, x] = tuple(clut[v]) + (255,)
    if region:
        rx, ry, rw, rh = (int(v) for v in region)
        en, ja = en[ry:ry + rh, rx:rx + rw], ja[ry:ry + rh, rx:rx + rw]
    return en, ja


def picture_at(img, pic, tol=0.03):
    """(x, y) where the RGBA picture `pic` shows in screenshot `img`, or None"""
    scr = (np.asarray(img.convert("RGB"), np.int16) >> 3)
    alpha = pic[:, :, 3] >= 128
    ys, xs = np.nonzero(alpha)
    if len(ys) == 0:
        return None
    col = pic[:, :, :3].astype(np.int16) >> 3
    want = col[ys, xs]
    ph, pw = pic.shape[:2]
    H, W = scr.shape[:2]
    # anchor: the opaque pixel whose colour is rarest on the screen
    best = None
    for k in range(0, len(ys), max(1, len(ys) // 16)):
        m = np.all(scr == want[k], axis=2)
        n = int(m.sum())
        if best is None or n < best[0]:
            best = (n, k, m)
    n, k, m = best
    cy, cx = np.nonzero(m)
    allowed = int(len(ys) * tol)
    for sy, sx in zip(cy - ys[k], cx - xs[k]):
        if sy < 0 or sx < 0 or sy + ph > H or sx + pw > W:
            continue
        got = scr[sy + ys, sx + xs]
        bad = int(np.any(got != want, axis=1).sum())
        if bad <= allowed:
            return int(sx), int(sy)
    return None


def cmd_art(args):
    en, ja = cell_pictures(args.manifest, args.cell,
                           [int(v) for v in args.region.split(",")] if args.region else None)
    found = 0
    for p in args.pngs:
        img = Image.open(p)
        e, j = picture_at(img, en), picture_at(img, ja)
        if e or j:
            print(f"{p}: english {e} japanese {j}")
        found |= bool(e) | (2 if j else 0)
    return 0 if found else 1


def cmd_scan(args):
    det = Detector()
    bad = 0
    for p in args.pngs:
        hits = det.scan(Image.open(p))
        txt = "".join(sjis_char(h[2]) for h in sorted(hits, key=lambda h: (h[1] // 8, h[0])))
        print(f"{p}: {len(hits)} hits {txt[:80]}")
        bad |= len(hits) >= args.min_hits
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("collect")
    p.add_argument("roots", nargs="+")
    p.add_argument("--db", required=True)
    p.add_argument("--fresh", action="store_true")
    p = sub.add_parser("sheets")
    p.add_argument("--db", required=True)
    p.add_argument("--per", type=int, default=16)
    p.add_argument("--steps", help="comma list of now_step values (hex) to keep")
    p.add_argument("--per-triple", type=int, default=0,
                   help="at most K frames per step triple, evenly spread")
    p.add_argument("--by-route", action="store_true", help="--per-triple per (triple, route)")
    p.add_argument("--out", help="sheet directory (default DB/sheets)")
    p = sub.add_parser("detect")
    p.add_argument("--db", required=True)
    p.add_argument("--jobs", type=int, default=os.cpu_count())
    p.add_argument("--min-hits", type=int, default=2)
    p = sub.add_parser("scan")
    p.add_argument("pngs", nargs="+")
    p.add_argument("--min-hits", type=int, default=2)
    p = sub.add_parser("art")
    p.add_argument("manifest")
    p.add_argument("cell")
    p.add_argument("pngs", nargs="+")
    p.add_argument("--region", help="x,y,w,h inside the cell")
    args = ap.parse_args()
    return {"collect": cmd_collect, "sheets": cmd_sheets, "detect": cmd_detect,
            "scan": cmd_scan, "art": cmd_art}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
