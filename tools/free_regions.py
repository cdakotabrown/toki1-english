#!/usr/bin/env python3
"""free_regions.py - find main-exe code that nothing can reach (patch space).

The English module lives in the 12x12 kanji block (see build_patched.py).
When a profile needs more room (english-debug: the English module plus the
debug build), the extra pieces go into retail code that is DEAD: functions
that no live code, no data word and no overlay can ever reach.  Psy-Q links
whole library members, so the main exe carries Sony functions the game never
calls; this tool proves which ones, statically.

Reachability (conservative: every doubt makes a function live):
  * the function list is config/symbol_names.json (main functions with a
    size) united with the registered C windows of
    config/level3_functions.json (overlapping entries merge into the
    outer window); bytes no window covers count as DATA, so every word in
    them is a root (an unlisted function is never freed);
  * a REFERENCE to a function is any of, found anywhere in the referencing
    bytes (code or data, aligned words): a j / jal whose target lies inside
    it; a 32-bit word pointing inside it; a lui rX,hi followed within 64
    words by an addiu / ori / load / store with base rX whose effective
    address lies inside it; a branch (beq/bne/... incl. the regimm ones)
    whose target lies inside it (cross-function branches, gcc tail jumps);
  * roots: the PS-X EXE entry point, every reference from main-exe DATA
    (bytes no function covers), every reference from every overlay image
    (assets/overlays/*.EXN, all 26, EVENT and GYOZI included unless
    --exclude-overlay); o.bin (the debug build) is not part of the disc;
  * closure: a live function makes everything it references live; a live
    function whose last-but-one word is not an unconditional jump (j / jr /
    b) also makes the NEXT function live (fall-through);
  * `--keep ADDR` forces a function live (e.g. debug-only code a profile
    wants to keep).

The dead functions are merged into contiguous RANGES (the gap between two
dead functions must be zero bytes).  `--json OUT` writes them,
`--write-config OUT` writes the library-region ranges >= --min bytes as
config/patch/free_regions.json, which a profile names in
main.module.extra_regions_file; build_patched.py re-runs analyse() at every
build and refuses a region that is not inside a dead range (`--check START
END` asks the same question by hand).

Static unreachability is the claim; the runtime half is
config/patch/english-poison.json (every region filled with self-loop
traps) driven by soak_test.py / scene_sweep.py and compared frame by frame
with the plain English disc, plus soak_test.py's write watch on the
module pieces placed there (docs/translation/PS1-PATCH-STATUS.md 3.6).
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
TEXT_BASE = 0x80041000
FILE_BASE = 0x800

OP_J, OP_JAL = 2, 3
LOADSTORE = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A,
             0x2B, 0x2E, 0x32, 0x3A}   # lb lh lwl lw lbu lhu lwr sb sh swl sw swr lwc2 swc2
BRANCH = {4, 5, 6, 7}                  # beq bne blez bgtz


def load_exe(path: Path):
    raw = path.read_bytes()
    t_addr, t_size = struct.unpack_from("<II", raw, 0x18)
    pc0 = struct.unpack_from("<I", raw, 0x10)[0]
    img = raw[FILE_BASE:FILE_BASE + t_size]
    return t_addr, img, pc0


def main_functions(img_lo, img_hi):
    names = json.loads((DECOMP / "config" / "symbol_names.json").read_text())
    funcs = []
    for k, v in names["symbols"].items():
        if v.get("scope") not in ("main", None) or v.get("kind") != "func":
            continue
        a = int(k, 16)
        size = int(v.get("size") or 0)
        if size <= 0 or not (img_lo <= a < img_hi):
            continue
        funcs.append([a, size, v.get("name", k)])
    # the registered C windows (config/level3_functions.json) as well
    reg = json.loads((DECOMP / "config" / "level3_functions.json").read_text())
    for f in reg.get("functions", []):
        a = int(str(f.get("address", "0")), 16)
        size = int(f.get("size") or 0)
        if size > 0 and img_lo <= a < img_hi:
            funcs.append([a, size, f.get("name", hex(a))])
    funcs.sort()
    # overlapping entries (a head recorded inside its host): keep the outer
    out = []
    for f in funcs:
        if out and f[0] < out[-1][0] + out[-1][1]:
            end = max(out[-1][0] + out[-1][1], f[0] + f[1])
            out[-1][1] = end - out[-1][0]
            continue
        out.append(f)
    return out


def refs_in(data: bytes, base: int, lo: int, hi: int):
    """Every address in [lo, hi) the bytes `data` (loaded at `base`) can
    name.  Returns a set of addresses (not yet mapped to functions)."""
    out = set()
    n = len(data) // 4
    words = struct.unpack_from(f"<{n}I", data, 0)
    for i, w in enumerate(words):
        pc = base + 4 * i
        if lo <= w < hi:
            out.add(w)
        op = w >> 26
        if op in (OP_J, OP_JAL):
            t = ((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            if lo <= t < hi:
                out.add(t)
        elif op in BRANCH or op == 1:
            off = w & 0xFFFF
            if off & 0x8000:
                off -= 0x10000
            t = pc + 4 + (off << 2)
            if lo <= t < hi:
                out.add(t)
        if op == 0x0F:                      # lui
            rt = (w >> 16) & 31
            hi16 = (w & 0xFFFF) << 16
            for j in range(i + 1, min(n, i + 65)):
                w2 = words[j]
                op2 = w2 >> 26
                rs2 = (w2 >> 21) & 31
                rt2 = (w2 >> 16) & 31
                if rs2 == rt and (op2 in (0x09, 0x0D) or op2 in LOADSTORE):
                    imm = w2 & 0xFFFF
                    if op2 != 0x0D and imm & 0x8000:
                        imm -= 0x10000
                    a = (hi16 + imm) & 0xFFFFFFFF
                    if lo <= a < hi:
                        out.add(a)
                # lui rt redefined: stop following this one
                if op2 == 0x0F and rt2 == rt:
                    break
    return out


def ends_unconditionally(img, t_addr, f):
    """True when the function's last two words are an unconditional jump
    and its delay slot (control cannot fall into the next function)."""
    a, size, _ = f
    if size < 8:
        return False
    w = struct.unpack_from("<I", img, a + size - 8 - t_addr)[0]
    op = w >> 26
    if op == 0 and (w & 0x3F) == 0x08:
        return True                         # jr
    if op == OP_J:
        return True
    if op == 4 and ((w >> 21) & 31) == 0 and ((w >> 16) & 31) == 0:
        return True                         # b (beq zero,zero)
    return False


def analyse(exclude_overlays=(), keep=()):
    t_addr, img, pc0 = load_exe(DECOMP / "disks" / "SLPS_000.65")
    img_hi = t_addr + len(img)
    funcs = main_functions(t_addr, img_hi)
    starts = [f[0] for f in funcs]
    import bisect

    def func_of(addr):
        i = bisect.bisect_right(starts, addr) - 1
        if i >= 0 and addr < funcs[i][0] + funcs[i][1]:
            return i
        return None

    code_lo, code_hi = funcs[0][0], funcs[-1][0] + funcs[-1][1]
    roots = {func_of(pc0)}
    # data bytes of the exe: everything no function covers
    pos = t_addr
    for f in funcs + [[img_hi, 0, "end"]]:
        if f[0] > pos:
            off = (pos - t_addr) & ~3
            chunk = img[off:f[0] - t_addr]
            for a in refs_in(chunk, t_addr + off, code_lo, code_hi):
                roots.add(func_of(a))
        pos = max(pos, f[0] + f[1])
    ovl = {}
    for exn in sorted((DECOMP / "assets" / "overlays").glob("*.EXN")):
        if exn.stem in exclude_overlays:
            continue
        data = exn.read_bytes()
        data = data[:len(data) & ~3]
        rs = {func_of(a) for a in refs_in(data, 0x80132000, code_lo, code_hi)}
        rs.discard(None)
        ovl[exn.stem] = rs
        roots |= rs
    for k in keep:
        roots.add(func_of(k))
    roots.discard(None)
    # per-function outgoing references
    live = set()
    work = list(roots)
    while work:
        i = work.pop()
        if i in live:
            continue
        live.add(i)
        a, size, _ = funcs[i]
        body = img[a - t_addr:a - t_addr + size]
        body = body[:len(body) & ~3]
        for r in refs_in(body, a, code_lo, code_hi):
            j = func_of(r)
            if j is not None and j not in live:
                work.append(j)
        if i + 1 < len(funcs) and not ends_unconditionally(img, t_addr, funcs[i]):
            if funcs[i + 1][0] == a + size or \
                    not any(img[a + size - t_addr:funcs[i + 1][0] - t_addr]):
                work.append(i + 1)
    dead = [funcs[i] for i in range(len(funcs)) if i not in live]
    # merge contiguous dead functions (gap must be zero bytes)
    ranges = []
    for a, size, name in dead:
        if ranges:
            r = ranges[-1]
            gap = img[r["end"] - t_addr:a - t_addr]
            if a >= r["end"] and not any(gap):
                r["end"] = a + size
                r["functions"].append(name)
                continue
        ranges.append({"start": a, "end": a + size, "functions": [name]})
    for r in ranges:
        r["bytes"] = r["end"] - r["start"]
    return {"exe_text": [t_addr, img_hi], "functions": len(funcs),
            "live": len(live), "dead": len(dead),
            "dead_bytes": sum(f[1] for f in dead),
            "overlay_refs": {k: len(v) for k, v in ovl.items()},
            "ranges": ranges}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", help="write the dead ranges here")
    ap.add_argument("--min", type=int, default=256, help="list ranges >= N bytes")
    ap.add_argument("--exclude-overlay", action="append", default=[],
                    help="treat this overlay as never loaded (EVENT, GYOZI)")
    ap.add_argument("--keep", action="append", default=[],
                    help="force the function at ADDR live")
    ap.add_argument("--check", nargs=2, metavar=("START", "END"),
                    help="exit 1 unless [START, END) lies inside one dead range")
    ap.add_argument("--write-config", metavar="OUT",
                    help="write the ranges >= --min bytes at or above --from as a "
                         "regions file for build_patched.py (start rounded up to 16)")
    ap.add_argument("--from", dest="lo", default="0x80086000",
                    help="lowest address for --write-config (default: the "
                         "Sony library region)")
    args = ap.parse_args()
    res = analyse(tuple(args.exclude_overlay), [int(k, 16) for k in args.keep])
    if args.write_config:
        lo = int(args.lo, 16)
        regs = []
        for r in res["ranges"]:
            start = (r["start"] + 15) & ~15
            if r["start"] < lo or r["end"] - start < args.min:
                continue
            regs.append({"start": f"0x{start:08X}", "end": f"0x{r['end']:08X}",
                         "bytes": r["end"] - start, "functions": r["functions"]})
        regs.sort(key=lambda r: -r["bytes"])
        cfg = {"generated_by": "tools/patch/free_regions.py --write-config "
                               f"{args.write_config} --min {args.min} --from {args.lo}",
               "what": "retail main-exe code no live code, data word or overlay can "
                       "reach (static proof re-derived by build_patched.py at every "
                       "build); a profile's main.module.extra_regions_file places "
                       "module pieces here.  Runtime evidence: soak_test.py with the "
                       "english-poison profile (every region filled with a self-loop "
                       "trap) and the write watch of every soak run",
               "total_bytes": sum(r["bytes"] for r in regs),
               "regions": regs}
        Path(args.write_config).write_text(json.dumps(cfg, indent=1) + "\n")
        print(f"wrote {args.write_config}: {len(regs)} regions, {cfg['total_bytes']} bytes")
        return
    if args.check:
        lo, hi = (int(x, 16) for x in args.check)
        ok = any(r["start"] <= lo and hi <= r["end"] for r in res["ranges"])
        print(f"0x{lo:08X}-0x{hi:08X}: {'DEAD (free)' if ok else 'NOT inside a dead range'}")
        sys.exit(0 if ok else 1)
    print(f"{res['functions']} functions, {res['live']} live, {res['dead']} dead "
          f"({res['dead_bytes']} bytes)")
    big = [r for r in res["ranges"] if r["bytes"] >= args.min]
    for r in sorted(big, key=lambda r: -r["bytes"]):
        fs = r["functions"]
        print(f"  0x{r['start']:08X}-0x{r['end']:08X} {r['bytes']:6d} B  "
              f"{len(fs)} fn: {', '.join(fs[:6])}{' ...' if len(fs) > 6 else ''}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
