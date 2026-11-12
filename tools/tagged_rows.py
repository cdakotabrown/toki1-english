#!/usr/bin/env python3
"""tagged_rows.py - the container strings the sheets do not cover.

Walks every container of translation/localization/containers.json, follows
every pointer word that lands inside the file, and reports the NUL-terminated
strings that are NOT sheet rows: almost all of them start with one of the
event dispatcher's speaker-tag letters ('>' 2-char, '-' 3-char, '+' 1-char,
'<' 2-char Shift-JIS speaker name, then the body) or end with the "nn" skip
marker, which the original extractor skipped.  Writes
build/patch/gen/tagged_rows.csv (same columns as the sheets, Japanese split
as "{tag:NAME}body", plus the row's config/patch/tagged_rows_en.json Key)
and prints the counts per directory.
"""
import csv
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, CONTAINERS  # noqa: E402  (this checkout, either layout)
from roots import locate                          # noqa: E402
TAGS = {ord(">"): 4, ord("-"): 6, ord("+"): 2, ord("<"): 4}
LETTERS = {" ": "{br}", "q": "{opt}", "P": "{P}", "G": "{G}", "p": "{p}", "m": "{m}",
           "F": "{F}", "Y": "{Y}", "S": "{S}", "O": "{O}", "W": "{W}", "A": "{A}", "M": "{M}"}


def is_lead(b):
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def retail_to_sheet(body: bytes) -> str:
    """retail body bytes -> sheet text: the single-byte command letters at
    lead positions become {tokens}; a trailing "nn" stays (skip marker)"""
    out = []
    i = 0
    while i < len(body):
        b = body[i]
        if is_lead(b) and i + 1 < len(body):
            out.append(body[i:i + 2].decode("shift_jis"))
            i += 2
            continue
        ch = chr(b)
        if (b < 0x20 and ch != "\t") or b >= 0x80 or (ch not in LETTERS and ch not in "n\t"):
            raise ValueError(f"byte {b:#x} is not retail text")
        out.append(LETTERS.get(ch, ch))
        i += 1
    return "".join(out)


def scan_container(rel: str, info: dict, sheet_offs):
    """the pointer-target strings of one container that are not sheet rows,
    as sheet-shaped dicts (ID, File, Offset, MaxBytes, PtrSite, Kind,
    Speaker, Tag, Japanese, English, Status)"""
    data = locate(rel).read_bytes()
    base = int(info["base"], 16)
    rows = []
    seen = set()
    sites = {}
    for site in range(0, len(data) - 3, 4):
        w = struct.unpack_from("<I", data, site)[0]
        off = w - base
        if not (0 <= off < len(data)) or off in sheet_offs:
            continue
        if off % 4:
            continue                    # strings are word-aligned
        sites.setdefault(off, []).append(site)
    for off in sorted(sites):
        e = data.find(b"\0", off)
        if e == -1 or e == off or e - off > 600:
            continue
        raw = data[off:e]
        pairs = sum(1 for i in range(0, len(raw) - 1) if is_lead(raw[i]))
        if pairs < 1:
            continue
        tag = raw[0] if raw[0] in TAGS else 0
        body = raw
        name = ""
        if tag:
            n = TAGS[tag]
            try:
                name = raw[1:1 + n].decode("shift_jis")
            except UnicodeDecodeError:
                continue
            body = raw[1 + n:]
        try:
            jp = retail_to_sheet(body)
        except (UnicodeDecodeError, ValueError):
            continue
        if not re.search(r"[぀-ヿ一-鿿]", jp + name) and \
                not re.fullmatch(r"(?:[‥…。、！？・ー]|\{br\})+", jp):
            continue        # a line of Japanese punctuation only (‥‥。) is text too
        seen.add(off)
        rows.append({"ID": f"{rel}:0x{off:x}", "File": rel, "Offset": f"0x{off:x}",
                     "MaxBytes": len(raw), "PtrSite": " ".join(f"0x{s:x}" for s in sites[off]),
                     "Kind": "tagged" if tag else "line",
                     "Speaker": name, "Tag": chr(tag) if tag else "",
                     "Japanese": jp, "English": "", "Status": "untranslated"})
    return rows


def en_key(path: str, off: int) -> str:
    """the key of a tagged row in config/patch/tagged_rows_en.json:
    "<DIR>/<FILE>:0x<offset of the string>" (the same form as its "keep"
    map).  `path` may be the repo path (assets/extracted_iso/CDROM/...), the
    CD path (CDROM/DIR/FILE) or DIR/FILE already.  The rows used to be keyed
    by tag|speaker|Japanese; the public tree carries no retail text, so the
    Japanese is read from the player's disc and never stored (D4(a))."""
    rel = path.split("extracted_iso/", 1)[-1]
    if rel.startswith("CDROM/"):
        rel = rel[len("CDROM/"):]
    return f"{rel}:0x{off:x}"


def main():
    index = json.loads(CONTAINERS.read_text())
    out_rows = []
    per_dir = Counter()
    per_dir_chars = Counter()
    for rel, info in sorted(index.items()):
        cdrom = rel.split("extracted_iso/")[1]
        d = cdrom.split("/")[1]
        if d in ("BATTLE", "BUNKASD"):
            continue
        with open(locate(info["sheet"]), encoding="utf-8") as fh:
            sheet_offs = {int(r["Offset"], 16) for r in csv.DictReader(fh)}
        for row in scan_container(rel, info, sheet_offs):
            row["Key"] = en_key(rel, int(row["Offset"], 16))    # tagged_rows_en.json key
            out_rows.append(row)
            per_dir[d] += 1
            per_dir_chars[d] += len(row["Japanese"])
    dst = ROOT / "build" / "patch" / "gen" / "tagged_rows.csv"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        wr.writeheader()
        wr.writerows(out_rows)
    for d, n in sorted(per_dir.items()):
        print(f"{d:9s} {n:6d} rows not in the sheets ({per_dir_chars[d]} chars)")
    print(f"total {len(out_rows)} -> {dst.relative_to(ROOT)}")
    spk = Counter(r["Speaker"] for r in out_rows if r["Speaker"])
    print("speaker prefixes:", spk.most_common(40))


if __name__ == "__main__":
    main()
