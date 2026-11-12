#!/usr/bin/env python3
"""mag_genre_tags.py - the exe pokes that point the Memorial Spot magazine's
genre tags at English word strips (docs/translation/VISUAL-SWEEP.md 3.2).

The magazine page (config_screen_init, holiday screen icon 10, step
70/32/1) draws its MOVIE / CONCERT genre tags as frames 134..143 of the
exe's sprite frame table `basyo_init_tbl1`.  Each frame record is

    s16 n, s16 160, s16 56, s16 0, then n cels of 7 s16:
    (ox, oy, cel, tp, attr, w, h)

and the retail tags are 1..5 cels of 8x8 katakana shared between tags
(ク serves クラシック twice and ロック, ア four tags) on rows 48..71 of
FUKUTEST/MAINROM.NBN page 12 (cel page 0xA; tile = page << 8 | row << 4 |
column, 8-px tiles; the stadium labels' frames 144 / 145 point at 0xA80 /
0xA84 = page 12 (0, 64) / (32, 64), the cells mag_stadium_* edit).  No
in-page edit can make shared kana read as ten English words, so every
record is rewritten in place to the cel(s) of ONE English word strip:
the `genre_*` cells of src/patch/art/MAINROM/manifest.json ("frame" names
the record a cell serves; a "pieces" cell is one cel per piece, set side
by side).  The first retail cel's ox / oy / tp / attr are kept, so the
word starts where the kana did.  A record only shrinks: the cels after
the new ones are zeroed, n is lowered.

The pokes live in config/patch/english.json `main.pokes` (notes start with
NOTE_TAG).  This tool generates them from the manifest and the retail exe:

    python3 tools/patch/mag_genre_tags.py            # print them (JSON)
    python3 tools/patch/mag_genre_tags.py --check    # profile == generated
    python3 tools/patch/mag_genre_tags.py --apply    # write them into the profile
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, ART, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
EXE = DECOMP / "disks" / "SLPS_000.65"
MANIFEST = ART / "MAINROM/manifest.json"
PROFILE = PATCH_CONFIG / "english.json"
TABLE = 0x800CFC5C              # basyo_init_tbl1 (config/patch/symbols.json)
FRAMES = range(134, 144)        # the ten genre tags
MAINROM_PAGE = 12               # the manifest page the tags' cels address ...
CEL_PAGE = 0xA                  # ... as cel page 0xA in this table
NOTE_TAG = "magazine genre tag"


def fo(addr):
    return addr - 0x80041000 + 0x800


def record(exe, frame):
    addr = struct.unpack_from("<I", exe, fo(TABLE + 4 * frame))[0]
    n = struct.unpack_from("<h", exe, fo(addr))[0]
    cels = [struct.unpack_from("<7h", exe, fo(addr) + 8 + 14 * k) for k in range(n)]
    return addr, cels


def tile(page, x, y):
    if page != MAINROM_PAGE:
        raise SystemExit(f"[genre] a genre cell must be on MAINROM page {MAINROM_PAGE}, not {page}")
    if x % 8 or y % 8:
        raise SystemExit(f"[genre] ({x}, {y}) is not on the 8-px tile grid")
    return CEL_PAGE << 8 | (y // 8) << 4 | (x // 8)


def pieces(cell):
    if "pieces" in cell:
        return [(int(p["page"]), int(p["x"]), int(p["y"]), int(p["w"])) for p in cell["pieces"]]
    return [(int(cell["page"]), int(cell["x"]), int(cell["y"]), int(cell["w"]))]


def generate(exe=None, man=None):
    exe = exe if exe is not None else EXE.read_bytes()
    man = man if man is not None else json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_frame = {}
    for c in man["cells"]:
        if c["name"].startswith("genre_") and "frame" in c:
            f = int(c["frame"])
            if f in by_frame:
                raise SystemExit(f"[genre] frame {f} served by {by_frame[f]['name']} and {c['name']}")
            by_frame[f] = c
    if sorted(by_frame) != list(FRAMES):
        raise SystemExit(f"[genre] the genre cells serve frames {sorted(by_frame)}, "
                         f"expected {FRAMES.start}..{FRAMES.stop - 1}")
    pokes = []
    for f in FRAMES:
        c = by_frame[f]
        addr, cels = record(exe, f)
        if not cels or any(t[2] >> 8 != CEL_PAGE for t in cels):
            raise SystemExit(f"[genre] frame {f}: retail cels {cels} are not the page-0x{CEL_PAGE:X} kana")
        ox, oy, _, tp, attr, _, _ = cels[0]
        h = int(c["h"])
        new = []
        for page, x, y, w in pieces(c):
            new.append((ox, oy, tile(page, x, y), tp, attr, w, h))
            ox += w
        if len(new) > len(cels):
            raise SystemExit(f"[genre] frame {f}: {c['name']} needs {len(new)} cels, the record holds {len(cels)}")
        blob = b"".join(struct.pack("<7h", *t) for t in new) + bytes(14 * (len(cels) - len(new)))
        note = f"{NOTE_TAG}: frame {f} -> {c['text']} ({c['name']})"
        pokes.append({"addr": f"0x{addr:08X}", "u16": len(new), "note": note + ", cel count"})
        pokes.append({"addr": f"0x{addr + 8:08X}", "bytes": blob.hex(), "note": note + ", cels"})
    return pokes


def profile_pokes(prof):
    return [p for p in prof.get("main", {}).get("pokes", []) if p.get("note", "").startswith(NOTE_TAG)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="the profile's pokes must equal the generated ones")
    ap.add_argument("--apply", action="store_true", help="write the generated pokes into the profile")
    ap.add_argument("--profile", default=str(PROFILE))
    a = ap.parse_args()
    gen = generate()
    if not (a.check or a.apply):
        print(json.dumps(gen, indent=1, ensure_ascii=False))
        return 0
    path = Path(a.profile)
    text = path.read_text(encoding="utf-8")
    prof = json.loads(text)
    if a.check:
        have = profile_pokes(prof)
        if have != gen:
            print(f"[genre] {path}: the {NOTE_TAG} pokes differ from the generated ones "
                  f"(run --apply)", file=sys.stderr)
            return 1
        print(f"[genre] {path}: {len(gen)} pokes OK (frames {FRAMES.start}..{FRAMES.stop - 1})")
        return 0
    main_ = prof.setdefault("main", {})
    kept = [p for p in main_.get("pokes", []) if not p.get("note", "").startswith(NOTE_TAG)]
    main_["pokes"] = kept + gen
    indent = 2 if text.startswith("{\n  \"") else 1
    path.write_text(json.dumps(prof, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[genre] {path}: {len(gen)} pokes written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
