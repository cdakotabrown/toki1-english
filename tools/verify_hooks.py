#!/usr/bin/env python3
"""verify_hooks.py - read back every hook and call-site redirect of a patch
build from the BYTES it wrote, independently of build_patched.py's own code
path, and check each one against the profile and the naming ledger.

For every `main.module.hooks[]` and `overlays.<OV>.hooks[]` entry:
  * the profile's `addr` is a function the ledger (or the main registry /
    the overlay's .sym window) knows, and the documentary `function` is the
    ledger's CURRENT name for it (else: run sync_patch_symbols.py --apply);
  * the patched exe / EXN holds `j <target>; nop` at the window, `target`
    being the module symbol of the build report, inside the module;
  * the clean base holds something else there (the retail prologue).
For every call-site redirect: the clean word is `jal <expect>` (expect
resolved through the ledger, or a hex address) and the patched word is
`jal <target>`.

  verify_hooks.py [--profile config/patch/english.json] [--out build/patch]
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import patch_symbols as PS  # noqa: E402

TEXT_BASE, FILE_BASE, OV_BASE = 0x80041000, 0x800, 0x80132000
CLEAN_EXE = ROOT / "build" / "SLPS_000.65.clean"
RETAIL_EXE = DECOMP / "disks" / "SLPS_000.65"


def load_profile(path: Path) -> dict:
    prof = json.loads(path.read_text())
    if "include" in prof:
        import build_patched
        return build_patched.load_profile(path)
    return prof


def j(addr):
    return (2 << 26) | ((addr >> 2) & 0x3FFFFFF)


def jal(addr):
    return (3 << 26) | ((addr >> 2) & 0x3FFFFFF)


def word(data, off):
    return struct.unpack_from("<I", data, off)[0]


def sym_window(ov, addr):
    for line in (DECOMP / "config" / "overlay" / f"{ov}.sym").read_text().splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 3 and parts[0].lower().startswith("0x"):
            try:
                start, size = int(parts[0], 16), int(parts[1])
            except ValueError:
                continue
            if start <= addr < start + size:
                return start, size
    return None


def registered(addr):
    reg = json.loads((DECOMP / "config" / "level3_functions.json").read_text())
    return any(int(str(f.get("address", "0")), 16) == addr for f in reg.get("functions", []))


def verify(profile_path: Path, out: Path):
    prof = load_profile(profile_path)
    name = prof["name"]
    rep = json.loads((out / f"{name}.report.json").read_text())
    syms = {k: int(v, 16) for k, v in rep.get("module", {}).get("symbols", {}).items()}
    mod_lo = int(rep["module"]["base"], 16) if "module" in rep else 0
    mod_hi = int(rep["module"]["end"], 16) if "module" in rep else 0
    xr = [(int(r["start"], 16), int(r["end"], 16))
          for r in rep.get("module", {}).get("extra_regions", [])]
    L = PS.ledger()
    exe = (out / "SLPS_000.65").read_bytes()
    clean = CLEAN_EXE.read_bytes() if CLEAN_EXE.exists() else RETAIL_EXE.read_bytes()
    errs, n = [], 0

    def in_module(a):
        return mod_lo <= a < mod_hi or any(lo <= a < hi for lo, hi in xr)

    def target_of(h, where):
        t = h.get("target", h["function"])
        a = syms.get(t)
        if a is None:
            errs.append(f"{where}: target {t} is not a module symbol of the build report")
        elif not in_module(a):
            errs.append(f"{where}: target {t} 0x{a:08X} is outside the module")
        return a

    def check_name(h, scope, a, where):
        key = L.func_at(a, scope)
        if key is None:
            errs.append(f"{where}: no ledger record for the function at 0x{a:08X}")
            return
        cur = L.name_at(key, scope, "func")
        if h["function"] != cur:
            errs.append(f"{where}: documentary name {h['function']} is stale, the ledger "
                        f"calls 0x{key:08X} {cur}; run `{PS.SYNC_HINT}`")

    for h in prof.get("main", {}).get("module", {}).get("hooks", []):
        n += 1
        a = int(h["addr"], 16)
        where = f"main hook {h['function']} 0x{a:08X}"
        if ("main", a) in L.records or not registered(a):
            check_name(h, "main", a, where)
        t = target_of(h, where)
        off = a - TEXT_BASE + FILE_BASE
        if t is not None and (word(exe, off), word(exe, off + 4)) != (j(t), 0):
            errs.append(f"{where}: patched words {word(exe, off):08X} {word(exe, off + 4):08X}"
                        f" are not `j 0x{t:08X}; nop`")
        if word(clean, off) >> 26 == 2:
            errs.append(f"{where}: the clean exe already holds a `j` there")
    for cs in prof.get("main", {}).get("callsites", []):
        n += 1
        at = int(cs["at"], 16)
        e = cs["expect"]
        ea = int(e, 16) if e.startswith("0x") else L.resolve(e, "main").addr
        where = f"main callsite 0x{at:08X} ({e} -> {cs['target']})"
        off = at - TEXT_BASE + FILE_BASE
        if ea is None:
            errs.append(f"{where}: {L.resolve(e, 'main').message()}")
        elif word(clean, off) != jal(ea):
            errs.append(f"{where}: clean word {word(clean, off):08X} is not jal 0x{ea:08X}")
        t = syms.get(cs["target"])
        if t is None or word(exe, off) != jal(t):
            errs.append(f"{where}: patched word {word(exe, off):08X} is not jal {cs['target']}")
    for ov, spec in prof.get("overlays", {}).items():
        if not spec.get("hooks") and not spec.get("callsites"):
            continue
        exn = (out / "EXEDIR" / f"{ov}.EXN").read_bytes()
        cexn = ROOT / "build" / "overlay" / ov / f"{ov}.clean.EXN"
        cexn = (cexn if cexn.exists() else DECOMP / "assets" / "overlays" / f"{ov}.EXN").read_bytes()
        for h in spec.get("hooks", []):
            n += 1
            a = int(h["addr"], 16)
            where = f"{ov} hook {h['function']} 0x{a:08X}"
            win = sym_window(ov, a)
            if win is None:
                errs.append(f"{where}: no config/overlay/{ov}.sym window covers it")
                continue
            check_name(h, ov, a, where)
            t = target_of(h, where)
            off = win[0] - OV_BASE
            if t is not None and (word(exn, off), word(exn, off + 4)) != (j(t), 0):
                errs.append(f"{where}: patched words at the window 0x{win[0]:08X} are not "
                            f"`j 0x{t:08X}; nop`")
            if word(cexn, off) >> 26 == 2:
                errs.append(f"{where}: the clean EXN already holds a `j` there")
        for cs in spec.get("callsites", []):
            n += 1
            at = int(cs["at"], 16)
            e = cs["expect"]
            ea = int(e, 16) if e.startswith("0x") else L.resolve(e, ov).addr
            where = f"{ov} callsite 0x{at:08X}"
            off = at - OV_BASE
            if ea is None or word(cexn, off) != jal(ea):
                errs.append(f"{where}: clean word {word(cexn, off):08X} is not jal {e}")
            t = syms.get(cs["target"])
            if t is None or word(exn, off) != jal(t):
                errs.append(f"{where}: patched word {word(exn, off):08X} is not jal {cs['target']}")
    return n, errs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=str(PATCH_CONFIG / "english.json"))
    ap.add_argument("--out", help="the build's output directory (default: the profile's)")
    a = ap.parse_args()
    prof = load_profile(Path(a.profile))
    out = Path(a.out) if a.out else locate(prof.get("out", "build/patch"))
    n, errs = verify(Path(a.profile), out)
    for e in errs:
        print(f"ERROR {e}")
    print(f"[verify_hooks] {n} hooks / call sites, {len(errs)} errors")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
