#!/usr/bin/env python3
"""text_sources.py - the closed inventory of Japanese text on the disc.

Walks the ISO9660 tree of the Track 1 image itself (every file, every EXN
overlay, the main exe), scans every unallocated sector as well, and finds
every run of game-encoded Japanese: Shift-JIS pairs with the retail
single-byte command letters (`space q P G p m F Y S O W A M n > - + <`)
allowed between them.  Pixel data in the sprite sheets decodes to Shift-JIS
by accident, so a run is kept only when it reads as text against the
vocabulary of the game's own script (the sheets): rare kanji, repeated
characters, JIS-ordered character tables (font lists) and symbol salad are
rejected (`is_text`; the rejected counts are kept per file).

Every run is attributed to a SOURCE: the text containers' pointer-table
strings (sheet rows), their tagged rows (speaker-prefixed lines the
extractor skipped), fixed-width records, pointer-table strings and inline
literals of the main exe / overlays, the speaker and name tables, text
tables inside sprite files, the font blocks, and the strings that are not
drawn (memory-card titles for the BIOS, strcmp specials).  Per run the
coverage of the English patch is recorded:

  injected        a sheet row the injector placed, a tagged row with
                  English, a profile / ui_strings override, or a string
                  whose slot died when its pointer was relocated
  sheet-missing   drawn Japanese nothing translates yet (the draft-sheet
                  writer puts it in build/patch/gen/sheets/<DIR>/<FILE>.csv)
  art/font        glyph blocks and character tables
  not-text        strings the game never draws as text (BIOS card titles,
                  strcmp literals, dead overlays)

Output: build/patch/text_sources.json (per file: sources, runs, statuses,
loader sites, draw sites) and the COVERAGE table on stdout, which
build_patched.py prints after every build.

  python3 tools/patch/text_sources.py                  # retail image
  python3 tools/patch/text_sources.py --draft-sheets   # + draft sheets
  python3 tools/patch/text_sources.py --image build/patch/iso/patched_disc.bin --remaining
                                                       # Japanese left on the patched disc
"""
import argparse
import csv
import glob
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, SHEETS, CONTAINERS, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import retail_text  # noqa: E402

TRACK1 = DECOMP / "disks" / ("Tokimeki Memorial - Forever with You (Japan) "
                           "(Rev 1) (Track 1).bin")
SECTOR_RAW = 2352
SECTOR_USER = 2048
MAIN_BASE = 0x80041000 - 0x800
OV_BASE = 0x80132000
DEAD_OVERLAYS = {"EVENT", "GYOZI"}         # never loaded by the retail game

CONTROL = set(b" qPGpmFYSOWAMn><+-gE")
NAME_TOKENS = set(b"PGpmFYSOWAM")      # retail one-byte name/runtime tokens
RUN_RE = re.compile(rb"(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]|[ qPGpmFYSOWAMn><+\-gE])+")
JP_RE = re.compile(r"[぀-ヿ一-鿿！-｠　-〿‥…]")      # ‥ … are Japanese punctuation (SJIS 8164 / 8163)
KANA_RE = re.compile(r"[぀-ヿ]")
HIRA_RE = re.compile(r"[぀-ゟ]")
KANJI_RE = re.compile(r"[一-鿿]")
PUNCT = set("、。「」『』！？…‥ー・（）～：")
FW_ALNUM_RE = re.compile(r"[０-９Ａ-Ｚａ-ｚ＊＿－．，／＋＝％＃＆]")
SMALL_KANA = set("ァィゥェォ" "ッャュョヮ" "ぁぃぅぇぉ" "っゃゅょゎ" "ヵヶ")   # glyph classes, not text

NOT_TEXT_MAIN = {
    0x800B5A60: "memory-card title piece (BIOS card manager, Shift-JIS only)",
    0x800B5A6C: "memory-card title piece", 0x800B5A74: "memory-card title piece",
    0x800B5A7C: "memory-card title piece", 0x800B63CC: "memory-card file title",
    0x800B63E0: "memory-card file title", 0x800B63F0: "memory-card file title",
    0x800B6404: "memory-card file title",
    0x800B8800: "strcmp special (narration)", 0x800B8814: "strcmp special (sfx)",
    0x800B881C: "strcmp special (sfx)", 0x800B8824: "strcmp special (sfx)",
    0x800B882C: "strcmp special (sfx)", 0x800B884C: "strcmp special (sfx)",
    0x800B885C: "strcmp special (narration)", 0x800B8888: "strcmp special (sfx)",
    0x800B8840: "unreferenced literal",
}
FONT_MAIN = (0x800BD250, 0x800BD250 + 3418 * 18)
NAME_TABLES_MAIN = {
    (0x800B9AE0, 0x800B9AE0 + 16 * 4): "girl family-name pointer table",
    (0x800B9A24, 0x800B9A24 + 16 * 4): "girl full-name pointer table",
}


# ---------------------------------------------------------------------------
# ISO9660
# ---------------------------------------------------------------------------

class Image:
    """Track 1 as an ISO9660 tree; `read(path)` returns a file's bytes."""

    def __init__(self, path: Path):
        self.path = path
        self.f = open(path, "rb")
        self.sectors = path.stat().st_size // SECTOR_RAW
        self.files = []          # (lba, sectors, size, "/CDROM/DIR/FILE")
        self.dirs = []           # (lba, sectors, path)
        pvd = self.sector(16)
        if pvd[1:6] != b"CD001":
            raise SystemExit(f"{path}: not a raw 2352-byte Mode 2 image")
        root = pvd[156:190]
        self._walk(struct.unpack_from("<I", root, 2)[0],
                   struct.unpack_from("<I", root, 10)[0], "/")
        self.files.sort()
        self.by_path = {p: (l, s, sz) for l, s, sz, p in self.files}
        self.by_lba = {l: p for l, s, sz, p in self.files}
        self.path_tables = (struct.unpack_from("<I", pvd, 140)[0],
                            struct.unpack_from(">I", pvd, 148)[0])

    def sector(self, lba: int) -> bytes:
        self.f.seek(lba * SECTOR_RAW + 24)
        return self.f.read(SECTOR_USER)

    def _walk(self, lba, size, path):
        n = (size + SECTOR_USER - 1) // SECTOR_USER
        self.dirs.append((lba, n, path))
        data = b"".join(self.sector(lba + i) for i in range(n))
        i = 0
        while i < len(data):
            ln = data[i]
            if ln == 0:
                i = (i // SECTOR_USER + 1) * SECTOR_USER
                continue
            r = data[i:i + ln]
            el = struct.unpack_from("<I", r, 2)[0]
            es = struct.unpack_from("<I", r, 10)[0]
            flags = r[25]
            name = r[33:33 + r[32]].decode("latin1").split(";")[0]
            if name not in ("\x00", "\x01"):
                if flags & 2:
                    self._walk(el, es, path + name + "/")
                else:
                    self.files.append((el, (es + SECTOR_USER - 1) // SECTOR_USER,
                                       es, path + name))
            i += ln

    def read(self, path: str) -> bytes:
        lba, n, size = self.by_path[path]
        n = min(n, max(0, self.sectors - lba))
        return b"".join(self.sector(lba + i) for i in range(n))[:size]

    def unallocated(self):
        """[(first, last)] sector ranges no file, directory or descriptor
        covers (the DA tracks' extents point past the image and are
        clipped)."""
        cov = bytearray(self.sectors)
        for l, n, sz, p in self.files:
            for k in range(l, min(self.sectors, l + n)):
                cov[k] = 1
        for l, n, p in self.dirs:
            for k in range(l, min(self.sectors, l + n)):
                cov[k] = 1
        for k in range(0, 19):
            cov[k] = 1
        for k in self.path_tables:
            if k < self.sectors:
                cov[k] = 1
        out = []
        for k in range(self.sectors):
            if cov[k]:
                continue
            if out and out[-1][1] == k - 1:
                out[-1][1] = k
            else:
                out.append([k, k])
        return out


# ---------------------------------------------------------------------------
# runs and the text filter
# ---------------------------------------------------------------------------

def sjis_runs(data: bytes, min_chars=2):
    """[(offset, length, text)] of Shift-JIS runs with the command letters
    allowed inside (trimmed at both ends)."""
    out = []
    for m in RUN_RE.finditer(data):
        s, e = m.start(), m.end()
        # tokenise first: a trail byte can be a command letter (前 = 91 4F
        # 'O', 字 = 8E 9A), so only whole one-byte tokens are trimmed
        toks = []
        i = s
        while i < e:
            n = 2 if (0x81 <= data[i] <= 0x9F or 0xE0 <= data[i] <= 0xEF) and i + 1 < e else 1
            toks.append((i, n))
            i += n
        # a command letter right after the string's NUL is part of the
        # string (a leading name token: P = the player's name), so the row
        # starts at it; elsewhere leading/trailing letters are noise
        at_start = s > 0 and data[s - 1] == 0
        while toks and toks[0][1] == 1 and data[toks[0][0]] in CONTROL and \
                not (at_start and data[toks[0][0]] in NAME_TOKENS and len(toks) > 1 and toks[1][1] == 2):
            toks.pop(0)
            at_start = False
        while toks and toks[-1][1] == 1 and data[toks[-1][0]] in CONTROL:
            toks.pop()
        if not toks:
            continue
        s, e = toks[0][0], toks[-1][0] + toks[-1][1]
        raw = data[s:e]
        if len(raw) < 2 * min_chars:
            continue
        try:
            txt = raw.decode("shift_jis")
        except UnicodeDecodeError:
            continue
        if len(JP_RE.findall(txt)) >= min_chars:
            out.append((s, e - s, txt))
    return out


_VOCAB = None


_SKIPS = None


def reviewed_skips():
    """runs a drafting pass read and judged not to be text (pixel or table
    bytes that decode as kanji, the name-entry key grids, the secret-name
    strings): the "skip" lists of config/patch/overlay_drafts.d/*.json,
    {"<rel>:<0xoff>": reason}"""
    global _SKIPS
    if _SKIPS is None:
        _SKIPS = {}
        for f in sorted((PATCH_CONFIG / "overlay_drafts.d").glob("*.json")):
            _SKIPS.update(json.loads(f.read_text()).get("skip", {}))
    return _SKIPS


def nul_bounded_label(data: bytes, off: int, ln: int, txt: str) -> bool:
    """a 2-3 character label stored as a C string of its own in an exe or
    overlay data area: word-aligned, a NUL before it and NUL padding after
    it, every character kana or a kanji of JIS levels 1-2 (the overlay
    place and status labels the script vocabulary never spells, 玄関 廊下)"""
    if off % 4 or off < 1 or data[off - 1] != 0 or off + ln + 1 > len(data) or data[off + ln] != 0:
        return False
    for c in txt:
        if not (KANA_RE.match(c) or KANJI_RE.match(c)):
            return False
        code = int.from_bytes(c.encode("shift_jis", "replace")[:2], "big")
        if KANJI_RE.match(c) and not (0x889F <= code <= 0xEAA4):
            return False
    return True


def vocab():
    """characters of the game's own script (every sheet's Japanese) plus
    all of kana and the common punctuation; the yardstick for `is_text`"""
    global _VOCAB
    if _VOCAB is None:
        v = Counter()
        for p in glob.glob(str(SHEETS / "*/*.csv")):
            for r in retail_text.read_sheet(p):     # fills Japanese from the disc (D4)
                for ch in r["Japanese"]:
                    if JP_RE.match(ch):
                        v[ch] += 1
        for cp in range(0x3041, 0x30FF):
            v[chr(cp)] += 1
        for ch in PUNCT:
            v[ch] += 1
        _VOCAB = v
    return _VOCAB


def is_text(txt: str, strict=False):
    """(verdict, reason): text, or why it is rejected (pixel data, a
    character table, ...).  `strict` is for data files and sprite sheets,
    where every run is suspect: all-kanji runs longer than a 4-kanji label
    and heavier repetition are rejected."""
    chars = [c for c in txt if JP_RE.match(c) and c != "　"]
    n = len(chars)
    if n < 2:
        return False, "too short"
    v = vocab()
    cnt = Counter(chars)
    if n >= 4 and max(cnt.values()) / n > (0.4 if strict or n >= 5 else 0.5):
        return False, "repeated character"
    hard = [c for c in chars if not HIRA_RE.match(c) and c != "ー" and c not in PUNCT]
    if any(hard[i] == hard[i + 1] == hard[i + 2] for i in range(len(hard) - 2)):
        return False, "repeated character"
    codes = [c.encode("shift_jis") for c in chars]
    if n >= 6 and all(codes[i] <= codes[i + 1] for i in range(n - 1)) and len(cnt) >= n - 1:
        # a table runs through neighbouring codes; a word that merely happens
        # to ascend (a bullet + 'system settings' label) jumps between rows of the JIS chart
        steps = [int.from_bytes(codes[i + 1], "big") - int.from_bytes(codes[i], "big")
                 for i in range(n - 1)]
        if sum(1 for d in steps if d <= 3) >= 0.6 * (n - 1):
            return False, "character table (JIS order)"
    def _level1(c):
        code = int.from_bytes(c.encode("shift_jis", "replace")[:2], "big")
        return 0x889F <= code <= 0x9872
    known_v = sum(1 for c in chars if v.get(c, 0) >= 2) / n
    known = known_v
    if not strict and n >= 3 and known_v >= 0.5 and \
            all(v.get(c, 0) >= 2 or _level1(c) for c in chars):
        # an overlay label with one kanji the script never uses (伊集院邸)
        known = 1.0
    small = sum(1 for c in chars if c in SMALL_KANA or (not KANA_RE.match(c) and
                not KANJI_RE.match(c) and c not in PUNCT and not FW_ALNUM_RE.match(c))) / n
    hira = any(HIRA_RE.match(c) for c in chars)
    punct = any(c in PUNCT for c in chars)
    kana = any(KANA_RE.match(c) for c in chars)
    if small > 0.34:
        return False, "symbol salad"
    if n <= 3:
        if known < 1.0:
            return False, "short, not in vocabulary"
        if not (hira or punct or all(KANA_RE.match(c) for c in chars)):
            # all-kanji 2-3 char labels (校門前 教室 自宅 廊下 ...) are the
            # exe/overlay place and status strings; in pixel data they are
            # noise, so only outside strict mode
            if strict or not all(v.get(c, 0) >= 5 for c in chars):
                return False, "short, not in vocabulary"
        if sum(1 for c in chars if c in SMALL_KANA) >= 1 and not hira:
            return False, "short, small kana"
        return True, ""
    if known < 0.85:
        return False, "not in vocabulary"
    if not kana and not punct:
        # all-kanji: a name or a label is fine, longer runs are tables
        if n > (4 if strict else 6):
            return False, "kanji list"
    return True, ""


# ---------------------------------------------------------------------------
# coverage of the patch
# ---------------------------------------------------------------------------

def load_profile(path):
    """a profile with its `include` chain merged (build_patched.py's rule:
    dicts merge, lists concatenate, the including profile's scalars win);
    english-debug includes english, whose strings it ships"""
    prof = json.loads(Path(path).read_text())
    if "include" not in prof:
        return prof

    def merge(base, extra):
        for k, v in extra.items():
            if k == "include":
                continue
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                merge(base[k], v)
            elif isinstance(v, list) and isinstance(base.get(k), list):
                base[k] = base[k] + v
            else:
                base[k] = v
        return base
    return merge(load_profile(locate(prof["include"])), prof)


def load_profile_coverage(profile_path, with_sheets=True):
    """with_sheets=False leaves out what overlay_sheets.py placed: the draft
    sheets are its INPUT, so they must not shrink when a draft is applied
    (a relocated string's old slot would otherwise drop out of its sheet)"""
    cov = {"main": {}, "ov": defaultdict(dict), "files": defaultdict(dict)}
    prof = load_profile(locate(profile_path))
    extra = {"main": [], "overlays": {}, "files": {}}
    gens = [ROOT / "build/patch/gen/ui_strings.json"]
    if with_sheets:
        gens.append(ROOT / "build/patch/gen/overlay_sheets.json")
    for gen in gens:
        if gen.exists():
            g = json.loads(gen.read_text())
            tag = "sheet string" if gen.name.startswith("overlay_sheets") else "ui string"
            for e in g.get("main", []):
                extra["main"].append(dict(e, _how=tag))
            for ov, lst in g.get("overlays", {}).items():
                extra["overlays"].setdefault(ov, []).extend(dict(e, _how=tag) for e in lst)
            for rel, lst in g.get("files", {}).items():
                extra["files"].setdefault(rel, []).extend(dict(e, _how=tag) for e in lst)
    for s in prof.get("main", {}).get("strings", []) + extra.get("main", []):
        how = s.get("_how", "string override")
        if "addr" in s:
            cov["main"][int(s["addr"], 16)] = f"injected ({how})"
        elif "ptr_at" in s:
            cov["main"][int(s["ptr_at"], 16)] = f"injected (relocated via pointer; {how})"
    for ov, spec in list(prof.get("overlays", {}).items()):
        for s in spec.get("strings", []):
            if "addr" in s:
                cov["ov"][ov][int(s["addr"], 16)] = "injected (string override)"
            elif "ptr_at" in s:
                cov["ov"][ov][int(s["ptr_at"], 16)] = "injected (relocated via pointer)"
    for ov, lst in extra.get("overlays", {}).items():
        for s in lst:
            how = s.get("_how", "ui string")
            if "addr" in s and how == "ui string" and s.get("max_bytes"):
                # a ui string rewrites its retail string whole (a printf
                # format the inventory split at the %s: "おっ、%sだ。"), so
                # the runs inside it are covered too
                a0 = int(s["addr"], 16)
                for a in range(a0 + 1, a0 + int(s["max_bytes"]) + 1):
                    cov["ov"][ov].setdefault(a, f"injected (inside a {how})")
            if "addr" in s:
                cov["ov"][ov][int(s["addr"], 16)] = f"injected ({how})"
            elif "ptr_at" in s:
                cov["ov"][ov][int(s["ptr_at"], 16)] = f"injected (relocated via pointer; {how})"
    for rel, spec in prof.get("files", {}).items():
        for s in spec.get("strings", []):
            cov["files"][rel][int(s["offset"], 16)] = "injected (file string override)"
    for rel, lst in extra.get("files", {}).items():
        for s in lst:
            cov["files"][rel][int(s["offset"], 16)] = f"injected (file string; {s.get('_how', 'profile')})"
    rep = ROOT / "build" / "patch" / "inject.report.json"
    if rep.exists():
        r = json.loads(rep.read_text())
        for c in r.get("containers", []):
            cov["files"][c["file"]]["placed"] = c["rows_placed"]
            cov["files"][c["file"]]["fallback"] = {f["id"] for f in c.get("fallback_rows", [])}
    return cov, prof


def load_container_index():
    """containers.json (the extractor's, read-only) + the patch's own
    extra containers (config/patch/containers_extra.json, same format)"""
    idx = {}
    for p in (CONTAINERS,
              PATCH_CONFIG / "containers_extra.json"):
        if p.exists():
            for k, v in json.loads(p.read_text()).items():
                idx[k.split("extracted_iso/")[1]] = v
    return idx


def load_sheet_rows(info):
    sheet = locate(info["sheet"])
    if not sheet.exists():
        return {}
    with open(sheet, encoding="utf-8") as fh:
        return {int(r["Offset"], 16): r for r in csv.DictReader(fh)}


def load_tagged_rows(containers):
    """the container strings outside the sheets that the injector places
    through config/patch/tagged_rows_en.json, found exactly as inject.py
    finds them (tagged_rows.scan_container over every container; BATTLE /
    BUNKASD are mini-game data).  This used to read
    build/patch/gen/tagged_rows.csv, which only `tagged_rows.py` writes and
    no build step runs: in a fresh tree every one of those rows (229 on
    2026-10-10) counted as "sheet-missing (not in the sheet)" although the
    build had placed its English."""
    import tagged_rows
    out = {}
    for cdrom, info in sorted(containers.items()):
        if cdrom.split("/")[1] in ("BATTLE", "BUNKASD"):
            continue
        rel = "assets/extracted_iso/" + cdrom
        if not locate(rel).exists():
            continue
        sheet_offs = set(load_sheet_rows(info))
        for t in tagged_rows.scan_container(rel, info, sheet_offs):
            out[(cdrom, int(t["Offset"], 16))] = t
    return out


TOKEN_RE = re.compile(r"\{(opt|P|G|p|m|F|Y|S|O|W|A|M)\}")


def load_container_keep():
    """container strings proven never displayed, kept Japanese on purpose:
    the "keep" map of config/patch/tagged_rows_en.json,
    {"<DIR>/<FILE>:<0xoffset of the string>": reason}.  A run inside a kept
    string counts as "kept", not "sheet-missing"; every entry needs its
    evidence."""
    p = PATCH_CONFIG / "tagged_rows_en.json"
    keep = json.loads(p.read_text()).get("keep", {}) if p.exists() else {}
    for k, why in keep.items():
        if not str(why).strip():
            raise SystemExit(f"[text_sources] tagged_rows_en.json keep {k!r} has no reason")
    return keep


def load_draw_sites():
    """string address -> [C file:line] from build/patch/kanji_sites.txt"""
    sites = defaultdict(list)
    p = ROOT / "build/patch/kanji_sites.txt"
    if not p.exists():
        return sites
    names = json.loads((DECOMP / "config/symbol_names.json").read_text())["symbols"]
    by_name = {}
    for k, v in names.items():
        nm = v.get("name")
        if not nm:
            continue
        scope, _, addr = k.rpartition(":")
        by_name[(scope or "main", nm)] = int(addr, 16)
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s*:(\d+)\s+.*str=(?:\(s32\))?([A-Za-z_]\w*)", line)
        if not m:
            continue
        scope, cfile, ln, sym = m.groups()
        a = None
        mm = re.match(r"D_([0-9A-Fa-f]{8})$", sym)
        if mm:
            a = int(mm.group(1), 16)
        elif (scope, sym) in by_name:
            a = by_name[(scope, sym)]
        if a is not None:
            sites[(scope, a)].append(f"{cfile}:{ln}")
    return sites


def load_pointer_refs():
    """(file, offset) -> number of pointer words that reference the string
    (translation/text_pointers.json, main + overlays)"""
    refs = {}
    p = locate("translation/text_pointers.json")
    if not p.exists():
        return refs
    for k, v in json.loads(p.read_text()).get("strings", {}).items():
        f, off = k.rsplit(":", 1)
        f = f.split("extracted_iso/")[1] if "extracted_iso/" in f else "PSX.EXE"
        refs[(f, int(off, 16))] = len(v.get("pointers", []))
    return refs


def load_lba_refs():
    """LBA -> [C file] for every literal cd_read_start / cd_read_start2 call"""
    refs = defaultdict(list)
    pat = re.compile(r"cd_read_start2?\(\s*(?:0x[0-9A-Fa-f]+|\d+)\s*,\s*(?:\([^)]*\))?\s*"
                     r"(?:0x[0-9A-Fa-f]+|\w+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*\)")
    for p in glob.glob(str(DECOMP / "src/main/matched/*.c")) + glob.glob(str(DECOMP / "src/overlay/*/*.c")):
        try:
            txt = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.finditer(txt):
            refs[int(m.group(1), 0)].append(str(Path(p).relative_to(DECOMP)))
    return refs


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

def pointer_words(data: bytes, base: int):
    """offsets inside the file that some aligned word of the file points at"""
    targets = Counter()
    lo, hi = base, base + len(data)
    for i in range(0, len(data) - 3, 4):
        w = struct.unpack_from("<I", data, i)[0]
        if lo <= w < hi:
            targets[w - base] += 1
    return targets


def group_sources(runs, kind_of):
    """runs -> [{kind, offset, end, rows, chars, runs}] by contiguous kind,
    with fixed-stride runs of unreferenced strings split out as records"""
    sources = []
    for r in runs:
        k = kind_of(r)
        if sources and sources[-1]["kind"] == k:
            sources[-1]["runs"].append(r)
        else:
            sources.append({"kind": k, "runs": [r]})
    out = []
    for s in sources:
        rs = s["runs"]
        if s["kind"] == "inline literals" and len(rs) >= 3:
            deltas = Counter(rs[i + 1]["off"] - rs[i]["off"] for i in range(len(rs) - 1))
            d, n = deltas.most_common(1)[0]
            if n >= len(rs) - 1 and 4 <= d <= 64:
                s["kind"] = f"fixed-width records (stride {d})"
        out.append({"kind": s["kind"], "offset": f"0x{rs[0]['off']:X}",
                    "end": f"0x{rs[-1]['off'] + rs[-1]['len']:X}",
                    "rows": len(rs), "chars": sum(r["chars"] for r in rs),
                    "status": dict(Counter(r["status"].split(" (")[0] for r in rs)),
                    "runs": rs})
    return out


def scan_file(rel, data, ctx, min_chars):
    """one file -> record (or None when it holds no text)"""
    runs = sjis_runs(data, min_chars)
    cdrom = rel[len("/"):]                      # CDROM/DIR/FILE or PSX.EXE
    group = cdrom.split("/")[1] if cdrom.startswith("CDROM/") else cdrom
    is_main = cdrom == "PSX.EXE"
    is_exn = cdrom.startswith("CDROM/EXEDIR/") and cdrom.endswith(".EXN")
    ov = Path(cdrom).stem if is_exn else None
    is_nbn = cdrom.upper().endswith(".NBN")
    cont = ctx["containers"].get(cdrom)
    rejected = Counter()
    rows = []
    sheet_rows = load_sheet_rows(cont) if cont else {}
    # a run starts AFTER any leading command letter / tag of its string, so
    # rows are matched by slot interval, not by exact offset
    slot_index = []
    for o, r in sheet_rows.items():
        slot_index.append((o, o + max(int(r["MaxBytes"]), 1) + 1, "sheet", r))
    for (f, o), t in ctx["tagged"].items():
        if f == cdrom:
            slot_index.append((o, o + int(t["MaxBytes"]) + 1, "tagged", t))
    slot_index.sort()
    kept = []                       # (lo, hi, reason): strings kept Japanese
    if cont:
        rel_short = cdrom.split("CDROM/", 1)[-1]
        for k, why in ctx["keep"].items():
            f, _, o = k.rpartition(":")
            if f == rel_short:
                lo = int(o, 16)
                e = data.find(b"\0", lo)
                kept.append((lo, (e if e >= 0 else len(data)) + 1, why))

    def row_at(off):
        for lo, hi, kind, r in slot_index:
            if lo <= off < hi:
                return kind, lo, r
            if lo > off:
                break
        return None, None, None
    cbase = int(cont["base"], 16) if cont else None
    strict = not (cont or is_main or is_exn)
    is_debug_exe = cdrom == "CDROM/EXEDIR/O.BIN"
    ptr_targets = None
    if cont or is_main or is_exn:
        ptr_targets = pointer_words(data, cbase if cont else (0x80041000 if is_main else OV_BASE))
    encoding = "sjis+retail-letters" if (cont or is_main or is_exn) else "sjis"
    accepted = []
    for off, ln, txt in runs:
        ok, why = is_text(txt, strict)
        if not ok and why == "short, not in vocabulary" and (is_exn or is_main) \
                and nul_bounded_label(data, off, ln, txt):
            ok = True          # a place / status label (玄関 廊下 自宅): a C string of its own
        if not ok and cont and group not in ("BATTLE", "BUNKASD") \
                and (ptr_targets.get(off) or (off and ptr_targets.get(off - 1) and data[off - 1] in b">-+<")):
            # a whole string a container's pointer table names is text by
            # construction, whatever the vocabulary test says (URANAI's
            # full-width '*PC NMS_9000*' lines, KOSIEN's long 'woooah...' whoop)
            ok = True
        if not ok:
            rejected[why] += 1
            continue
        accepted.append((off, ln, txt))
    if strict:
        # in data files a short run (2-3 chars) counts only inside a cluster
        # of text (a table), never alone in pixel data
        keep = []
        for i, (off, ln, txt) in enumerate(accepted):
            n = len(JP_RE.findall(txt))
            soft = any(HIRA_RE.match(c) or c in PUNCT for c in txt)
            if n >= 4 and (soft or n >= 8):
                keep.append((off, ln, txt))
                continue
            near = [a for a in accepted[max(0, i - 3):i + 4] if a[0] != off and
                    abs(a[0] - off) <= 48]
            if len(near) >= 1 and (len(near) >= 2 or len(JP_RE.findall(near[0][2])) >= 4):
                keep.append((off, ln, txt))
            else:
                rejected["isolated short run"] += 1
        accepted = keep
    for off, ln, txt in accepted:
        status, note, kind, draw, row_off = "", "", "inline literals", [], None
        if is_debug_exe:
            rows.append({"off": off, "len": ln, "chars": len(JP_RE.findall(txt)),
                         "text": txt[:120], "status": "not-text (debug exe, never loaded)",
                         "note": "", "kind": "debug build", "draw_sites": []})
            continue
        chars = len(JP_RE.findall(txt))
        if is_main:
            addr = MAIN_BASE + off
            draw = ctx["draw"].get(("main", addr), [])
            nref = ctx["ptr_refs"].get((cdrom, off), 0)
            kind = "pointer-table strings" if nref or ptr_targets.get(off - 0x800) else "inline literals"
            if FONT_MAIN[0] <= addr < FONT_MAIN[1]:
                status, kind = "art/font (12x12 glyph block)", "font block"
            elif addr in NOT_TEXT_MAIN:
                status, note, kind = "not-text", NOT_TEXT_MAIN[addr], "undrawn strings"
            elif addr in ctx["cov"]["main"] or addr in ctx["dead_main"]:
                status = ctx["cov"]["main"].get(addr, "injected (relocated via pointer)")
            elif addr < 0x800B5A60:
                status, kind = "not-text (code/table region)", "code"
            else:
                status = "sheet-missing (main exe string)"
        elif is_exn:
            addr = OV_BASE + off
            draw = ctx["draw"].get((ov, addr), [])
            nref = ctx["ptr_refs"].get((cdrom, off), 0)
            kind = "pointer-table strings" if nref or ptr_targets.get(off) else "inline literals"
            m = ctx["cov"]["ov"].get(ov, {})
            if ov in DEAD_OVERLAYS:
                status, kind = "not-text (overlay never loaded)", "dead overlay"
            elif addr in m:
                status = m[addr]
            elif addr in ctx["dead_ov"].get(ov, set()):
                status = "injected (relocated via pointer)"
            else:
                status = "sheet-missing (overlay string)"
        elif cont:
            rkind, roff, r = row_at(off)
            if rkind == "sheet":
                fb = ctx["cov"]["files"].get(cdrom, {}).get("fallback", set())
                kind = "pointer-table strings (sheet rows)"
                if r.get("Status") == "untranslated" or not (r.get("English") or "").strip():
                    status, note = "sheet-missing (row untranslated)", (r.get("Notes") or "")[:60]
                elif r["ID"] in fb:
                    status = "sheet-missing (did not fit)"
                elif cdrom not in ctx["injected_files"]:
                    status = "sheet-missing (container not injected)"
                else:
                    status = "injected"
            elif rkind == "tagged":
                row_off = roff
                t = r
                kind = "tagged rows (speaker prefix)"
                import tagged_rows
                key = tagged_rows.en_key(cdrom, int(t["Offset"], 16))
                en = (ctx["tagged_en"].get(key) or t.get("English") or "").strip()
                fb = ctx["cov"]["files"].get(cdrom, {}).get("fallback", set())
                # the injector's own rules (inject.py Container): no English,
                # a speaker without an English label, a token mismatch or a
                # row that did not fit keep the Japanese
                if not en:
                    status = "sheet-missing (tagged row, no English)"
                elif t.get("Tag") and not ctx["tagged_speakers"].get(t.get("Speaker", "")):
                    status = "sheet-missing (tagged row, speaker has no English label)"
                elif Counter(TOKEN_RE.findall(t["Japanese"])) != Counter(TOKEN_RE.findall(en)):
                    status = "sheet-missing (tagged row, token mismatch)"
                elif t["ID"] in fb:
                    status = "sheet-missing (tagged row, did not fit)"
                elif cdrom not in ctx["injected_files"]:
                    status = "sheet-missing (container not injected)"
                else:
                    status = "injected (tagged row)"
            elif ptr_targets.get(off) or ptr_targets.get(off - 1):
                kind = "pointer-table strings (no sheet row)"
                status = "sheet-missing (not in the sheet)"
            else:
                kind = "inline literals"
                status = "sheet-missing (not a pointer target)"
        elif is_nbn:
            kind = "text table in a sprite file"
            status = ctx["cov"]["files"].get(cdrom, {}).get(off, "sheet-missing (text in NBN)")
        else:
            status = ctx["cov"]["files"].get(cdrom, {}).get(off, "sheet-missing (data file)")
        rkey = f"{cdrom.split('CDROM/', 1)[-1]}:0x{off:x}"
        if status.startswith("sheet-missing") and rkey in reviewed_skips():
            status, note = "not-text (reviewed)", reviewed_skips()[rkey]
        if status.startswith("sheet-missing") and cont:
            for lo, hi, why in kept:
                if lo <= off < hi:
                    status, note = "kept (never displayed)", why[:200]
                    break
        rows.append({"off": off, "len": ln, "chars": chars, "text": txt[:120],
                     "status": status, "note": note, "kind": kind, "draw_sites": draw})
        if row_off is not None:
            rows[-1]["row_off"] = row_off
    if not rows and not rejected:
        return None
    # container-shaped data files that are not in the index: detect the
    # pointer base from the words of the file
    container_hint = None
    if rows and not (cont or is_main or is_exn or is_nbn):
        for base in (0x801E8000, 0x80180000, 0x801A0000, 0x801B0000, 0x801C0000, 0x801F0000):
            t = pointer_words(data, base)
            hits = sum(1 for r in rows if t.get(r["off"]))
            if hits >= max(2, len(rows) // 2):
                container_hint = {"base": f"0x{base:08X}", "pointer_hits": hits}
                for r in rows:
                    if t.get(r["off"]):
                        r["kind"] = "pointer-table strings (no sheet)"
                break
    return {
        "file": cdrom, "group": group, "bytes": len(data), "encoding": encoding,
        "kind": ("main-exe" if is_main else "overlay" if is_exn else "container" if cont
                 else "sprite-sheet" if is_nbn else "data"),
        "container": {"base": cont["base"], "sheet": cont["sheet"]} if cont else container_hint,
        "loaded_by": sorted(set(ctx["lba_refs"].get(ctx["image"].by_path[rel][0], []))),
        "rows": len(rows), "chars": sum(r["chars"] for r in rows),
        "rejected_runs": dict(rejected),
        "status": dict(Counter(r["status"].split(" (")[0] for r in rows)),
        "sources": group_sources(rows, lambda r: r["kind"]),
    }


STATUS_COLS = ("injected", "sheet-missing", "kept", "art/font", "not-text")


def coverage_table(records):
    table = defaultdict(Counter)
    for rec in records:
        for s in rec["sources"]:
            for r in s["runs"]:
                k = r["status"].split(" (")[0]
                table[rec["group"]][k] += 1
                table[rec["group"]]["_c_" + k] += r["chars"]
    lines = []
    hdr = f"{'group':10s} " + " ".join(f"{c:>18s}" for c in STATUS_COLS) + f" {'total':>14s}"
    lines.append(hdr)
    tot = Counter()
    for g in sorted(table):
        t = table[g]
        cells = []
        for k in STATUS_COLS:
            cells.append(f"{t[k]}/{t['_c_' + k]}")
            tot[k] += t[k]
            tot["_c_" + k] += t["_c_" + k]
        n = sum(t[k] for k in STATUS_COLS)
        c = sum(t["_c_" + k] for k in STATUS_COLS)
        lines.append(f"{g:10s} " + " ".join(f"{x:>18s}" for x in cells) + f" {n}/{c}".rjust(15))
    n = sum(tot[k] for k in STATUS_COLS)
    c = sum(tot["_c_" + k] for k in STATUS_COLS)
    lines.append(f"{'TOTAL':10s} " + " ".join(f"{tot[k]}/{tot['_c_' + k]}".rjust(18) for k in STATUS_COLS) + f" {n}/{c}".rjust(15))
    drawn = tot["injected"] + tot["sheet-missing"]
    drawn_c = tot["_c_injected"] + tot["_c_sheet-missing"]
    if drawn:
        lines.append(f"drawn text covered: {tot['injected']}/{drawn} rows "
                     f"({100.0 * tot['injected'] / drawn:.1f} %), "
                     f"{tot['_c_injected']}/{drawn_c} chars "
                     f"({100.0 * tot['_c_injected'] / drawn_c:.1f} %)")
    lines.append(f"visible uncovered (sheet-missing): {tot['sheet-missing']} rows; kept Japanese "
                 f"on purpose (never displayed, tagged_rows_en.json \"keep\"): {tot['kept']} rows")
    return "\n".join(lines)


def visible_uncovered(records):
    """the sheet-missing runs: drawn Japanese that nothing translates and
    no reasoned keep / skip entry explains (build_patched.py fails on any)"""
    return [{"file": rec["file"], "offset": f"0x{r['off']:x}", "status": r["status"],
             "kind": r["kind"], "text": r["text"][:60]}
            for rec in records for s in rec["sources"] for r in s["runs"]
            if r["status"].startswith("sheet-missing")]


def remaining_table(records):
    table = defaultdict(Counter)
    for rec in records:
        for s in rec["sources"]:
            table[rec["group"]]["rows"] += s["rows"]
            table[rec["group"]]["chars"] += s["chars"]
            table[rec["group"]]["files"] += 1
    lines = [f"{'group':10s} {'files':>6s} {'rows':>7s} {'chars':>8s}"]
    tot = Counter()
    for g in sorted(table):
        t = table[g]
        lines.append(f"{g:10s} {t['files']:6d} {t['rows']:7d} {t['chars']:8d}")
        tot.update(t)
    lines.append(f"{'TOTAL':10s} {tot['files']:6d} {tot['rows']:7d} {tot['chars']:8d}")
    return "\n".join(lines)


def write_draft_sheets(records, image):
    """sheet-missing rows -> build/patch/gen/sheets/<DIR>/<FILE>.csv in the
    sheets' column layout (English empty, Status untranslated)"""
    n = 0
    files = 0
    ce = PATCH_CONFIG / "containers_extra.json"
    extra = {k.split("extracted_iso/", 1)[1] for k in json.loads(ce.read_text())} if ce.exists() else set()
    for rec in records:
        # a container with no sheet of its own (containers_extra.json) is
        # injected FROM this draft sheet, so it lists every row whatever the
        # current build placed; elsewhere the rows the sheets lack
        # a run that starts INSIDE a tagged row (after its tag byte and
        # speaker: a container string the injector finds itself, English in
        # config/patch/tagged_rows_en.json) is never a sheet row: listed at
        # its run offset it became a second, overlapping row of the same
        # string (KOSIEN's walkover lines at 0x329.. over the tagged rows at
        # 0x328..).  A run that starts where the string starts (a plain
        # line) stays: for the extra containers it is how the row gets its
        # sheet row, and its English (overlay_drafts by_addr / by_text)
        miss = [r for s in rec["sources"] for r in s["runs"]
                if r.get("row_off", r["off"]) == r["off"] and not r["status"].startswith("kept")
                and (rec["file"] in extra and not r["status"].startswith("not-text")
                     or r["status"].startswith("sheet-missing") or "sheet string" in r["status"])]
        if not miss:
            continue
        rel = rec["file"]
        dst = ROOT / "build" / "patch" / "gen" / "sheets" / (rel.replace("CDROM/", "") + ".csv")
        dst.parent.mkdir(parents=True, exist_ok=True)
        base = int(rec["container"]["base"], 16) if rec.get("container") else None
        data = image.read("/" + rel)
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=["ID", "File", "Offset", "MaxBytes", "PtrSite", "Kind",
                                                "Speaker", "Japanese", "Tokens", "English", "Status", "Notes"])
            wr.writeheader()
            for r in miss:
                sites = ""
                if base is not None:
                    needle = struct.pack("<I", base + r["off"])
                    sites = " ".join(f"0x{i:x}" for i in range(0, len(data) - 3, 4)
                                     if data[i:i + 4] == needle)
                jp = r["text"].replace(" ", "{br}").replace("q", "{opt}")
                try:                    # retail command letters -> {tokens}
                    import tagged_rows
                    jp = tagged_rows.retail_to_sheet(data[r["off"]:r["off"] + r["len"]])
                except (UnicodeDecodeError, ValueError):
                    pass
                if base is not None:
                    import tagged_rows
                    e = data.find(b"\0", r["off"])
                    try:
                        jp = tagged_rows.retail_to_sheet(data[r["off"]:e])
                    except (UnicodeDecodeError, ValueError):
                        pass
                wr.writerow({"ID": f"assets/extracted_iso/{rel}:0x{r['off']:x}",
                             "File": f"assets/extracted_iso/{rel}", "Offset": f"0x{r['off']:x}",
                             "MaxBytes": r["len"], "PtrSite": sites, "Kind": "line",
                             "Speaker": "", "Japanese": jp, "Tokens": "", "English": "",
                             "Status": "untranslated",
                             "Notes": f"DRAFT sheet generated by text_sources.py; {r['status']}; "
                                      f"{r['kind']}; {r['note']}"})
                n += 1
        files += 1
    return n, files


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="config/patch/english.json")
    ap.add_argument("--image", default=str(TRACK1), help="Track 1 .bin to scan")
    ap.add_argument("--out", default="build/patch/text_sources.json")
    ap.add_argument("--draft-sheets", action="store_true")
    ap.add_argument("--remaining", action="store_true",
                    help="report the Japanese left on the image (for a patched disc)")
    ap.add_argument("--min-chars", type=int, default=2)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--fail-on-visible", action="store_true",
                    help="exit 3 when a drawn Japanese row has no English and no keep / "
                         "skip reason (build_patched.py passes it)")
    ap.add_argument("--kanji-subset", default="build/patch/gen/kanji_subset.json",
                    help="the drawable-code list build_patched.py wrote for this profile")
    ap.add_argument("--report", default="build/patch/english.report.json",
                    help="the build report (which containers were injected)")
    a = ap.parse_args()
    image = Image(Path(a.image))
    cov, prof = load_profile_coverage(a.profile, with_sheets=not a.draft_sheets)
    ten = PATCH_CONFIG / "tagged_rows_en.json"
    tdoc = json.loads(ten.read_text()) if ten.exists() else {}
    containers = load_container_index()
    ctx = {"image": image, "cov": cov, "containers": containers,
           "tagged_en": tdoc.get("rows", {}), "tagged_speakers": tdoc.get("speakers", {}),
           "keep": load_container_keep(),
           "tagged": load_tagged_rows(containers), "draw": load_draw_sites(),
           "ptr_refs": load_pointer_refs(), "lba_refs": load_lba_refs(),
           "dead_main": set(), "dead_ov": defaultdict(set),
           "injected_files": set(json.loads(locate(a.report).read_text())
                                 .get("containers", {}).get("files", []))
           if locate(a.report).exists() else set()}
    # strings whose pointer word was redirected: their old slot is dead
    main_exe = image.read("/PSX.EXE")
    for site, how in cov["main"].items():
        if "relocated" in how:
            ctx["dead_main"].add(struct.unpack_from("<I", main_exe, site - MAIN_BASE)[0])
    for ov, m in cov["ov"].items():
        p = f"/CDROM/EXEDIR/{ov}.EXN"
        if p in image.by_path:
            exn = image.read(p)
            for site, how in m.items():
                if "relocated" in how and 0 <= site - OV_BASE < len(exn) - 3:
                    ctx["dead_ov"][ov].add(struct.unpack_from("<I", exn, site - OV_BASE)[0])
    records = []
    skipped = []
    for lba, n, size, path in image.files:
        up = path.upper()
        if up.endswith((".STR", ".DA", ".XA")) or "/XA_G/" in up:
            skipped.append(path)
            continue
        data = image.read(path)
        rec = scan_file(path, data, ctx, a.min_chars)
        if rec:
            rec["lba"] = f"0x{lba:X}"
            records.append(rec)
    # unallocated sectors
    unalloc = []
    for s, e in image.unallocated():
        data = b"".join(image.sector(k) for k in range(s, e + 1))
        runs = [r for r in sjis_runs(data, a.min_chars) if is_text(r[2])[0]]
        unalloc.append({"first_lba": f"0x{s:X}", "sectors": e - s + 1,
                        "nonzero": bool(any(data)), "text_runs": len(runs),
                        "sample": [r[2][:40] for r in runs[:3]]})
    # Japanese that stays on the disc and uses a glyph the patched renderer
    # cannot draw (build/patch/gen/kanji_subset.json from build_patched.py)
    dropped = []
    ks = locate(a.kanji_subset)
    if ks.exists() and not a.remaining:
        drawable = set(json.loads(ks.read_text())["drawable_codes"])
        for rec in records:
            for src in rec["sources"]:
                for r in src["runs"]:
                    st = r["status"]
                    if st.startswith(("injected", "not-text", "art", "kept")):
                        continue
                    bad = sorted({c for c in r["text"] if JP_RE.match(c) and
                                  int.from_bytes(c.encode("shift_jis", "replace")[:2], "big") not in drawable
                                  and len(c.encode("shift_jis", "replace")) == 2})
                    if bad:
                        r["dropped_glyphs"] = "".join(bad)
                        dropped.append((rec["file"], r["off"], "".join(bad), r["text"][:40]))
    out = locate(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    vis = [] if a.remaining else visible_uncovered(records)
    doc = {"image": str(Path(a.image)), "sectors": image.sectors, "files": len(image.files),
           "skipped_streams": len(skipped), "unallocated": unalloc,
           "visible_uncovered": vis,
           "lba_refs_unmapped": sorted(f"0x{l:X}" for l in ctx["lba_refs"] if l not in image.by_lba),
           "records": records}
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    if a.remaining:
        print(f"JAPANESE REMAINING on {Path(a.image).name} (text runs of >= {a.min_chars} chars)")
        print(remaining_table(records))
    else:
        print(f"COVERAGE of the Japanese text on the disc (text runs of >= {a.min_chars} chars; rows/chars)")
        print(coverage_table(records))
    doc["dropped_glyph_runs"] = [{"file": f, "offset": f"0x{o:X}", "glyphs": g, "text": t}
                                 for f, o, g, t in dropped]
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    if ks.exists() and not a.remaining:
        by_file = Counter(f for f, _, _, _ in dropped)
        print(f"Japanese still drawn with a DROPPED glyph (box placeholder): {len(dropped)} runs"
              + (": " + ", ".join(f"{Path(f).name} {n}" for f, n in by_file.most_common(8)) if dropped else ""))
    hidden = [u for u in unalloc if u["text_runs"]]
    print(f"unallocated sectors: {sum(u['sectors'] for u in unalloc)} in {len(unalloc)} ranges, "
          f"{len(hidden)} with text; literal LBAs outside the file tree: {len(doc['lba_refs_unmapped'])}")
    print(f"-> {out.relative_to(ROOT)}")
    if a.draft_sheets:
        n, files = write_draft_sheets(records, image)
        print(f"draft sheets: {n} rows in {files} files under build/patch/gen/sheets/")
    if a.fail_on_visible and vis:
        for v in vis[:20]:
            print(f"VISIBLE UNCOVERED: {v['file']}:{v['offset']} {v['status']} {v['text']}")
        print(f"{len(vis)} drawn Japanese rows have no English: give each a DRAFT "
              f"(tagged rows: config/patch/tagged_rows_en.json; sheet rows: the sheet / "
              f"choice_overrides.json; overlay / exe / data strings: overlay_drafts.d) or, "
              f"with the evidence that it is never displayed, a \"keep\" entry")
        sys.exit(3)


if __name__ == "__main__":
    main()
