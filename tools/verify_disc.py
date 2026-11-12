#!/usr/bin/env python3
"""verify_disc.py - integrity audit of a patched Track 1 image against the dump.

    python3 tools/patch/verify_disc.py [build/patch/iso/patched_disc.bin]
        [--original "disks/...(Track 1).bin"] [--report build/patch/english.report.json]
        [--json OUT.json] [--self-test]

Independent of the builder (its own ISO9660 walker and its own EDC/ECC,
tools/patch/cdsector.py).  FAILS (exit 1) unless all of these hold:

  1. Same track size; the volume descriptors, both path tables and every
     directory extent are byte-identical to the dump; every file keeps its
     name, LBA, size, flags and date (the game addresses files by hardcoded
     (sectors, LBA) pairs, so nothing may move).
  2. Every sector of the image has a valid sync / BCD MSF / mode 2 header,
     a consistent XA subheader and a correct EDC + ECC P/Q (Form 1) or EDC
     (Form 2) -- or exactly the same defect the dump itself carries (the
     dump has two: a Form-2 subheader quirk and the junk post-gap ECC of the
     last sector).  Every changed sector's subheader equals the dump's.
  3. Every changed sector lies inside a file, and the set of changed files
     is the set the build report says it modified (when --report is given).
  4. Per changed file, the loader contracts (read from the C):
     * PSX.EXE: the 2 KB PS-X EXE header is unchanged (t_addr, t_size, pc0,
       gp, sp: the BIOS loads exactly t_size bytes to t_addr).
     * every 2048-aligned position where the dump's file has the 0x1012
       footer (the u32 at dest + sectors*2048 - 4 that cdq_command_process
       requires after a cd_read_start2 read) still has it;
     * every block byte-sum trailer that is valid in the dump (the
       big-endian u16 sum of the read's first blocks*2048-4 bytes,
       block_checksum_check: the EXN loader ending_load_gate, OMIKUJI via
       shougatu_data_check, week_day_load, the bustup loaders) is valid in
       the image, for reads starting at the file start or at an earlier
       footer boundary;
     * *.EXN: the trailer is 0x1012 + the byte-swapped 16-bit sum
       (translation/docs/EXN-CHECKSUM.md).
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
import cdsector                                         # noqa: E402

SEC = 2352
TRACK1 = DECOMP / "disks" / ("Tokimeki Memorial - Forever with You (Japan) "
                           "(Rev 1) (Track 1).bin")
TRACK2 = TRACK1.with_name(TRACK1.name.replace("(Track 1)", "(Track 2)"))
FOOTER = b"\x12\x10"


class Image:
    """Minimal ISO9660 reader over a raw MODE2/2352 track."""

    def __init__(self, path: Path):
        self.path = path
        self.f = open(path, "rb")
        self.n = path.stat().st_size // SEC
        self.entries = {}           # path -> dict(lba, size, flags, rec)
        self.dirs = {}              # path -> (lba, size)
        pvd = self.user(16)
        if pvd[1:6] != b"CD001":
            raise SystemExit(f"{path}: no ISO9660 PVD at sector 16")
        self.pvd = pvd
        self.vol_blocks = struct.unpack_from("<I", pvd, 80)[0]
        self.pt_size = struct.unpack_from("<I", pvd, 132)[0]
        self.pt_l, self.pt_l2, = struct.unpack_from("<II", pvd, 140)
        self.pt_m, self.pt_m2 = struct.unpack_from(">II", pvd, 148)
        root = pvd[156:156 + 34]
        self._walk(struct.unpack_from("<I", root, 2)[0],
                   struct.unpack_from("<I", root, 10)[0], "")

    def raw(self, lba: int) -> bytes:
        self.f.seek(lba * SEC)
        return self.f.read(SEC)

    def user(self, lba: int) -> bytes:
        return self.raw(lba)[24:24 + 2048]

    def _walk(self, lba, size, path):
        self.dirs[path or "/"] = (lba, size)
        for s in range((size + 2047) // 2048):
            d = self.user(lba + s)
            off = 0
            while off < 2048:
                ln = d[off]
                if ln == 0:
                    break
                rec = d[off:off + ln]
                elba = struct.unpack_from("<I", rec, 2)[0]
                esz = struct.unpack_from("<I", rec, 10)[0]
                flags = rec[25]
                nl = rec[32]
                name = rec[33:33 + nl]
                off += ln
                if name in (b"\x00", b"\x01"):
                    continue
                nm = name.decode("ascii", "replace").split(";")[0]
                p = f"{path}/{nm}" if path else nm
                self.entries[p] = {"lba": elba, "size": esz, "flags": flags,
                                   "rec": rec}
                if flags & 2:
                    self._walk(elba, esz, p)

    def read_file(self, p: str, form2=False) -> bytes:
        e = self.entries[p]
        out = bytearray()
        for s in range((e["size"] + 2047) // 2048):
            out += self.user(e["lba"] + s)
        return bytes(out[:e["size"]])

    def file_at(self, lba: int):
        for p, e in self.entries.items():
            if e["flags"] & 2:
                continue
            n = (e["size"] + 2047) // 2048
            if e["lba"] <= lba < e["lba"] + n:
                return p
        return None


def block_sum_ok(d: bytes, start: int, end: int) -> bool:
    """block_checksum_check over d[start:end]: u16 byte sum of the first
    (end-start-4) bytes == big-endian u16 at end-4."""
    return (sum(d[start:end - 4]) & 0xFFFF) == (d[end - 4] << 8 | d[end - 3])


def loader_contracts(orig: bytes, new: bytes, name: str):
    """Return the list of violated loader contracts for one changed file."""
    bad = []
    if len(orig) != len(new):
        bad.append(f"size {len(new)} != dump {len(orig)}")
        return bad
    if name == "PSX.EXE":
        if orig[:0x800] != new[:0x800]:
            bad.append("PS-X EXE header changed")
        return bad
    footers = [e for e in range(2048, len(orig) + 1, 2048)
               if orig[e - 2:e] == FOOTER]
    starts = [0]
    for e in footers:
        if new[e - 2:e] != FOOTER:
            bad.append(f"0x1012 footer lost at +0x{e - 4:x}")
        for s in starts:
            if block_sum_ok(orig, s, e) and not block_sum_ok(new, s, e):
                bad.append(f"block checksum stale over +0x{s:x}..+0x{e:x} "
                           f"(stored {new[e - 4]:02x}{new[e - 3]:02x}, sum "
                           f"{sum(new[s:e - 4]) & 0xFFFF:04x})")
        starts.append(e)
    if name.endswith(".EXN"):
        s16 = sum(new[:-4]) & 0xFFFF
        want = 0x10120000 | ((s16 >> 8) & 0xFF) | ((s16 & 0xFF) << 8)
        if struct.unpack_from("<I", new, len(new) - 4)[0] != want:
            bad.append("EXN trailer (0x1012 + swapped sum) wrong")
    return bad


def restamp_block_sums(orig: bytes, data: bytearray) -> list:
    """Re-stamp, in data, every block checksum that is valid in the dump's
    copy (same rule as loader_contracts); returns the positions written."""
    done = []
    footers = [e for e in range(2048, len(orig) + 1, 2048)
               if orig[e - 2:e] == FOOTER]
    starts = [0]
    for e in footers:
        for s in starts:
            if block_sum_ok(orig, s, e) and not block_sum_ok(data, s, e):
                v = sum(data[s:e - 4]) & 0xFFFF
                data[e - 4] = v >> 8
                data[e - 3] = v & 0xFF
                done.append((s, e))
        starts.append(e)
    return done


def expected_files(report: dict) -> set:
    exp = {"PSX.EXE"}
    for ov in report.get("overlays", {}):
        exp.add(f"CDROM/EXEDIR/{ov}.EXN")
    exp.update(report.get("files", {}).keys())
    exp.update(report.get("containers", {}).get("files", []))
    return exp


def verify(built: Path, original: Path, report: dict = None, out_json=None):
    fails = []
    a = Image(original)
    b = Image(built)
    if b.n < a.n:
        fails.append(f"image has {b.n} sectors, Track 1 of the dump {a.n}")
    elif b.n > a.n:
        # mkpsxiso writes both tracks into one .bin: the tail must be the
        # dump's Track 2 (audio, with its 2-second pregap) byte for byte
        t2 = TRACK2
        tail = (b.n - a.n) * SEC
        if not t2.exists() or t2.stat().st_size != tail:
            fails.append(f"image carries {b.n - a.n} sectors after Track 1 that "
                         f"are not the size of {t2.name}")
        else:
            with open(built, "rb") as fb, open(t2, "rb") as f2:
                fb.seek(a.n * SEC)
                while True:
                    x = fb.read(1 << 22)
                    y = f2.read(1 << 22)
                    if x != y:
                        fails.append("the audio track in the image differs "
                                     "from the dump's Track 2")
                        break
                    if not x:
                        break
    # 1. metadata
    meta = list(range(16, 16 + 8))
    for p_lba in (a.pt_l, a.pt_l2, a.pt_m, a.pt_m2):
        if p_lba:
            meta += list(range(p_lba, p_lba + (a.pt_size + 2047) // 2048))
    for _, (lba, size) in a.dirs.items():
        meta += list(range(lba, lba + (size + 2047) // 2048))
    meta_bad = [s for s in sorted(set(meta)) if a.user(s) != b.user(s)]
    if meta_bad:
        fails.append(f"ISO9660 metadata sectors differ: {meta_bad[:10]}")
    if set(a.entries) != set(b.entries):
        fails.append(f"file sets differ: {sorted(set(a.entries) ^ set(b.entries))[:10]}")
    for p, e in a.entries.items():
        f = b.entries.get(p)
        if f and f["rec"] != e["rec"]:
            fails.append(f"{p}: directory record changed (lba {f['lba']} size "
                         f"{f['size']} vs {e['lba']} {e['size']})")
    # 2. sectors
    sa = cdsector.check_file(original)
    sb = cdsector.check_file(built, n_sectors=a.n)
    changed = []
    with open(original, "rb") as fa, open(built, "rb") as fb:
        for s in range(min(a.n, b.n)):
            x = fa.read(SEC)
            y = fb.read(SEC)
            if x != y:
                changed.append(s)
                if x[16:24] != y[16:24]:
                    fails.append(f"sector {s}: subheader changed "
                                 f"{x[16:24].hex()} -> {y[16:24].hex()}")
    sector_bad = []
    for s in range(min(a.n, b.n)):
        cb = sb.get(s, 0) & 0x7F
        ca = sa.get(s, 0) & 0x7F
        if cb and cb != ca:
            sector_bad.append((s, cdsector.describe(sb[s])))
    if sector_bad:
        fails.append(f"{len(sector_bad)} sectors with bad header/EDC/ECC: "
                     f"{sector_bad[:8]}")
    # 3. changed sectors -> files
    files = {}
    stray = []
    for s in changed:
        p = b.file_at(s)
        if p is None:
            stray.append(s)
        else:
            files.setdefault(p, []).append(s)
    if stray:
        fails.append(f"changed sectors outside every file: {stray[:10]}")
    if report is not None:
        exp = expected_files(report)
        extra = sorted(set(files) - exp)
        if extra:
            fails.append(f"files changed that the build did not declare: {extra[:10]}")
    # 4. loader contracts
    per_file = {}
    for p in sorted(files):
        bad = loader_contracts(a.read_file(p), b.read_file(p), p.split("/")[-1])
        per_file[p] = {"sectors": len(files[p]), "problems": bad}
        for x in bad:
            fails.append(f"{p}: {x}")
    summary = {"built": str(built), "original": str(original),
               "sectors": b.n, "changed_sectors": len(changed),
               "changed_files": len(files), "metadata_sectors_checked": len(set(meta)),
               "dump_sector_defects": {str(s): cdsector.describe(c)
                                       for s, c in sa.items() if c & 0x7F},
               "files": per_file, "failures": fails}
    if out_json:
        Path(out_json).write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def self_test():
    """Negative controls: the sector checker and the contract checker must
    catch a corrupted EDC, a bad ECC byte, a moved footer and a stale sum."""
    import numpy as np
    a = Image(TRACK1)
    raw = bytearray(a.raw(24))
    assert cdsector.check_sectors(bytes(raw), 24)[0] & 0x7F == 0
    for pos, flag in ((100, cdsector.BAD_EDC), (2080, cdsector.BAD_ECC_P),
                      (2300, cdsector.BAD_ECC_Q), (14, cdsector.BAD_MSF)):
        r = bytearray(raw)
        r[pos] ^= 0x40
        c = int(cdsector.check_sectors(bytes(r), 24)[0])
        assert c & flag, (pos, cdsector.describe(c))
    d = a.read_file("CDROM/SERIFU/SERIFU.BIN")
    assert not loader_contracts(d, d, "SERIFU.BIN")
    e = bytearray(d)
    e[100] ^= 1
    assert any("stale" in x for x in loader_contracts(d, bytes(e), "SERIFU.BIN"))
    assert restamp_block_sums(d, e) and not loader_contracts(d, bytes(e), "SERIFU.BIN")
    e[-2] = 0
    assert any("footer" in x for x in loader_contracts(d, bytes(e), "SERIFU.BIN"))
    print("[verify_disc] self-test OK (EDC, ECC P/Q, MSF, footer, stale sum caught)")
    del np


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("built", type=Path, nargs="?",
                    default=ROOT / "build" / "patch" / "iso" / "patched_disc.bin")
    ap.add_argument("--original", type=Path, default=TRACK1)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    rep = json.loads(args.report.read_text()) if args.report else None
    s = verify(args.built, args.original, rep, args.json)
    print(f"[verify_disc] {s['changed_sectors']} changed sectors in "
          f"{s['changed_files']} files; {s['metadata_sectors_checked']} metadata "
          f"sectors checked; dump defects kept: {s['dump_sector_defects']}")
    for f in s["failures"][:40]:
        print(f"[verify_disc] FAIL: {f}")
    if len(s["failures"]) > 40:
        print(f"[verify_disc] ... {len(s['failures']) - 40} more")
    if s["failures"]:
        sys.exit(1)
    print("[verify_disc] OK")


if __name__ == "__main__":
    main()
