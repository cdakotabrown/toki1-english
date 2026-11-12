#!/usr/bin/env python3
"""Map every static pointer that targets an extracted script string.

The text injector (tools/translation/inject_text.py) currently enforces
translation <= original byte length, because it patches each Japanese string in
place and has no way to move it. This scanner removes that limitation for the
PS1 build: for every string in translation/tokimeki_script.csv that lives in a
statically-addressable executable (the main PS-X EXE or an .EXN overlay), it
finds the pointer SITES that reference the string's runtime address. Once the
injector knows those sites it can relocate a string into free space and rewrite
its pointers, dropping the byte budget entirely.

Two reference kinds are detected, both rewritable:

  word  -- a 4-byte little-endian data word whose value == the string vaddr
           (string-pointer tables). Rewrite = overwrite the word.
  hilo  -- a MIPS `lui rX, %hi` paired with a later `addiu/ori/lw/sw/...`
           on rX that computes the string vaddr (the normal way code names a
           string). Rewrite = patch the lui immediate + the low-half immediate.

Address model (verified from the on-disk headers, not assumed):
  main PS-X EXE : body starts at file 0x800; vaddr = t_addr + (off - 0x800),
                  where t_addr is read live from the EXE header (0x80041000).
  .EXN overlays : headerless, loaded whole to 0x80132000 (CLAUDE.md); every
                  overlay shares that base, so a pointer whose target lands in
                  overlay space is only unambiguous WITHIN its own file. Such
                  cross-file coincidences are reported but never asserted as a
                  specific string -- this tool does not fabricate matches.

CDROM data containers are skipped for pointer scanning: they are DMA'd to
runtime buffers whose addresses are not statically known, so no 0x80xxxxxx
pointer can be resolved against them.

Output (deterministic, idempotent):
  translation/text_pointers.json  -- manifest the injector consumes.
  stdout                          -- human summary.

Usage: .venv/bin/python3 tools/translation/map_text_pointers.py [--out PATH]
"""
import csv
import json
import struct
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import locate  # noqa: E402
SHEET = locate("translation/tokimeki_script.csv")
DEFAULT_OUT = locate("translation/text_pointers.json")

OVERLAY_BASE = 0x80132000          # CLAUDE.md: every .EXN loads here.
EXE_BODY_OFFSET = 0x800            # PS-X EXE header size.
RAM_LO, RAM_HI = 0x80000000, 0x80200000   # 2 MiB kseg0 window.

# MIPS-I opcodes we reconstruct addresses from.
OP_LUI = 0x0F
OP_ADDIU = 0x09
OP_ADDI = 0x08
OP_ORI = 0x0D
# base+offset memory ops: address = base_reg + signed_offset.
LOAD_OPS = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26}          # lb..lwr
STORE_OPS = {0x28, 0x29, 0x2A, 0x2B, 0x2E}                     # sb..swr
ADDR_I_OPS = {OP_ADDIU, OP_ADDI, OP_ORI}


def sign16(v):
    return v - 0x10000 if v & 0x8000 else v


class LoadImage:
    """A statically-addressable binary: file bytes + offset<->vaddr mapping."""

    def __init__(self, relpath, data, base, body_offset):
        self.relpath = relpath
        self.data = data
        self.base = base
        self.body_offset = body_offset

    def off_to_vaddr(self, off):
        return (self.base + (off - self.body_offset)) & 0xFFFFFFFF

    def vaddr_to_off(self, vaddr):
        off = (vaddr - self.base) + self.body_offset
        return off if 0 <= off < len(self.data) else None


def open_image(relpath):
    """Return a LoadImage for a main EXE or .EXN overlay, else None."""
    path = locate(relpath)
    if not path.exists():
        return None
    data = path.read_bytes()
    if data[:8] == b"PS-X EXE":
        t_addr = struct.unpack_from("<I", data, 0x18)[0]
        return LoadImage(relpath, data, t_addr, EXE_BODY_OFFSET)
    if relpath.upper().endswith(".EXN"):
        # Headerless overlay. Guard against a surprise header rather than
        # silently mapping garbage.
        if data[:8] == b"PS-X EXE":
            return None
        return LoadImage(relpath, data, OVERLAY_BASE, 0)
    return None


def load_strings():
    """string rows grouped by file, restricted to addressable executables."""
    rows = list(csv.DictReader(open(SHEET, encoding="utf-8")))
    by_file = {}
    for r in rows:
        rel = r["File"]
        if not (rel.endswith(".EXN") or "SLPS_000.65" in rel):
            continue
        by_file.setdefault(rel, []).append({
            "id": r["ID"],
            "offset": int(r["Offset"], 16),
            "bytes": int(r["Bytes"]),
        })
    return by_file


def scan_words(img, vaddr_to_id, other_overlay_vaddrs):
    """Aligned 32-bit LE words whose value is a known string vaddr."""
    hits = []
    ambiguous = 0
    data = img.data
    for off in range(0, len(data) - 3, 4):
        val = struct.unpack_from("<I", data, off)[0]
        if not (RAM_LO <= val < RAM_HI):
            continue
        sid = vaddr_to_id.get(val)
        if sid is not None:
            hits.append((off, val, sid))
        elif OVERLAY_BASE <= val < RAM_HI and val in other_overlay_vaddrs:
            ambiguous += 1
    return hits, ambiguous


def scan_hilo(img, vaddr_to_id):
    """lui %hi + later %lo op on the same register that names a string."""
    hits = []
    data = img.data
    # register index -> (hi_immediate, lui_file_offset)
    lui_state = {}
    n = len(data) - (len(data) % 4)
    for off in range(0, n, 4):
        instr = struct.unpack_from("<I", data, off)[0]
        op = instr >> 26
        rs = (instr >> 21) & 31
        rt = (instr >> 16) & 31
        imm = instr & 0xFFFF

        if op == OP_LUI:
            if rt != 0:
                lui_state[rt] = (imm, off)
            continue

        # Does this instruction consume a lui-loaded register to reach RAM?
        consumed = None
        if op in ADDR_I_OPS or op in LOAD_OPS or op in STORE_OPS:
            st = lui_state.get(rs)
            if st is not None:
                hi, lui_off = st
                if op == OP_ORI:
                    addr = ((hi << 16) | imm) & 0xFFFFFFFF
                else:
                    addr = ((hi << 16) + sign16(imm)) & 0xFFFFFFFF
                sid = vaddr_to_id.get(addr)
                if sid is not None:
                    hits.append({
                        "lui_offset": lui_off,
                        "lo_offset": off,
                        "vaddr": addr,
                        "id": sid,
                        "lo_op": _mnemonic(op),
                    })
                consumed = rs

        # Invalidate clobbered lui state (conservative clobber tracking).
        if op == 0:                       # R-type: writes rd
            rd = (instr >> 11) & 31
            lui_state.pop(rd, None)
        elif op in ADDR_I_OPS or op in LOAD_OPS:   # I-type: writes rt
            lui_state.pop(rt, None)
        if consumed is not None and consumed != rs:
            lui_state.pop(consumed, None)
    return hits


_MNEMONICS = {
    OP_ADDIU: "addiu", OP_ADDI: "addi", OP_ORI: "ori",
    0x20: "lb", 0x21: "lh", 0x22: "lwl", 0x23: "lw",
    0x24: "lbu", 0x25: "lhu", 0x26: "lwr",
    0x28: "sb", 0x29: "sh", 0x2A: "swl", 0x2B: "sw", 0x2E: "swr",
}


def _mnemonic(op):
    return _MNEMONICS.get(op, f"op{op:#04x}")


def main():
    out_path = Path(sys.argv[sys.argv.index("--out") + 1]) \
        if "--out" in sys.argv else DEFAULT_OUT

    strings_by_file = load_strings()

    # Build per-file images and vaddr lookups first (overlays share a base, so
    # each file gets its OWN lookup -- cross-file matches stay ambiguous).
    images, lookups = {}, {}
    all_overlay_vaddrs = set()
    for rel, rows in strings_by_file.items():
        img = open_image(rel)
        if img is None:
            continue
        images[rel] = img
        look = {}
        for row in rows:
            v = img.off_to_vaddr(row["offset"])
            look[v] = row["id"]
            row["vaddr"] = v
            if img.base == OVERLAY_BASE:
                all_overlay_vaddrs.add(v)
        lookups[rel] = look

    strings = {}                 # id -> record (only referenced strings)
    referenced = set()
    total_word = total_hilo = total_ambiguous = 0

    for rel in sorted(images):
        img, look = images[rel], lookups[rel]
        others = all_overlay_vaddrs - set(look) if img.base == OVERLAY_BASE \
            else set()
        words, ambiguous = scan_words(img, look, others)
        hilos = scan_hilo(img, look)
        total_ambiguous += ambiguous

        for off, val, sid in words:
            total_word += 1
            referenced.add(sid)
            rec = strings.setdefault(sid, _new_rec(rel, val))
            rec["pointers"].append(
                {"kind": "word", "file": rel, "offset": f"{off:#x}"})
        for h in hilos:
            total_hilo += 1
            referenced.add(h["id"])
            rec = strings.setdefault(h["id"], _new_rec(rel, h["vaddr"]))
            rec["pointers"].append({
                "kind": "hilo", "file": rel,
                "lui_offset": f"{h['lui_offset']:#x}",
                "lo_offset": f"{h['lo_offset']:#x}",
                "lo_op": h["lo_op"],
            })

    # Strings in executables that we could NOT find a pointer for: honest
    # accounting -- the injector must keep these in place (byte-budgeted).
    unreferenced = []
    scannable = 0
    for rel in sorted(images):
        for row in strings_by_file[rel]:
            scannable += 1
            if row["id"] not in referenced:
                unreferenced.append(row["id"])

    manifest = {
        "generated_by": "tools/translation/map_text_pointers.py",
        "load_map": {
            rel: {"base": f"{img.base:#010x}",
                  "body_offset": f"{img.body_offset:#x}",
                  "kind": "exe" if img.base != OVERLAY_BASE else "overlay"}
            for rel, img in sorted(images.items())
        },
        "summary": {
            "scannable_strings": scannable,
            "referenced_strings": len(referenced),
            "relocatable_pct": round(100 * len(referenced) / scannable, 2)
            if scannable else 0.0,
            "unreferenced_strings": len(unreferenced),
            "pointer_sites_word": total_word,
            "pointer_sites_hilo": total_hilo,
            "ambiguous_overlay_words": total_ambiguous,
        },
        "strings": {k: strings[k] for k in sorted(strings)},
        "unreferenced": sorted(unreferenced),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))

    s = manifest["summary"]
    print(f"images scanned      : {len(images)}")
    print(f"scannable strings   : {s['scannable_strings']}")
    print(f"referenced strings  : {s['referenced_strings']} "
          f"({s['relocatable_pct']}% relocatable)")
    print(f"  via word pointers : {s['pointer_sites_word']}")
    print(f"  via hilo pairs    : {s['pointer_sites_hilo']}")
    print(f"unreferenced (kept) : {s['unreferenced_strings']}")
    print(f"ambiguous overlay   : {s['ambiguous_overlay_words']} "
          f"(cross-overlay coincidences, not asserted)")
    print(f"manifest -> {out_path.relative_to(ROOT)}")
    return 0


def _new_rec(rel, vaddr):
    return {"file": rel, "vaddr": f"{vaddr:#010x}", "pointers": []}


if __name__ == "__main__":
    sys.exit(main())
