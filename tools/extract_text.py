#!/usr/bin/env python3
"""Extract ALL Japanese script/dialogue text from Tokimeki Memorial FwY into
an industry-standard, round-trippable translation package.

Sources scanned (deterministic order):
  - disks/SLPS_000.65                (main executable)
  - assets/overlays/*.EXN            (scene overlays -- most dialogue)
  - assets/extracted_iso/CDROM/**    (data containers; media formats skipped)

Every maximal valid Shift-JIS run (>= MIN_CHARS chars, majority Japanese) is
recorded with its exact file offset and byte length, so a filled-in sheet can
be injected back byte-for-byte by tools/translation/inject_text.py.

Outputs (translation/ -- tracked):
  translation/tokimeki_script.csv   master sheet: ID,File,Offset,Bytes,
                                    MaxBytes,Context,Japanese,Translation,Notes
  translation/tokimeki_script.pot   gettext template (msgctxt=ID, msgid=JA)
                                    -- hand either file to a translator; PO
                                    editors (Poedit etc.) open the .pot as-is.
  translation/extract_report.json   per-file counts + skip list

IDs are stable: <relpath>:<hex offset>. Re-running after a binary change only
changes entries whose bytes moved.

Usage: .venv/bin/python3 tools/translation/extract_text.py [--min-chars N]
"""
import csv
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT, locate  # noqa: E402  (this checkout, either layout)
sys.path.insert(0, str(ROOT / "tools"))
from repo_paths import DECOMP  # noqa: E402  (the extracted disc is toki1-decomp's)
OUT = locate("translation/tokimeki_script.csv").parent   # translation/, or work/ (public)
MEDIA_EXT = {".STR", ".XA", ".VH", ".VB", ".SEQ", ".TIM", ".WAV", ".TMD",
             ".BS", ".BAK", ".str", ".xa"}
MIN_CHARS = 6

# Shift-JIS classification. Half-width katakana (0xFF61-0xFF9F) deliberately
# does NOT count as "strong" Japanese: lone half-width runs are almost always
# machine code masquerading as text (measured: they inflate the extraction
# 10x with garbage). They are still decoded when adjacent to real text.
def is_jp(ch):
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or   # hiragana + katakana
            0x4E00 <= o <= 0x9FFF or   # kanji
            0xFF01 <= o <= 0xFF60 or   # full-width forms
            ch in "。、！？「」『』（）・〜ー…　")


def is_kana_kanji(ch):
    o = ord(ch)
    return 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF


def sjis_lead(b):
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def sjis_trail(b):
    return 0x40 <= b <= 0xFC and b != 0x7F


def scan_file(data):
    """Yield (offset, raw_bytes, decoded) for every valid SJIS run."""
    n = len(data)
    i = 0
    while i < n:
        b = data[i]
        start = i
        raw = bytearray()
        # a run = sequence of double-byte SJIS chars, half-width katakana,
        # or printable ASCII embedded between them
        while i < n:
            b = data[i]
            if sjis_lead(b) and i + 1 < n and sjis_trail(data[i + 1]):
                raw += data[i:i + 2]
                i += 2
            elif 0xA1 <= b <= 0xDF:            # half-width katakana
                raw.append(b)
                i += 1
            elif 0x20 <= b <= 0x7E and raw:    # ASCII inside a run only
                raw.append(b)
                i += 1
            else:
                break
        if raw:
            try:
                text = raw.decode("shift_jis")
            except UnicodeDecodeError:
                i = start + 1
                continue
            jp = sum(1 for c in text if is_jp(c))
            kk = sum(1 for c in text if is_kana_kanji(c))
            uniq = len(set(text))
            if (len(text) >= MIN_CHARS and jp * 2 >= len(text) and
                    kk >= 3 and uniq >= 4 and
                    not all(c == text[0] for c in text)):
                yield start, bytes(raw), text
        else:
            i += 1


def sources():
    files = []
    exe = DECOMP / "disks/SLPS_000.65"
    if exe.exists():
        files.append(exe)
    files += sorted((DECOMP / "assets/overlays").glob("*.EXN"))
    cdrom = DECOMP / "assets/extracted_iso/CDROM"
    if cdrom.exists():
        for f in sorted(cdrom.rglob("*")):
            if f.is_file() and f.suffix not in MEDIA_EXT:
                files.append(f)
    return files


def po_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main():
    global MIN_CHARS
    if "--min-chars" in sys.argv:
        MIN_CHARS = int(sys.argv[sys.argv.index("--min-chars") + 1])
    OUT.mkdir(exist_ok=True)
    rows = []
    report = {}
    for f in sources():
        rel = str(f.relative_to(DECOMP))
        data = f.read_bytes()
        cnt = 0
        for off, raw, text in scan_file(data):
            rows.append({
                "ID": f"{rel}:{off:#x}",
                "File": rel,
                "Offset": f"{off:#x}",
                "Bytes": len(raw),
                "MaxBytes": len(raw),
                "Context": f.stem,
                "Japanese": text,
                "Translation": "",
                "Notes": "",
            })
            cnt += 1
        report[rel] = cnt
        print(f"{rel}: {cnt} strings", flush=True)

    with open(OUT / "tokimeki_script.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    with open(OUT / "tokimeki_script.pot", "w", encoding="utf-8") as fh:
        fh.write('msgid ""\nmsgstr ""\n'
                 '"Project-Id-Version: tokimeki-fwy\\n"\n'
                 '"Content-Type: text/plain; charset=UTF-8\\n"\n\n')
        for r in rows:
            fh.write(f'#. file={r["File"]} offset={r["Offset"]} '
                     f'maxbytes={r["MaxBytes"]}\n')
            fh.write(f'msgctxt "{po_escape(r["ID"])}"\n')
            fh.write(f'msgid "{po_escape(r["Japanese"])}"\n')
            fh.write('msgstr ""\n\n')

    (OUT / "extract_report.json").write_text(
        json.dumps({"total": len(rows), "per_file": report}, indent=1,
                   ensure_ascii=False))
    print(f"\nTOTAL: {len(rows)} strings -> translation/tokimeki_script.csv "
          f"+ .pot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
