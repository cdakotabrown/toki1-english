#!/usr/bin/env python3
"""draw_log.py - decode the drawn-text log of the english-drawlog build.

The drawlog profile (config/patch/english-drawlog.json) records every
string drawn through set_kanji_string that still carries Japanese in a RAM
ring (src/patch/drawlog/drawlog.c: magic "DLG2" (DLG1 on older builds), head, counters, 160
entries of scene / step / sub-step / x / y / address / flags / first 20
bytes) and counts the English draws.  regtest_screens.py --dumpram (or
scene_sweep.py --dumpram) writes the 2 MB RAM; this tool finds the ring by
its magic, decodes the entries (patch encoding, the build's DTE table) and
says where each string lives by its address:

  exe data        0x80041000..0x800BF230   a main-exe string
  module / pool   0x800BF230..0x800CC2A4   the patch module / string pool
  overlay         0x80132000..0x80180000   the loaded overlay's image
  data buffer     0x80180000..0x80200000   a container / data file buffer
  work RAM        anything else            a formatter's line buffer, stack

  draw_log.py RAM.bin [RAM2.bin ...] [--dte build/patch/gen/dte.json]
              [--json OUT] [--md OUT]

Output: one line per distinct Japanese string (scene, position, source,
text), the English/Japanese draw counters, and a summary.  A clean run
logs nothing but the expected Japanese (the name-entry kana grids, a kana
name the player typed).
"""
import argparse
import json
import struct
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import locate                          # noqa: E402
import textcodec  # noqa: E402

MAGIC = b"DLG1"
MAGIC2 = b"DLG2"        # DLG1 + per-now_step English / Japanese draw counters
MAGIC3 = b"DLG3"        # DLG2 with the entry count in the header (64)
N = 160
ENTRY = 36
RAM_BASE = 0x80000000


def region(addr):
    if 0x80041000 <= addr < 0x800BF230:
        return "exe data"
    if 0x800BF230 <= addr < 0x800CC2A4:
        return "module/pool"
    if 0x80132000 <= addr < 0x80180000:
        return "overlay"
    if 0x80180000 <= addr < 0x80200000:
        return "data buffer"
    return "work RAM"


def find_ring(ram: bytes):
    """offset of the ring and its version (1 or 2), or (-1, 0)"""
    for magic, ver in ((MAGIC3, 3), (MAGIC2, 2), (MAGIC, 1)):
        i = ram.find(magic)
        while i >= 0 and i % 4:
            i = ram.find(magic, i + 1)
        if i >= 0:
            return i, ver
    return -1, 0


def parse(ram: bytes, dte):
    i, ver = find_ring(ram)
    if i < 0:
        return None
    head, n_jp, n_en = struct.unpack_from("<III", ram, i + 4)
    entries = []
    base = i + 16
    n = N
    if ver >= 3:
        n = struct.unpack_from("<I", ram, i + 16)[0]
        base = i + 20
    for k in range(n):
        o = base + ENTRY * ((head + k) % n)
        seq, scene, step, x, y, ptr, flags, sub = struct.unpack_from("<HBBhhIBB", ram, o)
        if ptr == 0:
            continue
        raw = ram[o + 14:o + 14 + 22].split(b"\0")[0]
        # the live string, when it is still in RAM, is the better source
        full = b""
        if RAM_BASE <= ptr < RAM_BASE + len(ram):
            p = ptr - RAM_BASE
            full = ram[p:p + 200].split(b"\0")[0]
        txt = textcodec.decode(full if full.startswith(raw[:4]) and full else raw, dte)
        entries.append({"seq": seq, "scene": scene, "step": step, "sub": sub, "x": x, "y": y,
                        "addr": f"0x{ptr:08X}", "source": region(ptr),
                        "english_strip": bool(flags & 1), "text": txt})
    scene_en, scene_jp = {}, {}
    if ver >= 2:
        o = base + ENTRY * n
        en = struct.unpack_from("<256H", ram, o)
        jp = struct.unpack_from("<256H", ram, o + 512)
        scene_en = {s: n for s, n in enumerate(en) if n}
        scene_jp = {s: n for s, n in enumerate(jp) if n}
    return {"at": f"0x{RAM_BASE + i:08X}", "version": ver, "head": head,
            "japanese_draws": n_jp, "english_draws": n_en,
            "step_english_draws": scene_en, "step_japanese_draws": scene_jp,
            "entries": entries}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ram", nargs="+")
    ap.add_argument("--dte", default="build/patch/gen/dte.json")
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args()
    p = locate(a.dte)
    dte = json.loads(p.read_text())["entries"] if p.exists() else None
    distinct = OrderedDict()
    runs = []
    for path in a.ram:
        ram = Path(path).read_bytes()
        r = parse(ram, dte)
        if r is None:
            print(f"[draw_log] {path}: no DLG1 ring (not an english-drawlog build, or never drawn)")
            continue
        runs.append({"ram": str(path), **{k: v for k, v in r.items() if k != "entries"}})
        print(f"[draw_log] {path}: {r['english_draws']} English draws, "
              f"{r['japanese_draws']} Japanese draws logged")
        if r["step_english_draws"] or r["step_japanese_draws"]:
            steps = sorted(set(r["step_english_draws"]) | set(r["step_japanese_draws"]))
            print("  per now_step (English/Japanese draws): " + ", ".join(
                f"{s}:{r['step_english_draws'].get(s, 0)}/{r['step_japanese_draws'].get(s, 0)}"
                for s in steps))
        for e in r["entries"]:
            key = (e["text"], e["source"])
            if key not in distinct:
                distinct[key] = dict(e, runs=[str(path)])
            elif str(path) not in distinct[key]["runs"]:
                distinct[key]["runs"].append(str(path))
    # expected: padding / button glyphs inside English strips (the 14-px
    # ideographic space of the yes/no lines, ○ × △ □)
    ok_chars = set("　○×△□")
    for key, e in list(distinct.items()):
        jp = {c for c in e["text"] if ord(c) > 0x7E}
        e["expected"] = bool(jp) and jp <= ok_chars
    lines = []
    for (txt, src), e in distinct.items():
        if e["expected"]:
            continue
        lines.append(f"scene {e['scene']:3d} step {e['step']:3d}/{e['sub']:<3d} ({e['x']:4d},{e['y']:4d}) "
                     f"{e['addr']} {src:12s}{' [in English strip]' if e['english_strip'] else ''}  {txt}")
    for ln in lines:
        print("  " + ln)
    n_exp = sum(1 for e in distinct.values() if e["expected"])
    print(f"[draw_log] {len(distinct)} distinct strings with Japanese characters across {len(runs)} "
          f"runs: {len(distinct) - n_exp} to look at, {n_exp} expected (only padding / button glyphs)")
    if a.json:
        Path(a.json).write_text(json.dumps({"runs": runs, "japanese": list(distinct.values())},
                                           ensure_ascii=False, indent=1) + "\n")
    if a.md:
        md = ["| scene | step | x,y | address | source | text | runs |", "|---:|---:|---|---|---|---|---:|"]
        for e in distinct.values():
            if e["expected"]:
                continue
            md.append(f"| {e['scene']} | {e['step']}/{e['sub']} | {e['x']},{e['y']} | `{e['addr']}` | "
                      f"{e['source']} | {e['text'].replace('|', '/')} | {len(e['runs'])} |")
        Path(a.md).write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
