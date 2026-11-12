#!/usr/bin/env python3
"""tilemap_panel.py - read and re-encode the mod/srn tile-map pictures.

The TAIIKU and EN_NICHI instruction panels (SPSETU, KASETU, TASETU,
NINSETU x2, SHATEKI, KINGYO) are not sprite pages: the overlay loads the
file whole and rebuilds a 320x256 (or 384x256) 8-bpp picture in VRAM with
the main exe's tile-map routines (src/main/matched/mod_init.c,
srn_init.c, srn_vram_set.c, mod_trans_vram.c, get_fnt.c).  The format,
read here exactly as those routines read it:

  ptrs   a table of RAM pointers to the cell SHEETS (128x128 8-bpp, 256
         8x8 cells each, row-major);
  mod    a 16-byte header (word0 bits 24-31 = type, 0 = 8 bpp; word1 =
         tw, th, cell px, -) then the TILES: tile id n is tw*th words at
         mod + 16 + 4*tw*th*n, each word [sheet:8][cell:8][x:8][flags:8],
         flags bit0 = vertical flip, bit1 = horizontal flip (get_fnt);
  srn    a 20-byte header (word1 = w, h, tile px w, tile px h; word2 =
         tx, ty, srcW, srcH; word4 = entry count) then u32 entries, row
         stride srcW*tile_w/w, entry & 0xFFFF = the tile id at that grid
         position (0 = nothing drawn).  srn_vram_set skips a position
         whose column or row falls past its maxX / maxY arguments.

Editing such a picture means re-tiling it.  `Tilemap.retile` is
INCREMENTAL so the file keeps every byte it does not need to change:
grid positions whose 32x32 block is unchanged keep their tile and its
cells; a changed block reuses an existing tile or cell (any flip) when
one matches, otherwise it takes a tile slot / sheet cell that only
changed blocks used (or an unused, all-zero cell).  Nothing is written
into bytes another structure of the same file owns (the second NINSETU
panel overlaps the first one's tables), and the result is decoded again
and compared with the edited picture pixel for pixel; any mismatch or a
capacity overflow is refused.

  python3 tools/patch/tilemap_panel.py CDROM/TAIIKU/SPSETU.BIN 0x8018F000 0x801A19CC 0x8019D000 0x8019E190 --png out.png
  python3 tools/patch/tilemap_panel.py --self-test
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
EXTRACTED = DECOMP / "assets" / "extracted_iso"


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _off(v):
    return int(v, 16) if isinstance(v, str) else int(v)


class Tilemap:
    """one mod/srn picture inside a loaded file (file offsets = RAM - load
    address + base, base = the picture's byte offset inside the edited
    file, 0 normally)"""

    def __init__(self, data, spec, base=0):
        self.d = data
        self.name = spec.get("name", "panel")
        self.load = _off(spec["load"])
        self.base = base
        fo = self.fo
        self.mod = fo(_off(spec["mod"]))
        self.srn = fo(_off(spec["srn"]))
        self.ptr = fo(_off(spec["ptrs"]))
        self.max_x, self.max_y = (int(v) for v in spec.get("vram_limit", [1408, 240]))
        m0, m1 = _u32(data, self.mod), _u32(data, self.mod + 4)
        if (m0 >> 24) not in (0, 3, 4, 5):
            raise SystemExit(f"[tilemap] {self.name}: mod type {m0 >> 24} is not 8 bpp")
        self.tw, self.th, self.cpx = m1 >> 24, (m1 >> 16) & 255, (m1 >> 8) & 255
        if self.cpx != 8:
            raise SystemExit(f"[tilemap] {self.name}: {self.cpx}-px cells are not handled")
        s1, s2 = _u32(data, self.srn + 4), _u32(data, self.srn + 8)
        w, h, tpw, tph = s1 >> 24, (s1 >> 16) & 255, (s1 >> 8) & 255, s1 & 255
        tx, ty, srcw, srch = s2 >> 24, (s2 >> 16) & 255, (s2 >> 8) & 255, s2 & 255
        if (tpw, tph) != (self.tw * 8, self.th * 8):
            raise SystemExit(f"[tilemap] {self.name}: srn tile {tpw}x{tph} vs mod {self.tw}x{self.th} cells")
        self.tpw, self.tph = tpw, tph
        self.stride = srcw * tpw // w
        self.count = _u32(data, self.srn + 16)
        self.wpt = self.tw * self.th                        # words per tile
        # the positions srn_vram_set draws (its maxX / maxY test)
        self.pos = {}
        self.dead = []                  # byte runs of srn entries srn_vram_set never draws
        rows = srch * tph // h
        for i in range(self.count):
            row, col = divmod(i, self.stride)
            if row >= rows:
                break
            if not ((col - 1) * tpw + tx * w < self.max_x and (row - 1) * tph + ty * h < self.max_y):
                o = self.srn + 20 + 4 * i
                if self.dead and self.dead[-1][1] == o:
                    self.dead[-1][1] = o + 4
                else:
                    self.dead.append([o, o + 4])
                continue
            tid = _u32(data, self.srn + 20 + 4 * i) & 0xFFFF
            if tid:
                self.pos[(row, col)] = (i, tid)
        self.gh = max(r for r, _ in self.pos) + 1
        self.gw = max(c for _, c in self.pos) + 1
        self.h, self.w = self.gh * tph, self.gw * tpw
        sheets = sorted({self.word(t, k) >> 24 for _, t in self.pos.values() for k in range(self.wpt)})
        self.sheets = {s: fo(_u32(data, self.ptr + 4 * s)) for s in sheets}

    def fo(self, ram):
        return ram - self.load + self.base

    # --- raw access -------------------------------------------------------------
    def tile_off(self, tid):
        return self.mod + 16 + 4 * self.wpt * tid

    def word(self, tid, k, d=None):
        return _u32(self.d if d is None else d, self.tile_off(tid) + 4 * k)

    def cell_off(self, sheet, cell):
        """file offset of row 0 of the cell; rows are 128 bytes apart"""
        cy, cx = divmod(cell, 16)
        return self.sheets[sheet] + cy * 8 * 128 + cx * 8

    def cell_px(self, sheet, cell, d=None):
        d = self.d if d is None else d
        o = self.cell_off(sheet, cell)
        return tuple(bytes(d[o + 128 * r:o + 128 * r + 8]) for r in range(8))

    def cell_ranges(self, sheet, cell):
        o = self.cell_off(sheet, cell)
        return [(o + 128 * r, o + 128 * r + 8) for r in range(8)]

    # --- decode -----------------------------------------------------------------
    def decode(self, d=None):
        """the picture as a list of bytearray rows (0 where nothing is drawn)"""
        plane = [bytearray(self.w) for _ in range(self.h)]
        for (gy, gx), (_, tid) in self.pos.items():
            for k in range(self.wpt):
                wd = self.word(tid, k, d)
                px = flip(self.cell_px(wd >> 24, (wd >> 16) & 255, d), wd & 3)
                r, c = divmod(k, self.tw)
                y, x = gy * self.tph + r * 8, gx * self.tpw + c * 8
                for j in range(8):
                    plane[y + j][x:x + 8] = px[j]
        return plane

    def block(self, plane, gy, gx):
        return [bytes(plane[gy * self.tph + j][gx * self.tpw:(gx + 1) * self.tpw]) for j in range(self.tph)]

    def owned(self):
        """byte ranges this picture's structures occupy (headers, the srn
        entry table, the pointer table, every tile and cell its positions
        use)"""
        rs = [(self.mod, self.mod + 16), (self.srn, self.srn + 20 + 4 * self.count),
              (self.ptr, self.ptr + 4 * (max(self.sheets) + 1))]
        for _, tid in self.pos.values():
            rs.append((self.tile_off(tid), self.tile_off(tid) + 4 * self.wpt))
            for k in range(self.wpt):
                wd = self.word(tid, k)
                rs += self.cell_ranges(wd >> 24, (wd >> 16) & 255)
        return rs


def flip(px, fl):
    if fl & 1:
        px = px[::-1]
    if fl & 2:
        px = tuple(r[::-1] for r in px)
    return px


def _hits(rs, lo, hi):
    return any(a < hi and lo < b for a, b in rs)


def extra_tile_slots(tm, locked):
    """tile ids whose words would sit wholly inside a run of srn entries
    that srn_vram_set never draws (columns past its maxX test, rows past
    maxY) and are zero: a tile id is just an index from the mod table, so
    such a slot is storage the game reads only through that id"""
    out = []
    base = tm.mod + 16
    size = 4 * tm.wpt
    for a, b in tm.dead:
        t = max(1, -(-(a - base) // size))
        while base + size * (t + 1) <= b and t <= 0xFFFF:
            lo, hi = base + size * t, base + size * (t + 1)
            if not _hits(locked, lo, hi) and not any(tm.d[lo:hi]):
                out.append(t)
            t += 1
    return out


def retile(tm, new_plane, others=()):
    """Write `new_plane` into tm's file bytes (tm.d) incrementally.
    others: the other Tilemaps of the same file (their bytes are kept).
    Returns a one-line report; raises SystemExit when it does not fit."""
    d = tm.d
    old = tm.decode()
    others_before = [o.decode() for o in others]
    if len(new_plane) != tm.h or any(len(r) != tm.w for r in new_plane):
        raise SystemExit(f"[tilemap] {tm.name}: the edited picture is not {tm.w}x{tm.h}")
    changed = {p for p in tm.pos if tm.block(old, *p) != tm.block(new_plane, *p)}
    if not changed:
        return f"{tm.name}: unchanged"
    kept_pos = [p for p in tm.pos if p not in changed]
    kept_tids = {tm.pos[p][1] for p in kept_pos}
    freed_tids = sorted({tm.pos[p][1] for p in changed} - kept_tids)

    def cells_of(tids):
        out = set()
        for t in tids:
            for k in range(tm.wpt):
                wd = tm.word(t, k)
                out.add((wd >> 24, (wd >> 16) & 255))
        return out

    kept_cells = cells_of(kept_tids)
    # bytes nobody may overwrite: the other pictures' structures, this
    # picture's headers / srn / ptr table, the kept tiles and cells
    foreign = [r for o in others for r in o.owned()]
    own_fixed = [(tm.mod, tm.mod + 16), (tm.srn, tm.srn + 20 + 4 * tm.count),
                 (tm.ptr, tm.ptr + 4 * (max(tm.sheets) + 1))]
    kept_tile_rs = [(tm.tile_off(t), tm.tile_off(t) + 4 * tm.wpt) for t in kept_tids]
    kept_cell_rs = [r for s, c in kept_cells for r in tm.cell_ranges(s, c)]
    locked = foreign + own_fixed + kept_tile_rs + kept_cell_rs

    def free_cell(s, c):
        return not any(_hits(locked, a, b) for a, b in tm.cell_ranges(s, c))

    free_cells = [sc for sc in sorted(cells_of(freed_tids) - kept_cells) if free_cell(*sc)]
    used_any = cells_of({t for _, t in tm.pos.values()})
    for s in sorted(tm.sheets):                       # never-used cells that are blank
        for c in range(256):
            if (s, c) not in used_any and free_cell(s, c) and \
                    not any(any(r) for r in tm.cell_px(s, c)):
                free_cells.append((s, c))
    free_tids = [t for t in freed_tids
                 if not _hits(foreign + own_fixed + kept_tile_rs,
                              tm.tile_off(t), tm.tile_off(t) + 4 * tm.wpt)]

    # cell library: content (any flip) -> (sheet, cell, flags)
    lib = {}

    def add_lib(px, s, c):
        for fl in (0, 1, 2, 3):
            lib.setdefault(flip(px, fl), (s, c, fl))

    for s, c in sorted(kept_cells):
        add_lib(tm.cell_px(s, c), s, c)
    tiles = {}                                       # tile words -> tid
    for t in sorted(kept_tids):
        tiles.setdefault(tuple(tm.word(t, k) for k in range(tm.wpt)), t)
    new_cells = new_tiles = reused_tiles = n_extra = 0
    extra = None
    writes = []                                      # deferred cell writes
    for p in sorted(changed):
        blk = tm.block(new_plane, *p)
        words = []
        for k in range(tm.wpt):
            r, c = divmod(k, tm.tw)
            px = tuple(blk[r * 8 + j][c * 8:c * 8 + 8] for j in range(8))
            hit = lib.get(px)
            if hit is None:
                if not free_cells:
                    raise SystemExit(f"[tilemap] {tm.name}: out of sheet cells at block {p} "
                                     f"({new_cells} new cells placed)")
                s, cc = free_cells.pop(0)
                writes.append((s, cc, px))
                add_lib(px, s, cc)
                hit = (s, cc, 0)
                new_cells += 1
            s, cc, fl = hit
            words.append(s << 24 | cc << 16 | fl)
        words = tuple(words)
        tid = tiles.get(words)
        if tid is None:
            if not free_tids:
                if extra is None:
                    extra = extra_tile_slots(tm, foreign + kept_tile_rs + [
                        (tm.mod, tm.mod + 16), (tm.srn, tm.srn + 20),
                        (tm.ptr, tm.ptr + 4 * (max(tm.sheets) + 1))])
                if not extra:
                    raise SystemExit(f"[tilemap] {tm.name}: out of tile slots at block {p} "
                                     f"({new_tiles} new tiles placed)")
                free_tids.append(extra.pop(0))
                n_extra += 1
            tid = free_tids.pop(0)
            tiles[words] = tid
            for k, wd in enumerate(words):
                struct.pack_into("<I", d, tm.tile_off(tid) + 4 * k, wd)
            new_tiles += 1
        else:
            reused_tiles += 1
        i = tm.pos[p][0]
        e = _u32(d, tm.srn + 20 + 4 * i)
        struct.pack_into("<I", d, tm.srn + 20 + 4 * i, (e & 0xFFFF0000) | tid)
        tm.pos[p] = (i, tid)
    for s, c, px in writes:
        o = tm.cell_off(s, c)
        for j in range(8):
            d[o + 128 * j:o + 128 * j + 8] = px[j]
    # the gate: decode the written bytes again
    back = tm.decode()
    if back != [bytearray(r) for r in new_plane]:
        bad = sum(a != b for ra, rb in zip(back, new_plane) for a, b in zip(ra, rb))
        raise SystemExit(f"[tilemap] {tm.name}: re-decode differs from the edit in {bad} pixels")
    for o, before in zip(others, others_before):     # and the neighbours are untouched
        if o.decode() != before:
            raise SystemExit(f"[tilemap] {tm.name}: changed {o.name}")
    return (f"{tm.name}: {len(changed)} blocks re-tiled, {new_tiles} tiles written "
            f"({reused_tiles} shared, {n_extra} in undrawn srn entries), {new_cells} cells written, "
            f"{len(free_cells)} cells / {len(free_tids)} tile slots left")


# --- CLI / self-test --------------------------------------------------------------

def _png(tm, plane, clut, path, k=2):
    from PIL import Image
    im = Image.new("RGB", (tm.w, tm.h))
    px = im.load()
    for y in range(tm.h):
        for x in range(tm.w):
            px[x, y] = clut[plane[y][x]]
    im.resize((tm.w * k, tm.h * k), Image.NEAREST).save(path)


def file_clut(d, off=0, n=256):
    out = []
    for i in range(n):
        v = struct.unpack_from("<H", d, off + 2 * i)[0]
        out.append(((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31))
    return out


def self_test(path, spec):
    """round trip + an edit + negative controls on one retail panel"""
    retail = (EXTRACTED / path).read_bytes()
    d = bytearray(retail)
    tm = Tilemap(d, spec)
    plane = tm.decode()
    assert retile(tm, plane).endswith("unchanged") and bytes(d) == retail, "identity re-tile changed bytes"
    # an edit: a 40x12 block of one colour in the middle of the picture
    ed = [bytearray(r) for r in plane]
    for y in range(80, 92):
        for x in range(100, 140):
            ed[y][x] = 17
    rep = retile(tm, ed)
    assert Tilemap(d, spec).decode() == ed, "edit did not round-trip"
    # negative control 1: a re-decode check catches a corrupted cell
    bad = bytearray(d)
    tmb = Tilemap(bad, spec)
    wd = tmb.word(tmb.pos[(2, 3)][1], 5)
    o = tmb.cell_off(wd >> 24, (wd >> 16) & 255)
    bad[o] ^= 0x55
    assert Tilemap(bad, spec).decode() != ed, "a corrupted cell was not seen"
    # negative control 2: noise everywhere does not fit and is refused
    import random
    rnd = random.Random(1)
    noisy = [bytearray(rnd.randrange(256) for _ in range(tm.w)) for _ in range(tm.h)]
    try:
        retile(Tilemap(bytearray(retail), spec), noisy)
    except SystemExit as e:
        assert "out of" in str(e), e
    else:
        raise AssertionError("a picture of noise was accepted")
    return rep


SPSETU = dict(name="spoon_relay", load="0x8018F000", mod="0x8019D000", srn="0x8019E190",
              ptrs="0x801A19CC")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("load", nargs="?")
    ap.add_argument("ptrs", nargs="?")
    ap.add_argument("mod", nargs="?")
    ap.add_argument("srn", nargs="?")
    ap.add_argument("--png")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        print("[tilemap] self-test:", self_test("CDROM/TAIIKU/SPSETU.BIN", SPSETU))
        return
    d = bytearray((EXTRACTED / a.file).read_bytes())
    tm = Tilemap(d, dict(load=a.load, ptrs=a.ptrs, mod=a.mod, srn=a.srn))
    print(f"{a.file}: {tm.w}x{tm.h}, {len(tm.pos)} positions, "
          f"{len({t for _, t in tm.pos.values()})} tiles, sheets "
          + ", ".join(f"{s}@0x{o:X}" for s, o in tm.sheets.items()))
    if a.png:
        _png(tm, tm.decode(), file_clut(d), a.png)


if __name__ == "__main__":
    main()
