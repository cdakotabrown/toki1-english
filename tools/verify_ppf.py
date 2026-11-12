#!/usr/bin/env python3
"""verify_ppf.py - check a PPF patch against the PPF 3.0 spec and prove it.

    python3 tools/patch/verify_ppf.py build/patch/english.ppf \
        [--original "disks/...(Track 1).bin"] [--built build/patch/iso/patched_disc.bin]
        [--write OUT.bin]

The parser is written from the PPF3 layout that the third-party appliers
read (PPF-O-Matic / applyppf3 / the reference emulator's CDImagePPF), independently of
build_patched.py's writer:

    0x00  "PPF30"            magic
    0x05  u8   method        2 = PPF 3.0
    0x06  50 B description   (space padded)
    0x38  u8   image type    0 = BIN, 1 = GI
    0x39  u8   blockcheck    0/1: 1024 bytes of validation data at 0x3C
    0x3A  u8   undo          0/1: every record carries the original bytes
    0x3B  u8   dummy
    0x3C  records (or 0x43C with blockcheck):
          u64 LE offset, u8 length, length bytes [+ length undo bytes]
    [optional "@BEGIN_FILE_ID.DIZ" ... "@END_FILE_ID.DIZ" + length]

It then APPLIES the patch to a pristine Track 1 dump (streaming; the image is
never loaded whole) and requires the result to equal the built image byte
for byte (SHA1 of both).  With --write the patched image is also saved.
Exit status 0 = compliant and reproducing; 1 = any failure.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
TRACK1 = DECOMP / "disks" / ("Tokimeki Memorial - Forever with You (Japan) "
                           "(Rev 1) (Track 1).bin")
DIZ_BEGIN = b"@BEGIN_FILE_ID.DIZ"
DIZ_END = b"@END_FILE_ID.DIZ"
HEADER_SIZE = 60
BLOCKCHECK_SIZE = 1024


def parse_ppf3(data: bytes):
    """Return (header dict, [(offset, payload, undo)], problems)."""
    problems = []
    if len(data) < HEADER_SIZE:
        raise ValueError("file shorter than the 60-byte PPF3 header")
    if data[:5] != b"PPF30":
        raise ValueError(f"magic {data[:5]!r} is not PPF30")
    hdr = {"method": data[5],
           "description": data[6:56].decode("ascii", "replace").rstrip(),
           "image_type": data[56], "blockcheck": data[57], "undo": data[58],
           "dummy": data[59]}
    if hdr["method"] != 2:
        problems.append(f"encoding method {hdr['method']} (PPF3 = 2)")
    if hdr["image_type"] not in (0, 1):
        problems.append(f"image type {hdr['image_type']:#x} (0 = BIN, 1 = GI): "
                        f"the header is shifted")
    if hdr["blockcheck"] not in (0, 1) or hdr["undo"] not in (0, 1):
        problems.append(f"blockcheck/undo flags {hdr['blockcheck']}/{hdr['undo']} "
                        f"are not 0/1: the header is shifted")
    if any(c < 0x20 or c > 0x7E for c in data[6:56]):
        problems.append("description holds non-printable bytes (header shifted?)")
    pos = HEADER_SIZE + (BLOCKCHECK_SIZE if hdr["blockcheck"] == 1 else 0)
    end = len(data)
    k = data.rfind(DIZ_BEGIN)
    if k >= pos and data.find(DIZ_END, k) > 0:
        end = k
        hdr["file_id_diz"] = True
    recs = []
    undo = hdr["undo"] == 1
    while pos < end:
        if pos + 9 > end:
            problems.append(f"truncated record header at {pos:#x}")
            break
        off, n = struct.unpack_from("<QB", data, pos)
        pos += 9
        if n == 0:
            problems.append(f"zero-length record at {pos - 9:#x}")
        need = n * (2 if undo else 1)
        if pos + need > end:
            problems.append(f"truncated record payload at {pos:#x}")
            break
        recs.append((off, data[pos:pos + n],
                     data[pos + n:pos + 2 * n] if undo else None))
        pos += need
    return hdr, recs, problems


def apply_stream(orig: Path, recs, out_file=None, chunk=1 << 22):
    """Stream the original through the records; return (sha1, size, problems)."""
    problems = []
    size = orig.stat().st_size
    recs = sorted(recs, key=lambda r: r[0])
    last_end = 0
    for off, payload, _ in recs:
        if off < last_end:
            problems.append(f"overlapping records at {off:#x}")
        if off + len(payload) > size:
            problems.append(f"record at {off:#x} runs past the image end "
                            f"({size:#x})")
        last_end = max(last_end, off + len(payload))
    first = 0
    h = hashlib.sha1()
    with open(orig, "rb") as fo:
        pos = 0
        while pos < size:
            buf = bytearray(fo.read(min(chunk, size - pos)))
            n = len(buf)
            j = first
            while j < len(recs) and recs[j][0] < pos + n:
                off, payload, undo = recs[j]
                a = max(off, pos)
                b = min(off + len(payload), pos + n)
                if a < b:
                    if undo is not None and \
                            bytes(buf[a - pos:b - pos]) != undo[a - off:b - off]:
                        problems.append(f"undo data mismatch at {off:#x}")
                    buf[a - pos:b - pos] = payload[a - off:b - off]
                j += 1
            while first < len(recs) and \
                    recs[first][0] + len(recs[first][1]) <= pos + n:
                first += 1
            h.update(buf)
            if out_file:
                out_file.write(buf)
            pos += n
    return h.hexdigest(), size, problems


def sha1_file(p: Path, limit: int = None) -> str:
    h = hashlib.sha1()
    left = p.stat().st_size if limit is None else limit
    with open(p, "rb") as f:
        while left > 0:
            b = f.read(min(1 << 22, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def verify(ppf: Path, original: Path, built: Path = None, write: Path = None,
           quiet=False) -> bool:
    data = ppf.read_bytes()
    try:
        hdr, recs, problems = parse_ppf3(data)
    except ValueError as e:
        print(f"[verify_ppf] {ppf}: FAIL: {e}")
        return False
    out = open(write, "wb") if write else None
    try:
        sha, size, p2 = apply_stream(original, recs, out)
    finally:
        if out:
            out.close()
    problems += p2
    # mkpsxiso writes Track 2 (audio) after Track 1 in the same .bin; the
    # PPF patches Track 1, so compare the built image's first `size` bytes
    # (tools/patch/verify_disc.py checks that the rest is the dump's Track 2)
    want = sha1_file(built, size) if built else None
    if built and built.stat().st_size < size:
        problems.append(f"built image is {built.stat().st_size} bytes, shorter "
                        f"than the original Track 1 ({size})")
    if want and sha != want:
        problems.append(f"patched original sha1 {sha} != built image {want}")
    if not quiet:
        print(f"[verify_ppf] {ppf.name}: PPF3 method {hdr['method']}, image type "
              f"{hdr['image_type']}, blockcheck {hdr['blockcheck']}, undo "
              f"{hdr['undo']}, {len(recs)} records, "
              f"{sum(len(r[1]) for r in recs)} payload bytes")
        print(f"[verify_ppf] description: {hdr['description']!r}")
        print(f"[verify_ppf] original {original.name} + patch -> sha1 {sha}")
        if want:
            print(f"[verify_ppf] built image (Track 1 part) -> sha1 {want}")
    for p in problems[:20]:
        print(f"[verify_ppf] FAIL: {p}")
    if len(problems) > 20:
        print(f"[verify_ppf] ... {len(problems) - 20} more problems")
    if not problems and not quiet:
        print("[verify_ppf] OK: spec-compliant, and the patched dump equals "
              "the built image")
    return not problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ppf", type=Path)
    ap.add_argument("--original", type=Path, default=TRACK1)
    ap.add_argument("--built", type=Path,
                    help="default: <ppf dir>/iso/patched_disc.bin")
    ap.add_argument("--write", type=Path, help="also save the patched image")
    args = ap.parse_args()
    built = args.built or (args.ppf.parent / "iso" / "patched_disc.bin")
    sys.exit(0 if verify(args.ppf, args.original, built, args.write) else 1)


if __name__ == "__main__":
    main()
