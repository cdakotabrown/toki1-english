#!/usr/bin/env python3
"""Exact string extraction for the CDROM script containers (SERIFU, SPEAKTST,
BUNKA, ...): enumerate strings through the files' OWN pointer tables instead
of scanning for Shift-JIS runs.

Why this exists
---------------
`extract_text.py` scans every file for maximal Shift-JIS runs of >= 6 chars.
On the script containers that misses two things a translator must see:

  * strings shorter than 6 characters ("待った？", "そうだね。", "はい") --
    ~16,000 pointer-referenced strings across SERIFU/SPEAKTST/BUNKA;
  * the single-byte name/number tokens (P, G, p, m, F, Y, S, O, W, A, M) at
    the START of a string: the run scanner treats the token as non-Japanese,
    starts the row one byte late and drops the token from the text
    (a "G..." line was sheeted without its leading G, at offset+1).

The containers are DMA'd whole to a fixed RAM base (DATE_*.BIN -> 0x80198000,
TEST_AS -> 0x80180000, ...) and every string is referenced by an absolute
little-endian pointer word inside the same file.  The pointer table is
therefore the authoritative string list: exact starts, exact count, and the
sites the injector must rewrite if a string is ever moved.

Layout facts (measured, DATE_AS.BIN):
  * strings are NUL-terminated Shift-JIS, 4-byte aligned, zero padded;
  * each string is referenced by exactly ONE pointer word (no sharing);
  * text uses single-byte control bytes:  ' ' line break, 'q' choice
    separator, and the name/number tokens listed above (see
    translation/localization/CONTROL-CODES.md);
  * everything else in the file is script records (pointer words into the
    node graph plus 48-byte records that are mostly zero).  The zero runs are
    record fields, NOT free space.

Output
------
  translation/localization/sheets/<DIR>/<FILE>.csv   one sheet per container
  translation/localization/containers.json           per-file base / sites

Sheet columns: ID, File, Offset, MaxBytes, PtrSite, Kind, Speaker, Tokens,
English, Status, Notes.  The sheet deliberately carries NO Japanese text (project
decision D4): `File` + `Offset` locate the string on the player's disc, where the
reviewer and every checker read it with the `decode()` below.  `Tokens` lists the
control tokens present (so a QA check can insist they survive) and `MaxBytes` is
the in-place budget (bytes up to the next 4-byte-aligned object, minus the NUL).

Usage:
    python3 tools/translation/extract_containers.py            # all dirs
    python3 tools/translation/extract_containers.py SERIFU     # one dir
    python3 tools/translation/extract_containers.py --file assets/extracted_iso/CDROM/SERIFU/DATE_AS.BIN
"""
from __future__ import annotations

import csv
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT as REPO, SHEETS, CONTAINERS  # noqa: E402  (this checkout, either layout)
sys.path.insert(0, str(REPO / "tools"))
from repo_paths import DECOMP  # noqa: E402  (the extracted disc is toki1-decomp's)
# (None: the disc-free lint imports this module only for FIELDS and decode)
CDROM = DECOMP / "assets" / "extracted_iso" / "CDROM" if DECOMP is not None else None

DEFAULT_DIRS = ["SERIFU", "SPEAKTST", "BUNKA", "BUNKASD", "BATTLE", "TAIIKU"]

# single-byte control codes (from src/main/matched/msg_str_disp.c,
# serifu_cmd_exec.c and msg_part_reorder.c -- the three parsers of this text format)
TOKENS = {
    0x20: "{br}",    # ' '  line break inside a message
    0x71: "{opt}",   # 'q'  choice separator / message break
    0x50: "{P}",     # girl's family name (+ honorific), D_800D067C
    0x47: "{G}",     # girl's given name, D_800D0690
    0x70: "{p}",     # player's family name, D_800D066C
    0x6D: "{m}",     # player's given name, D_800D0674
    0x46: "{F}",     # player's full name "%s%s"
    0x59: "{Y}",     # the friend's name (Yoshio), D_800B8A00
    0x53: "{S}",     # runtime string D_800D073C
    0x4F: "{O}",     # runtime string D_800D0748
    0x57: "{W}",     # runtime string D_800D0750
    0x41: "{A}",     # runtime string D_800D075C
    0x4D: "{M}",     # runtime string D_800D0780
}
TOKEN_RE = re.compile(r"\{(br|opt|P|G|p|m|F|Y|S|O|W|A|M)\}")

JP_RE = re.compile(r"[぀-ヿ一-鿿！-～　-〿‘-”…ー]")

# speaker hint from the file name.  DATE_XX / EVENT_XX / TEST_XX are one
# heroine's own lines (the {opt} strings inside them are the player's).
GIRLS = {
    "FU": "Shiori Fujisaki", "NI": "Saki Nijino", "KI": "Mio Kisaragi",
    "HI": "Yuina Himoo", "KA": "Ayako Katagiri", "KY": "Nozomi Kiyokawa",
    "KG": "Mira Kagami", "AS": "Yuko Asahina", "KO": "Yukari Koshiki",
    "MI": "Megumi Mikihara", "SA": "Yumi Saotome", "OT": "other (Rei/Miharu/NPC)",
}


def speaker_for(stem: str) -> str:
    m = re.match(r"(?:DATE|EVENT|TEST|GASSH)_?([A-Z]{2})", stem)
    if m and m.group(1) in GIRLS:
        return GIRLS[m.group(1)]
    m = re.match(r"([A-Z]{2})_S\d", stem)          # BUNKA/AS_S6 etc.
    if m and m.group(1) in GIRLS:
        return GIRLS[m.group(1)]
    return ""


def find_base(data: bytes) -> int | None:
    """Load base: the file is DMA'd whole to one RAM address (the loader call
    `cd_read_start2(sectors, ram, lba)` names it; 1 KB-aligned, e.g. GASSH_FU ->
    0x801B4400) and its pointer words fall inside [base, base+len).  Score every
    1 KB-aligned candidate around the pointer range by how many pointer words
    land exactly on a string start (4-aligned, preceded by NUL or offset 0,
    Shift-JIS decodable) and keep the best."""
    n = len(data)
    words = [struct.unpack_from("<I", data, o)[0] for o in range(0, n - 3, 4)]
    cands = [w for w in words if 0x80100000 <= w < 0x80200000 and (w & 3) == 0]
    if len(cands) < 4:
        return None
    lo = min(cands) & ~0x3FF
    best, best_n = None, 0
    for base in range(max(lo - n, 0x80100000), lo + 0x400, 0x400):
        hits = 0
        for w in cands:
            t = w - base
            if 0 <= t < n and data[t] and (t == 0 or data[t - 1] == 0):
                e = data.find(b"\0", t)
                if e > t:
                    try:
                        data[t:e].decode("shift_jis")
                        hits += 1
                    except UnicodeDecodeError:
                        pass
        if hits > best_n:
            best, best_n = base, hits
    return best if best_n >= 4 else None


def decode(raw: bytes) -> str | None:
    """Shift-JIS with control bytes turned into {tokens}; None if not text."""
    out = []
    i = 0
    while i < len(raw):
        b = raw[i]
        if b in TOKENS:
            out.append(TOKENS[b]); i += 1; continue
        if b < 0x80:
            if 0x21 <= b < 0x7F:      # bare ASCII never appears in retail text
                return None
            return None
        if i + 1 >= len(raw):
            return None
        try:
            out.append(raw[i:i + 2].decode("shift_jis"))
        except UnicodeDecodeError:
            return None
        i += 2
    return "".join(out)


def encode(text: str) -> bytes:
    """Inverse of decode(): {tokens} -> control bytes, text -> Shift-JIS."""
    rev = {v: k for k, v in TOKENS.items()}
    out = bytearray()
    pos = 0
    for m in TOKEN_RE.finditer(text):
        out += text[pos:m.start()].encode("shift_jis")
        out.append(rev[m.group(0)])
        pos = m.end()
    out += text[pos:].encode("shift_jis")
    return bytes(out)


def extract_file(path: Path):
    data = path.read_bytes()
    n = len(data)
    base = find_base(data)
    if base is None:
        return None
    sites = defaultdict(list)
    for o in range(0, n - 3, 4):
        w = struct.unpack_from("<I", data, o)[0]
        if base <= w < base + n:
            sites[w - base].append(o)
    starts = sorted(sites)
    rows = []
    stem = path.stem
    rel = path.relative_to(DECOMP).as_posix()
    speaker = speaker_for(stem)
    for idx, s in enumerate(starts):
        e = data.find(b"\0", s)
        if e < 0 or e == s:
            continue
        raw = data[s:e]
        text = decode(raw)
        if text is None:
            continue
        letters = sum(1 for ch in text if JP_RE.match(ch))
        plain = TOKEN_RE.sub("", text)
        if plain and letters * 2 < len(plain):
            continue
        # in-place budget: up to the next referenced object or next non-zero
        # byte after the padding, whichever is first
        nxt = starts[idx + 1] if idx + 1 < len(starts) else n
        limit = e + 1
        while limit < nxt and data[limit] == 0:
            limit += 1
        limit = min(limit, nxt)
        maxbytes = limit - s - 1
        kind = "choice" if "{opt}" in text else "line"
        toks = " ".join(sorted(set(TOKEN_RE.findall(text))))
        rows.append({
            "ID": f"{rel}:0x{s:x}",
            "File": rel,
            "Offset": f"0x{s:x}",
            "MaxBytes": maxbytes,
            "PtrSite": " ".join(f"0x{o:x}" for o in sites[s]),
            "Kind": kind,
            "Speaker": "player (choice)" if kind == "choice" else speaker,
            "Tokens": toks,
            "English": "",
            "Status": "untranslated",
            "Notes": "",
        })
    return {"base": base, "size": n, "rows": rows}


FIELDS = ["ID", "File", "Offset", "MaxBytes", "PtrSite", "Kind", "Speaker",
          "Tokens", "English", "Status", "Notes"]


def main(argv):
    only_file = None
    dirs = DEFAULT_DIRS
    if "--file" in argv:
        only_file = Path(argv[argv.index("--file") + 1])
    elif len(argv) > 1:
        dirs = [a for a in argv[1:] if not a.startswith("-")]
    files = [only_file] if only_file else [
        p for d in dirs for p in sorted((CDROM / d).glob("*.BIN"))]
    index = {}
    total = 0
    for p in files:
        r = extract_file(p)
        if r is None or not r["rows"]:
            continue
        sub = p.parent.name
        outdir = SHEETS / sub
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (p.stem + ".csv")
        if out.exists():   # keep translator work keyed by ID across re-extraction
            with open(out, encoding="utf-8") as fh:
                keep = {x["ID"]: x for x in csv.DictReader(fh)}
            for row in r["rows"]:
                k = keep.get(row["ID"])
                if k and k.get("English", "").strip():
                    row["English"], row["Status"], row["Notes"] = k["English"], k["Status"], k["Notes"]
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(r["rows"])
        index[p.relative_to(DECOMP).as_posix()] = {
            "base": f"0x{r['base']:x}", "size": r["size"],
            "strings": len(r["rows"]), "sheet": out.relative_to(REPO).as_posix(),
        }
        total += len(r["rows"])
        print(f"{sub}/{p.name}: {len(r['rows'])} strings, base 0x{r['base']:x}")
    CONTAINERS.parent.mkdir(parents=True, exist_ok=True)
    idx_path = CONTAINERS
    old = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    old.update(index)
    idx_path.write_text(json.dumps(old, indent=1, sort_keys=True) + "\n")
    print(f"TOTAL {total} strings in {len(index)} containers -> {SHEETS}")


if __name__ == "__main__":
    main(sys.argv)
