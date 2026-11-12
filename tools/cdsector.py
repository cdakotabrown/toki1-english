#!/usr/bin/env python3
"""cdsector.py - an independent CD-ROM XA sector checker (ECMA-130 / CD-XA).

Written from the standard, not from mkpsxiso, so that it can audit the
sectors mkpsxiso regenerates for the English patch:

  * sync pattern 00 FF*10 00, header MSF = LBA + 150 (BCD), mode byte 2;
  * the XA subheader stored twice (bytes 16..19 == 20..23);
  * Form 1 (submode bit 5 clear): EDC (CRC-32, polynomial 0x8001801B,
    reflected, init 0) over bytes 16..2071 stored LE at 2072, and the
    Reed-Solomon P (86 x 24) and Q (52 x 43) parity over bytes 12..2075 /
    12..2247 computed with the header bytes 12..15 zeroed (mode 2);
  * Form 2: EDC over bytes 16..2347 at 2348 (0 = "not computed", allowed).

Vectorised with numpy over many sectors at once (a whole 700 MB track in
about a minute).  `check_sectors(raw, first_lba)` returns one status code
per sector (0 = valid); `describe(code)` names the failures.
"""
import numpy as np

SEC = 2352
SYNC = bytes([0] + [0xFF] * 10 + [0])

OK = 0
BAD_SYNC = 1
BAD_MSF = 2
BAD_MODE = 4
BAD_SUBHDR = 8
BAD_EDC = 16
BAD_ECC_P = 32
BAD_ECC_Q = 64
FORM2 = 128            # informational: the sector is Form 2
NAMES = {BAD_SYNC: "sync", BAD_MSF: "msf", BAD_MODE: "mode",
         BAD_SUBHDR: "subheader copy", BAD_EDC: "edc", BAD_ECC_P: "ecc-p",
         BAD_ECC_Q: "ecc-q"}


def describe(code: int) -> str:
    bad = [n for b, n in NAMES.items() if code & b]
    return ("form2 " if code & FORM2 else "form1 ") + (",".join(bad) or "ok")


def _tables():
    edc = np.zeros(256, dtype=np.uint32)
    for i in range(256):
        e = i
        for _ in range(8):
            e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
        edc[i] = e
    f = np.zeros(256, dtype=np.uint8)
    b = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        j = (i << 1) ^ (0x11D if i & 0x80 else 0)
        f[i] = j & 0xFF
        b[i ^ (j & 0xFF)] = i
    return edc, f, b


EDC_LUT, ECC_F, ECC_B = _tables()


def edc(block: np.ndarray) -> np.ndarray:
    """CRC over the columns of block (n_sectors x length) -> uint32[n]."""
    crc = np.zeros(block.shape[0], dtype=np.uint32)
    for k in range(block.shape[1]):
        crc = (crc >> np.uint32(8)) ^ EDC_LUT[(crc ^ block[:, k]) & 0xFF]
    return crc


def _ecc_block(src: np.ndarray, major_count, minor_count, major_mult, minor_inc):
    """ECMA-130 Annex A parity for each sector row of src -> (n, 2*major)."""
    size = major_count * minor_count
    n = src.shape[0]
    out = np.zeros((n, 2 * major_count), dtype=np.uint8)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = np.zeros(n, dtype=np.uint8)
        b = np.zeros(n, dtype=np.uint8)
        for _ in range(minor_count):
            t = src[:, index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        out[:, major] = a
        out[:, major + major_count] = a ^ b
    return out


def bcd(v):
    return ((v // 10) << 4) | (v % 10)


def check_sectors(raw: bytes, first_lba) -> np.ndarray:
    """raw = n * 2352 bytes of sectors: consecutive from first_lba (an int)
    or at the LBAs of the sequence first_lba."""
    a = np.frombuffer(raw, dtype=np.uint8).reshape(-1, SEC)
    n = a.shape[0]
    code = np.zeros(n, dtype=np.uint16)
    sync = np.frombuffer(SYNC, dtype=np.uint8)
    code[(a[:, :12] != sync).any(axis=1)] |= BAD_SYNC
    if np.isscalar(first_lba):
        lba = np.arange(first_lba, first_lba + n) + 150
    else:
        lba = np.asarray(first_lba, dtype=np.int64) + 150
    mm, ss, ff = lba // (75 * 60), (lba // 75) % 60, lba % 75
    msf = np.stack([bcd(mm), bcd(ss), bcd(ff)], axis=1).astype(np.uint8)
    code[(a[:, 12:15] != msf).any(axis=1)] |= BAD_MSF
    code[a[:, 15] != 2] |= BAD_MODE
    code[(a[:, 16:20] != a[:, 20:24]).any(axis=1)] |= BAD_SUBHDR
    form2 = (a[:, 18] & 0x20) != 0
    code[form2] |= FORM2
    f1 = np.where(~form2)[0]
    if len(f1):
        s = a[f1]
        stored = s[:, 2072:2076].copy().view("<u4").ravel()
        bad = edc(s[:, 16:2072]) != stored
        code[f1[bad]] |= BAD_EDC
        z = s.copy()
        z[:, 12:16] = 0
        p = _ecc_block(z[:, 12:12 + 2064], 86, 24, 2, 86)
        code[f1[(p != s[:, 2076:2248]).any(axis=1)]] |= BAD_ECC_P
        z[:, 2076:2248] = p
        q = _ecc_block(z[:, 12:12 + 2236], 52, 43, 86, 88)
        code[f1[(q != s[:, 2248:2352]).any(axis=1)]] |= BAD_ECC_Q
    f2 = np.where(form2)[0]
    if len(f2):
        s = a[f2]
        stored = s[:, 2348:2352].copy().view("<u4").ravel()
        nz = stored != 0
        if nz.any():
            bad = np.zeros(len(f2), dtype=bool)
            bad[nz] = edc(s[nz][:, 16:2348]) != stored[nz]
            code[f2[bad]] |= BAD_EDC
    return code


def check_file(path, lbas=None, batch=4096, n_sectors=None):
    """Status codes for the sectors `lbas` (sorted list) of an image file,
    or for every sector when lbas is None."""
    import os
    n_total = os.path.getsize(path) // SEC
    if n_sectors is not None:
        n_total = min(n_total, n_sectors)
    out = {}
    with open(path, "rb") as f:
        if lbas is None:
            for start in range(0, n_total, batch):
                cnt = min(batch, n_total - start)
                f.seek(start * SEC)
                codes = check_sectors(f.read(cnt * SEC), start)
                for i, c in enumerate(codes):
                    out[start + i] = int(c)
            return out
        lbas = sorted(lbas)
        for i in range(0, len(lbas), batch):
            group = lbas[i:i + batch]
            raw = bytearray()
            for lba in group:
                f.seek(lba * SEC)
                raw += f.read(SEC)
            codes = check_sectors(bytes(raw), group)
            for lba, c in zip(group, codes):
                out[lba] = int(c)
    return out
