#!/usr/bin/env python3
"""Cross-check the extracted translation sheet against KNOWN code layout so
we neither ship false positives nor miss real text.

Two independent ground-truth sources, both already in the repo:
  1. Overlay .sym maps (config/overlay/*.sym): every function's exact
     address+size. EXN file offset = address - 0x80132000. Any extracted
     "string" whose byte span intersects a function body is CODE, not text.
  2. Main-exe function spans from config/main_function_audit_by_addr.json
     (+ the o.bin debug-symbol cache when present, which also NAMES data
     symbols). Main file offset = address - 0x80041000 + 0x800.

Outputs:
  translation/tokimeki_script.filtered.csv  sheet minus CODE_OVERLAP rows
  translation/coverage_report.json:
    - per file: strings kept / flagged-as-code, code bytes, data bytes,
      data bytes covered by kept strings (the honest coverage number)
    - gap list: data regions >= 64 bytes with NO extracted string that
      still contain >= 8 SJIS-lead bytes  ->  candidate MISSED text, each
      with file+offset for manual eyeballing (completeness check)

Usage: .venv/bin/python3 tools/translation/verify_text_coverage.py
"""
import csv
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT, locate  # noqa: E402  (this checkout, either layout)
sys.path.insert(0, str(ROOT / "tools"))
from repo_paths import DECOMP  # noqa: E402  (.sym maps, audits, symbol caches)
SHEET = locate("translation/tokimeki_script.csv")
OVERLAY_BASE = 0x80132000
MAIN_BASE, MAIN_FOFF = 0x80041000, 0x800


def overlay_code_spans(ov):
    sym = DECOMP / f"config/overlay/{ov}.sym"
    spans = []
    if not sym.exists():
        return spans
    for line in sym.read_text().splitlines():
        p = line.strip().split(":")
        if len(p) >= 3:
            try:
                a, s = int(p[0], 16), int(p[1], 0)
            except ValueError:
                continue
            off = a - OVERLAY_BASE
            if off >= 0:
                spans.append((off, off + s))
    return sorted(spans)


def main_code_spans():
    spans = []
    audit = DECOMP / "config/main_function_audit_by_addr.json"
    if audit.exists():
        d = json.loads(audit.read_text())
        addrs = d.get("addresses", {})
        keys = sorted(addrs, key=lambda k: int(k, 16))
        for i, k in enumerate(keys):
            a = int(k, 16)
            e = addrs[k]
            size = e.get("size") if isinstance(e, dict) else None
            if not size:
                nxt = int(keys[i + 1], 16) if i + 1 < len(keys) else a + 64
                size = min(nxt - a, 0x4000)
            off = a - MAIN_BASE + MAIN_FOFF
            if off >= MAIN_FOFF:
                spans.append((off, off + size))
    # o.bin symbol cache refines/extends this when available
    for cache in (DECOMP / "build/slps00065/symbols").glob("*.json") \
            if (DECOMP / "build/slps00065/symbols").exists() else []:
        try:
            for s in json.loads(cache.read_text()):
                a = s.get("address") or s.get("addr")
                sz = s.get("size", 0)
                if a and sz and s.get("type", "").lower() in ("func", "text",
                                                             "code", ""):
                    a = int(a, 16) if isinstance(a, str) else a
                    off = a - MAIN_BASE + MAIN_FOFF
                    if off >= MAIN_FOFF:
                        spans.append((off, off + sz))
        except Exception:
            pass
    return sorted(spans)


def intersects(spans, lo, hi):
    import bisect
    i = bisect.bisect_right(spans, (lo, float("inf"))) - 1
    for j in (i, i + 1):
        if 0 <= j < len(spans):
            a, b = spans[j]
            if a < hi and lo < b:
                return True
    return False


def sjis_lead_count(data):
    return sum(1 for b in data if 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF)


def main():
    rows = list(csv.DictReader(open(SHEET, encoding="utf-8")))
    spans_cache = {}
    kept, flagged = [], []
    for r in rows:
        f = r["File"]
        if f not in spans_cache:
            if f.endswith(".EXN"):
                spans_cache[f] = overlay_code_spans(Path(f).stem)
            elif f.endswith("SLPS_000.65"):
                spans_cache[f] = main_code_spans()
            else:
                spans_cache[f] = []
        lo = int(r["Offset"], 16)
        hi = lo + int(r["Bytes"])
        if intersects(spans_cache[f], lo, hi):
            flagged.append(r)
        else:
            kept.append(r)

    out = locate("translation/tokimeki_script.filtered.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(kept)

    # completeness: scan DATA regions with no kept string for SJIS density
    report = {"total": len(rows), "kept": len(kept),
              "flagged_code_overlap": len(flagged), "per_file": {},
              "gaps": []}
    by_file = {}
    for r in kept:
        by_file.setdefault(r["File"], []).append(
            (int(r["Offset"], 16), int(r["Offset"], 16) + int(r["Bytes"])))
    for f, spans in spans_cache.items():
        src = ROOT / f
        if not src.exists():
            continue
        data = src.read_bytes()
        code = sum(b - a for a, b in spans)
        strings = sorted(by_file.get(f, []))
        covered = sum(b - a for a, b in strings)
        report["per_file"][f] = {
            "bytes": len(data), "code_bytes": code,
            "kept_strings": len(strings), "string_bytes": covered}
        # gap scan (coarse, 256-byte windows)
        marks = bytearray(len(data) // 256 + 1)
        for a, b in spans + strings:
            for w0 in range(max(0, a // 256), min(len(marks), b // 256 + 1)):
                marks[w0] = 1
        run_start = None
        for wi, m in enumerate(list(marks) + [1]):
            if not m and run_start is None:
                run_start = wi
            elif m and run_start is not None:
                lo, hi = run_start * 256, wi * 256
                if hi - lo >= 64:
                    chunk = data[lo:hi]
                    leads = sjis_lead_count(chunk)
                    if leads >= max(8, len(chunk) // 32):
                        report["gaps"].append(
                            {"file": f, "offset": hex(lo),
                             "bytes": hi - lo, "sjis_leads": leads})
                run_start = None
    (locate("translation/coverage_report.json")).write_text(
        json.dumps(report, indent=1))
    print(f"total={len(rows)} kept={len(kept)} "
          f"code_overlap={len(flagged)} gaps={len(report['gaps'])}")
    print("-> translation/tokimeki_script.filtered.csv + coverage_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
