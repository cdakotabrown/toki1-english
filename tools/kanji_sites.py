#!/usr/bin/env python3
"""kanji_sites.py - inventory of every set_kanji_string() call site in the
matched C (main exe + the overlays the retail game loads), with the call's
x/y arguments and, when the string argument is a named data symbol, the
Japanese it points at (decoded from the exe / EXN).  Output:
build/patch/kanji_sites.txt (one line per site) for the UI-text sweep.
"""
import glob
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
EXE = (DECOMP / "disks" / "SLPS_000.65").read_bytes()
DEAD = {"EVENT", "GYOZI"}
names = json.load(open(DECOMP / "config" / "symbol_names.json"))["symbols"]
name_addr = {v.get("name"): int(k, 16) for k, v in names.items()
             if re.match(r"^0x[0-9A-F]{8}$", k) and v.get("name")}


def sjis_at(data, off):
    e = data.find(b"\0", off)
    if e == -1 or e - off > 200:
        return None
    try:
        return data[off:e].decode("shift_jis")
    except UnicodeDecodeError:
        return None


def resolve(sym, ov, exn):
    m = re.match(r"^(?:D|func)_([0-9A-F]{8})$", sym)
    a = int(m.group(1), 16) if m else name_addr.get(sym)
    if a is None:
        return None
    if 0x80041000 <= a < 0x800E9000:
        return sjis_at(EXE, a - 0x80041000 + 0x800)
    if ov and 0x80132000 <= a < 0x80162000 and exn:
        return sjis_at(exn, a - 0x80132000)
    return None


CALL = re.compile(r"set_kanji_string\s*\(([^;]*?)\)\s*;", re.S)


def main():
    out = []
    files = [(None, f) for f in sorted(glob.glob(str(DECOMP / "src/main/matched/*.c")))]
    for ovdir in sorted(glob.glob(str(DECOMP / "src/overlay/*"))):
        ov = Path(ovdir).name
        if ov in DEAD:
            continue
        files += [(ov, f) for f in sorted(glob.glob(ovdir + "/*.c"))]
    exns = {}
    for ov, f in files:
        txt = open(f, errors="replace").read()
        if "set_kanji_string(" not in txt:
            continue
        if ov and ov not in exns:
            p = DECOMP / "assets" / "overlays" / f"{ov}.EXN"
            exns[ov] = p.read_bytes() if p.exists() else None
        for m in CALL.finditer(txt):
            args = [a.strip() for a in re.split(r",(?![^()]*\))", m.group(1))]
            if len(args) < 4 or "extern" in m.group(0):
                continue
            sarg = re.sub(r"^\(.*?\)\s*|&|\[.*", "", args[3]).strip()
            sym = re.match(r"[A-Za-z_][A-Za-z0-9_]*", sarg)
            jp = resolve(sym.group(0), ov, exns.get(ov)) if sym else None
            line = txt[:m.start()].count("\n") + 1
            out.append(f"{ov or 'main':9s} {Path(f).name:36s}:{line:<4d} x={args[0]:>8s} y={args[1]:>8s} "
                       f"attr={args[2]:>4s} str={args[3][:40]:40s} {jp!r}" if jp else
                       f"{ov or 'main':9s} {Path(f).name:36s}:{line:<4d} x={args[0]:>8s} y={args[1]:>8s} "
                       f"attr={args[2]:>4s} str={args[3][:40]}")
    dst = ROOT / "build" / "patch" / "kanji_sites.txt"
    dst.write_text("\n".join(out) + "\n")
    lit = sum(1 for o in out if o.rstrip().endswith("'"))
    print(f"{len(out)} call sites ({lit} with a resolved Japanese literal) -> {dst}")


if __name__ == "__main__":
    main()
