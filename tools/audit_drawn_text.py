#!/usr/bin/env python3
"""audit_drawn_text.py - the broken-English-text audit, on both targets.

Every string the English patch's set_kanji_string draws is logged by the
target and classified here:

  PC port     TOKI_TEXTLOG=<file.jsonl> with TOKI_LANG=en (pc/hal/text_audit.c):
              one JSON line per distinct (address, bytes) drawn, with the
              frame, scene / step / sub-step, position, the address and, for
              a HOST address (a host copy of retail data the English
              executable never reaches), its host symbol.
  PS1 disc    the english-drawlog profile (config/patch/english-drawlog.json,
              src/patch/drawlog/drawlog.c): a RAM ring of the distinct
              strings drawn that still carry Shift-JIS; read from a RAM dump
              (regtest -dumpram, coverage_campaign.py's per-item ram.bin,
              playthrough.py --retail --shots --vram's <label>.ram).

Flags per string: `japanese` (a Shift-JIS character), `box` (a kanji the
English font cannot draw: outside the kept subset, drawn as a box),
`mixed` (Latin letters and Japanese in one string), `host` (PC: drawn from
a host copy, never from PS1 RAM).  Strings whose Japanese is only the
symbols the English font keeps (　○×△□) are not flagged; the coverage
plan's `expected_japanese` ranges (the name-entry key grids, a kana name
the player typed) are `expected`.

Each flagged string is looked up by its Japanese text in the patch build's
inventory (build/patch/text_sources.json: every Japanese string on the disc
with its file, offset and status) and classed:

  a  PC-only (host copy / data source / hook routing): `host`, or drawn
     on the PC while the PS1 run of the same build never draws it Japanese
     (needs --ps1 for the second rule)
  b  patch bug: the inventory says the patch translates it ("injected"),
     or it is a mixed string, yet the PS1 draws it Japanese
  c  untranslated content: the inventory lists it as sheet-missing /
     untranslated / kept, or a text the inventory has no row for
     (a formatter's buffer: `unknown source`, listed for review)
  d  baked art: never drawn as text -- listed from the art inventory
     (`--art`), not detected here

Usage:
  audit_drawn_text.py scan --pc LOG.jsonl... [--ps1 RAM.bin|CAMPAIGN_DIR...]
        [--json OUT] [--md OUT] [--baseline config/patch/drawn_text_baseline.json]
        [--check] [--write-baseline]

  --check fails (exit 1) when a flagged, non-expected string's key is not
  in the baseline (a regression: newly broken text); --write-baseline
  records the current set.  The baseline stores only hashes of the text
  and the class (no game text), per target.

Typical runs (docs/translation/BROKEN-STRINGS-AUDIT.md):
  PC:  python3 pc/tools/playthrough.py pc/tools/playthrough/english_tour.txt \\
           --set TOKI_LANG=en --set TOKI_TEXTLOG=$PWD/build/audit/pc/tour.jsonl
  PS1: python3 tools/patch/build_patched.py config/patch/english-drawlog.json
       REFEMU_REGTEST=... python3 tools/patch/coverage_campaign.py --jobs 12
  then: python3 tools/patch/audit_drawn_text.py scan --pc build/audit/pc/*.jsonl \\
           --ps1 build/patch/campaign --md build/audit/report.md --check
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, PC, locate              # noqa: E402
import textcodec  # noqa: E402
import draw_log   # noqa: E402

DTE = ROOT / "build" / "patch" / "gen" / "dte.json"
KANJI = ROOT / "build" / "patch" / "gen" / "kanji_subset.json"
SOURCES = ROOT / "build" / "patch" / "text_sources.json"
PLAN = PATCH_CONFIG / "coverage_plan.json"
BASELINE = PATCH_CONFIG / "drawn_text_baseline.json"
FONT_KEEPS = set("　○×△□")
JP_RE = re.compile(r"[　-ヿ一-鿿＀-￯]")
WIN = 6                                    # inventory lookup window (chars)


def load_dte():
    return json.loads(DTE.read_text())["entries"] if DTE.exists() else None


def drawable_codes():
    if not KANJI.exists():
        return None
    return set(json.loads(KANJI.read_text())["drawable_codes"])


def sjis_codes(raw: bytes):
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0:
            return
        if textcodec.is_sjis_lead(b) and i + 1 < len(raw):
            yield (b << 8) | raw[i + 1]
            i += 2
        else:
            i += 1


def jp_only(text):
    return "".join(c for c in text if JP_RE.match(c) and c not in FONT_KEEPS)


# ------------------------------------------------------------ inventory
class Inventory:
    """Japanese text -> [(file, offset, status)] from text_sources.json,
    looked up by WIN-character windows of the drawn string's Japanese"""

    def __init__(self, path=SOURCES):
        self.win = defaultdict(set)
        self.rows = []
        if not path.exists():
            return
        d = json.loads(path.read_text())
        for rec in d["records"]:
            for src in rec["sources"]:
                for r in src["runs"]:
                    t = jp_only(r["text"])
                    if len(t) < 2:
                        continue
                    k = len(self.rows)
                    self.rows.append((rec["file"], r["off"], r["status"], r["text"][:60]))
                    for i in range(0, max(1, len(t) - WIN + 1), 2):
                        self.win[t[i:i + WIN]].add(k)

    def lookup(self, text):
        t = jp_only(text)
        if len(t) < 2:
            return []
        votes = defaultdict(int)
        for i in range(0, max(1, len(t) - WIN + 1)):
            for k in self.win.get(t[i:i + WIN], ()):
                votes[k] += 1
        best = sorted(votes, key=lambda k: -votes[k])[:3]
        return [self.rows[k] for k in best]


def status_class(status):
    s = status.split(" (")[0]
    if s.startswith("injected"):
        return "translated"
    if s.startswith("sheet-missing") or s.startswith("kept"):
        return "untranslated"
    if s.startswith("art"):
        return "art"
    return "other"


# ------------------------------------------------------------ readers
def read_pc(paths, dte, route_of=None):
    out = []
    for p in paths:
        route = route_of(p) if route_of else Path(p).stem
        with open(p, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue                           # a line cut by a crash
            raw = bytes.fromhex(e["hex"])
            out.append({"target": "pc", "route": route, "frame": e["f"], "scene": e["scene"],
                        "step": e["step"], "sub": e["sub"], "x": e["x"], "y": e["y"],
                        "addr": int(e["addr"], 16), "host": bool(e.get("host")),
                        "sym": e.get("sym", ""), "raw": raw,
                        "text": textcodec.decode(raw, dte)})
    return out


def read_ps1(paths, dte):
    rams = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            rams += [(q.parent.name, q) for q in sorted(p.glob("*/ram.bin"))]
            # playthrough.py --retail --shots --vram: the reference's RAM
            # (shots/ holds the PC's own RAM, which has no drawlog ring)
            rams += [(q.parent.name + "/" + q.stem, q)
                     for q in sorted(p.glob("**/shots-retail/**/*.ram"))]
        else:
            rams.append((p.stem, p))
    out = []
    for route, q in rams:
        ram = q.read_bytes()
        parsed = draw_log.parse(ram, dte)
        if not parsed:
            continue
        for e in parsed["entries"]:
            a = int(e["addr"], 16)
            raw = b""
            if 0x80000000 <= a < 0x80000000 + len(ram):
                raw = ram[a - 0x80000000:a - 0x80000000 + 400].split(b"\0")[0]
            out.append({"target": "ps1", "route": route, "frame": e["seq"], "scene": e["scene"],
                        "step": e["step"], "sub": e["sub"], "x": e["x"], "y": e["y"],
                        "addr": a, "host": False, "sym": "", "raw": raw,
                        "text": e["text"]})
    return out


# ------------------------------------------------------------ classify
HOST_TABLES = ("pc/src/missing_globals_gen.c", "pc/src/globals.c")
_WARNED = []


def retail_copy_names():
    """the PC's host definitions that hold retail data (pc_retail_init rows
    and the hand-written globals.c): a draw from one of them is a draw from
    a host copy, which the English executable never reaches"""
    names = set()
    if PC is None and not _WARNED:
        _WARNED.append(1)
        print("[audit_drawn_text] no PC port checkout (toki1-pc): host-copy "
              "draws are not recognised", file=sys.stderr)
    for rel in HOST_TABLES:
        p = locate(rel)
        if p.exists():
            names |= set(re.findall(r"^(?:static\s+)?(?:const\s+)?(?:u8|s8|u16|s16|u32|s32|char)"
                                    r"\s+\*?(\w+)\s*(?:\[|=|;)", p.read_text(), re.M))
    return names


RETAIL_COPIES = None


def flags_of(rec, drawable):
    global RETAIL_COPIES
    if RETAIL_COPIES is None:
        RETAIL_COPIES = retail_copy_names()
    text = rec["text"]
    jp = jp_only(text)
    f = []
    if jp:
        f.append("japanese")
        if re.search(r"[A-Za-z]{2}", re.sub(r"\{[A-Za-z0-9]+\}", "", text)):
            f.append("mixed")
    if drawable is not None and rec["raw"]:
        if any(c not in drawable and c >> 8 >= 0x88 for c in sjis_codes(rec["raw"])):
            f.append("box")
    if rec["host"] and (jp or rec["sym"] in RETAIL_COPIES):
        # a host address: the native engine's own buffers are fine; Japanese
        # from one, or any draw from a host copy of retail data, is not
        f.append("host")
    return f


PLAYER_KANA = "あいうえお"     # the checkpoint template album's names (new_game.txt)


def expected_why(rec, plan, player_kana=PLAYER_KANA):
    for x in plan.get("expected_japanese", []):
        lo, hi = int(x["from"], 16), int(x["to"], 16)
        if rec["step"] != x["step"]:
            continue
        if lo <= rec["addr"] < hi:
            return x["why"]
        # a range on the PS1 stack (a buffer the code builds in its frame):
        # on the PC that frame is the native stack, a host address with no
        # symbol
        if lo >= 0x801F0000 and rec["host"] and not rec["sym"]:
            return x["why"] + " (PC: the native stack)"
    jp = jp_only(rec["text"])
    if jp and player_kana and set(jp) <= set(player_kana):
        return ("the player's own kana name (a Japanese name typed on a card the run "
                "loaded: the checkpoint albums are new_game.txt's あい / うえ / お)")
    return None


def key_of(text):
    return hashlib.sha1(jp_only(text).encode("utf-8")).hexdigest()[:16]


def classify(recs, inv, drawable, plan, ps1_keys, player_kana=PLAYER_KANA):
    groups = {}
    for r in recs:
        f = flags_of(r, drawable)
        if "japanese" not in f and "host" not in f:
            continue
        k = key_of(r["text"]) if "japanese" in f else "host:" + (r["sym"] or hex(r["addr"]))
        g = groups.get((r["target"], k))
        if not g:
            hits = inv.lookup(r["text"]) if "japanese" in f else []
            st = status_class(hits[0][2]) if hits else "unknown"
            why = expected_why(r, plan, player_kana)
            if why:
                cls = "expected"
            elif "host" in f:
                cls = "a"
            elif r["target"] == "pc" and ps1_keys is not None and k not in ps1_keys \
                    and st == "translated":
                cls = "a"
            elif st == "translated" or "mixed" in f:
                cls = "b"
            else:
                cls = "c"
            g = groups[(r["target"], k)] = {
                "target": r["target"], "key": k, "class": cls, "flags": f,
                "text": r["text"][:120], "addr": f"0x{r['addr']:X}", "sym": r["sym"],
                "scene": r["scene"], "step": r["step"], "sub": r["sub"],
                "x": r["x"], "y": r["y"], "routes": [], "source_status": st,
                "sources": [{"file": h[0], "off": f"0x{h[1]:X}", "status": h[2]} for h in hits],
                "expected": why}
        if r["route"] not in g["routes"]:
            g["routes"].append(r["route"])
        for x in f:
            if x not in g["flags"]:
                g["flags"].append(x)
    return sorted(groups.values(), key=lambda g: (g["target"], g["class"], g["step"], g["text"]))


def summarize(groups):
    s = defaultdict(lambda: defaultdict(int))
    for g in groups:
        s[g["target"]][g["class"]] += 1
        if "box" in g["flags"]:
            s[g["target"]]["with_box"] += 1
        if "mixed" in g["flags"]:
            s[g["target"]]["mixed"] += 1
    return {t: dict(v) for t, v in s.items()}


def write_md(groups, summary, counts, path):
    L = ["# Drawn-text audit (generated by tools/patch/audit_drawn_text.py)", ""]
    L.append("| target | strings drawn | flagged a | b | c | expected | with box | mixed |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for t in ("pc", "ps1"):
        if t not in counts:
            continue
        s = summary.get(t, {})
        L.append(f"| {t} | {counts[t]} | {s.get('a', 0)} | {s.get('b', 0)} | {s.get('c', 0)} | "
                 f"{s.get('expected', 0)} | {s.get('with_box', 0)} | {s.get('mixed', 0)} |")
    L.append("")
    for cls, title in (("a", "a: PC-only"), ("b", "b: patch bug (PS1 too)"),
                       ("c", "c: untranslated content")):
        L.append(f"## {title}")
        L.append("")
        L.append("| target | step/sub | x,y | routes | flags | source | text |")
        L.append("|---|---|---|---|---|---|---|")
        for g in groups:
            if g["class"] != cls:
                continue
            src = g["sym"] or (f"{g['sources'][0]['file']}:{g['sources'][0]['off']} "
                               f"({g['sources'][0]['status']})" if g["sources"] else
                               f"{g['addr']} (no inventory row)")
            routes = ", ".join(g["routes"][:3]) + (" ..." if len(g["routes"]) > 3 else "")
            L.append(f"| {g['target']} | {g['step']}/{g['sub']} | {g['x']},{g['y']} | {routes} | "
                     f"{' '.join(g['flags'])} | {src} | {g['text'][:60].replace('|', '/')} |")
        L.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


# ------------------------------------------------------------ class d: baked art
# Every text-bearing picture docs/translation/SPRITE-TEXT-INVENTORY.md lists
# (section 4, plus the manual-review and optional rows): CDROM path, what the
# text is, how often a player sees it (1 = every session ... 4 = rare or
# optional), and the inventory section.  `art` says, per target, whether the
# English build changes the file at all (the patch staging vs the extracted
# disc; the PC's <assets>-en copy vs <assets>/raw).  A changed file can still
# carry unconverted cells (MAINROM p1/p2/p7/p11/p12, FILESEL pages, the
# NAME_ENT field labels): see the inventory and PS1-PATCH-STATUS section 5.
ART = [
    ("FUKUTEST/MAINROM.NBN", "calendar HUD labels, date units, weekdays; magazine strips, profile labels", 1, "3.1"),
    ("FUKUTEST/FILESEL.NBN", "file select / album buttons and labels", 1, "3.2"),
    ("FUKUTEST/TITLE.NBN", "title menu Game Start / Options", 1, "3.4"),
    ("NAME_ENT/NAME_ENT.NBN", "name-entry tabs; field labels (shared cells)", 1, "3.3"),
    ("PROLODIR/CUT_10.NBN", "prologue name card (Rei Ijuin)", 2, "3.9"),
    ("FUKUTEST/OPTION.NBN", "title Options sub-lists, sprite frames: text speed, icon mode "
     "'free', menu mode, cursor speed, voice 'X button skips'", 1, "PS1-PATCH-STATUS 5.0"),
    ("FUKUTEST/EXAMINE.NBN", "exam results header + points glyph", 2, "3.5"),
    ("BATTLE/VS_PARK.BIN", "RPG_BAT command box (+ 8 BATTLE copies); miss stack", 2, "3.8"),
    ("TAIIKU/SPSETU.BIN", "sports day: spoon relay instruction panel", 3, "3.6"),
    ("TAIIKU/KASETU.BIN", "sports day: borrowing race instruction panel", 3, "3.6"),
    ("TAIIKU/TASETU.BIN", "sports day: ball roll instruction panel", 3, "3.6"),
    ("TAIIKU/NINSETU.BIN", "sports day: three-legged race panels (casual + polite)", 3, "3.6"),
    ("TAIIKU/SPOON.BIN", "sports day cue cards (heave / right / left), flags", 3, "3.6"),
    ("TAIIKU/NININ.BIN", "sports day cue cards + speech bubble", 3, "3.6"),
    ("TAIIKU/TAI_BG.BIN", "sports day cue cards (second copy)", 3, "3.6"),
    ("TAIIKU/TAMA.BIN", "ball roll course-out banner; name tags", 3, "3.6"),
    ("TAIIKU/KARI.BIN", "borrowing race disqualified banner", 3, "3.6"),
    ("EN_GAME/SHATEKI.BIN", "summer festival shooting instruction panel", 3, "3.7"),
    ("EN_GAME/KINGYO.BIN", "summer festival goldfish instruction panel", 3, "3.7"),
    ("TARA_OBJ/OMIKUJI.BIN", "shrine fortune slip ranks", 3, "3.9"),
    ("BUNKASD/B_BUNGEI.BIN", "culture festival speech-contest board + topic pieces", 3, "3.9"),
    ("BUNKASD/B_SUISOU.BIN", "culture festival brass band board", 3, "3.9"),
    ("BUNKASD/B_DENNOU.BIN", "culture festival computer club signs", 3, "3.9"),
    ("BUNKASD/B_TENSOU.BIN", "culture festival science club signs", 3, "3.9"),
    ("TACO/TACOTEX.NBN", "TACO sub-game tutorial text (OPERATIONS)", 4, "3.9"),
    ("LASTPHOT/ALL_C.NBN", "all-clear picture caption", 4, "3.5"),
    ("BUNKASD/B_ROMEO.BIN", "culture festival drama act cards (optional signage)", 4, "3.9"),
    ("BUNKASD/B_KARUTO.BIN", "culture festival hero-show logo (optional signage)", 4, "3.9"),
    ("FUKUTEST/JOHO.NBN", "TEL screens (no legible text found; optional)", 4, "3.5"),
    ("FUKUTEST/ALBUM.NBN", "album cover tiny line (optional)", 4, "3.5"),
]


def art_report(staging, extracted, pc_raw, pc_en):
    rows = []
    for rel, what, seen, sec in ART:
        st = {}
        for tgt, a, b in (("ps1", staging, extracted), ("pc", pc_en, pc_raw)):
            pa, pb = Path(a) / "CDROM" / rel, Path(b) / "CDROM" / rel
            if not pb.exists():
                st[tgt] = "no base"
            elif not pa.exists():
                st[tgt] = "unchanged" if tgt == "pc" else "no build"
            else:
                st[tgt] = "unchanged" if pa.read_bytes() == pb.read_bytes() else "changed"
        rows.append({"file": rel, "text": what, "seen": seen, "inventory": sec, **st})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--pc", nargs="*", default=[], help="TOKI_TEXTLOG .jsonl files (globs ok)")
    s.add_argument("--ps1", nargs="*", default=[], help="RAM dumps or a campaign directory")
    s.add_argument("--player-kana", default=PLAYER_KANA,
                   help="kana a loaded card's player names use (expected Japanese); '' = none")
    s.add_argument("--json")
    s.add_argument("--md")
    s.add_argument("--baseline", default=str(BASELINE))
    s.add_argument("--check", action="store_true")
    s.add_argument("--write-baseline", action="store_true")
    r = sub.add_parser("art", help="class d: the inventory's baked-text pictures, per target")
    r.add_argument("--staging", default=str(ROOT / "build/patch/iso/staging"))
    r.add_argument("--extracted", default=str(DECOMP / "assets/extracted_iso"))
    r.add_argument("--pc-raw", default=str(locate("pc/assets/raw")))
    r.add_argument("--pc-en", default=str(locate("pc/assets-en/raw")))
    r.add_argument("--json")
    a = ap.parse_args()
    if a.cmd == "art":
        rows = art_report(a.staging, a.extracted, a.pc_raw, a.pc_en)
        for x in sorted(rows, key=lambda x: (x["seen"], x["file"])):
            print(f"{x['seen']}  {x['file']:24s} ps1 {x['ps1']:9s} pc {x['pc']:9s} {x['text']}")
        if a.json:
            Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        return

    dte = load_dte()
    drawable = drawable_codes()
    plan = json.loads(PLAN.read_text()) if PLAN.exists() else {}
    inv = Inventory()
    pc_paths = sorted({q for p in a.pc for q in glob.glob(p)})
    pc = read_pc(pc_paths, dte)
    ps1 = read_ps1(a.ps1, dte) if a.ps1 else []
    ps1_keys = None
    if a.ps1:
        ps1_keys = {key_of(r["text"]) for r in ps1 if jp_only(r["text"])}
    groups = classify(pc + ps1, inv, drawable, plan, ps1_keys, a.player_kana)
    counts = {}
    if a.pc:
        counts["pc"] = len(pc)
    if a.ps1:
        counts["ps1"] = sum(1 for _ in ps1)
    summary = summarize(groups)
    print(f"[audit] PC: {len(pc_paths)} logs, {len(pc)} distinct draws; "
          f"PS1: {len(ps1)} Japanese ring entries")
    for t, v in sorted(summary.items()):
        print(f"[audit] {t}: " + ", ".join(f"{k}={n}" for k, n in sorted(v.items())))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"summary": summary, "counts": counts,
                                            "groups": groups}, indent=1, ensure_ascii=False))
    if a.md:
        write_md(groups, summary, counts, a.md)
    flagged = {(g["target"], g["key"]): g["class"] for g in groups if g["class"] != "expected"}
    bpath = Path(a.baseline)
    if a.write_baseline:
        old = json.loads(bpath.read_text()) if bpath.exists() else {}
        known = old.get("known", {})
        for (t, k), c in flagged.items():
            known.setdefault(t, {})[k] = c
        bpath.write_text(json.dumps({
            "note": "known broken / untranslated drawn strings by target: sha1(Japanese "
                    "characters)[:16] -> class (tools/patch/audit_drawn_text.py; "
                    "docs/translation/BROKEN-STRINGS-AUDIT.md). No game text is stored.",
            "known": {t: dict(sorted(v.items())) for t, v in sorted(known.items())}},
            indent=1) + "\n")
        print(f"[audit] baseline -> {bpath} ({sum(len(v) for v in known.values())} keys)")
    if a.check:
        known = json.loads(bpath.read_text()).get("known", {}) if bpath.exists() else {}
        new = [(t, k, c) for (t, k), c in flagged.items() if k not in known.get(t, {})]
        new_a = [(t, k, c) for (t, k), c in flagged.items() if c == "a"]
        for t, k, c in new:
            g = next(g for g in groups if g["target"] == t and g["key"] == k)
            print(f"[audit] NEW {t} class {c}: step {g['step']}/{g['sub']} {g['addr']} "
                  f"{g['sym']} {g['text'][:60]!r}")
        if new:
            print(f"[audit] FAIL: {len(new)} flagged string(s) not in {bpath}")
            sys.exit(1)
        if new_a and any(t == "pc" for t, _, _ in new_a):
            pass
        print("[audit] OK: no flagged string outside the baseline")


if __name__ == "__main__":
    main()
