#!/usr/bin/env python3
"""inject.py - sheet -> script-container injector for the PS1 English patch.

Reads the cloud agent's sheets (translation/localization/sheets/<DIR>/<FILE>.csv,
READ ONLY) and rewrites COPIES of the script containers under
build/patch/files/CDROM/... so that every file keeps its exact size (and so
its sector count: the loader addresses every file by LBA, see
docs/translation/PS1-PATCH-FEASIBILITY.md section 3.1).

What a container looks like (measured; tools/translation/extract_containers.py
is the extractor whose sheets this consumes):

  * the file is DMA'd whole to a fixed RAM base; every string is NUL
    terminated Shift-JIS, 4-byte aligned, zero padded to the next word, and
    referenced by exactly one absolute pointer word inside the same file;
  * strings and script nodes are INTERLEAVED (a node is a few pointer words
    followed by its text), there is NO free tail (the last byte of every
    file is non-zero) and the "zero runs" are node fields, not padding.  So
    the only writable bytes are the string slots themselves:
    [offset, offset + ceil4(len + 1)).  Adjacent slots merge into one region.
  * pointer targets that are not sheet rows (script nodes, and a few strings
    the extractor skipped because they carry the event dispatcher's letter
    tags '>' '-' '+' '<' or a trailing "nn") are IMMUTABLE here: never
    moved, never overwritten.  The patched parsers convert such legacy
    strings at run time (src/patch/main/text_event.c).

What it does per container:

  1. rows whose Status is accepted (default: everything but `untranslated`)
     and whose English carries every token of the Japanese are TRANSLATED;
     the rest keep their retail bytes in place (legacy mode at run time);
  2. the English is normalised (curly quotes, ellipsis, dashes -> ASCII),
     pre-fitted to the window that draws it (event window: 201 px rows,
     x = -72 .. 129, authored {br} kept when every line fits, else reflowed;
     choices: one row each, {br} removed, over-wide replies reported) and
     encoded with tools/patch/textcodec.py: control bytes < 0x20 for the
     tokens, ASCII, and DTE codes 0xA0..0xDF / 0xF0..0xFE;
  3. the DTE dictionary (80 entries) is built from the whole English corpus
     of the run (greedy by bytes saved, re-encoding between passes) and
     written to build/patch/gen/dte.json; build_patched.py places the
     strings in the string pool and fills patch_dte_table[] so the renderer
     and the parsers expand them;
  4. the translated rows are packed into the merged free regions
     (best-fit decreasing); a row that does not fit falls back to its
     retail bytes in place (its slot returns to the immutable set and the
     file is re-packed until stable); every pointer word of a moved string
     is rewritten to base + new offset;
  5. a report (build/patch/inject.report.json + a summary on stdout) lists
     per container: capacity, demand raw / with DTE, rows translated /
     placed / fallen back, bytes of overflow, over-wide choices, and the
     totals before and after DTE.

Usage:
    python3 tools/patch/inject.py                       # SERIFU + SPEAKTST
    python3 tools/patch/inject.py --dirs SERIFU         # one directory
    python3 tools/patch/inject.py --only SERIFU/G_APPEAR SERIFU/G_BIRTH
    python3 tools/patch/inject.py --no-dte              # measure raw fit
    python3 tools/patch/inject.py --dte build/patch/gen/dte.json  # reuse a table

BUNKA (culture-festival club visits), MASTER (club finals), TAIIKU (sports
day) and SHIAI (practice matches) use the SAME container format and are
drawn by the MAIN event dispatcher (the overlays call serifu_run; verified
in game on 2026-10-09 with the forced BUNKASAI scene), so they are injected
exactly like SERIFU.  BATTLE and BUNKASD are NOT text: their three "rows"
each are runs of repeated byte pairs inside mini-game data that the pointer
scan misread (the editor's note in those sheets); they are refused here.
"""
import argparse
import csv
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, CONTAINERS, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import locate                          # noqa: E402
import textcodec                                      # noqa: E402
import tagged_rows                                    # noqa: E402
import retail_text                                    # noqa: E402

OUT_FILES = ROOT / "build" / "patch" / "files"
OUT_GEN = ROOT / "build" / "patch" / "gen"

DEFAULT_DIRS = ["SERIFU", "SPEAKTST", "BUNKA", "MASTER", "TAIIKU", "SHIAI", "TARA_OBJ"]
BINARY_DIRS = ["BATTLE", "BUNKASD"]      # mini-game data, not text: refused
ACCEPT_STATUS = ("draft", "translated", "edited", "qa", "final")

TOKEN_RE = re.compile(r"\{(br|opt|P|G|p|m|F|Y|S|O|W|A|M)\}")
TOKEN_SPLIT_RE = re.compile(r"\{(?:br|opt|P|G|p|m|F|Y|S|O|W|A|M)\}")

# event window geometry (docs/translation/TEXT-DRAW-INVENTORY.md section 2):
# body rows at x = -72, text area ends at 129 -> 201 px; choice rows start
# at the retail bullet column x = -128 (plain layout, no brackets) -> 257 px
LINE_PX = 201
CHOICE_PX = 129 + 128
CHOICE_ROWS_PER_REPLY = 2       # text_msg.c wraps a reply onto a second row
CHOICE_ROWS_PER_MENU = 3        # 48-px box: 3 rows at the retail 16-px pitch
CHOICE_EDITS = PATCH_CONFIG / "choice_edits.json"   # ID -> English
# DRAFT shortened replies that make a menu fit the retail box (and the odd
# container line that does not fit its region), keyed by
# "<DIR>/<FILE>:<0xoffset>" (the container and the row's offset); the sheet
# text is untouched, the build applies them (tools/patch/choice_check.py)
CHOICE_OVERRIDES = PATCH_CONFIG / "choice_overrides.json"


def choice_key(row_id: str) -> str:
    """sheet ID 'assets/extracted_iso/CDROM/SERIFU/X.BIN:0xe70' -> 'SERIFU/X.BIN:0xe70'"""
    rel, _, off = row_id.rpartition(":")
    rel = rel.split("CDROM/", 1)[-1]
    return f"{rel}:0x{int(off, 16):x}"
TAGGED_EN = PATCH_CONFIG / "tagged_rows_en.json"     # DIR/FILE:0xoff -> English
TAG_BYTES = {">": 0x10, "-": 0x11, "+": 0x12, "<": 0x13}         # text_event.c PT_C_TAG_*
TAG_SEP = 0x1F
TAG_NOSHOW = 0x0E
LABEL_PX_MAX = 44                # text_event.c PT_LABEL_BUDGET: the retail name column

# run-time token expansions are names; estimate their width for pre-fitting
# (the renderer wraps again at run time with the real string, so this only
# decides where the injector's own breaks go)
TOKEN_PX = {"{P}": 48, "{G}": 42, "{p}": 48, "{m}": 48, "{F}": 90, "{Y}": 36,
            "{S}": 40, "{O}": 40, "{W}": 40, "{A}": 40, "{M}": 40}

NORMALISE = {
    "…": "...", "’": "'", "‘": "'", "“": '"',
    "”": '"', "—": "-", "–": "-", "‐": "-",
    "　": " ", " ": " ",
}


def ceil4(n):
    return (n + 3) & ~3


def normalise(text: str) -> str:
    for a, b in NORMALISE.items():
        text = text.replace(a, b)
    return text


def tokens_of(text: str):
    """the tokens that must survive translation ({br} may be added or
    dropped freely, WORKFLOW.md section 2; {opt} and the name/number tokens
    must keep their count)"""
    return Counter(t for t in TOKEN_RE.findall(text) if t != "br")


def line_width(line: str) -> int:
    """pixel width of one authored line with token estimates"""
    w = 0
    pos = 0
    for m in TOKEN_RE.finditer(line):
        w += textcodec.width(line[pos:m.start()])
        w += TOKEN_PX.get(m.group(0), 0)
        pos = m.end()
    w += textcodec.width(line[pos:])
    return w


def wrap_segment(seg: str, max_px: int) -> str:
    """greedy word wrap of a segment that may hold tokens; returns {br}-joined"""
    words = seg.split(" ")
    lines = []
    cur = ""
    for wd in words:
        if wd == "":
            continue
        cand = wd if not cur else cur + " " + wd
        if line_width(cand) <= max_px or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return "{br}".join(lines)


def fit_text(text: str, kind: str, stats: dict):
    """pre-fit one row's English to its window; returns (text, notes)"""
    notes = []
    segs = text.split("{opt}")
    out = []
    if kind == "choice":
        # plain layout (text_msg.c PT_CHOICE_PLAIN): no brackets, 257-px
        # rows; the engine wraps a wider reply onto a second row and the
        # hooked menu2_init/menu3_init size the hit box to it.  The message
        # box has 48 px: three 16-px rows, or FOUR rows at the 12-px pitch
        # the engine switches to when the menu needs them.  So a reply may
        # take two rows and a menu four rows in all; anything wider is
        # over-wide: it needs a shorter English (config/patch/choice_edits.json
        # or the editor) and the build refuses it (see run()).
        replies = [re.sub(r" +", " ", s.replace("{br}", " ")).strip() for s in segs]
        rows = []
        for seg in replies:
            w = line_width(seg)
            rows.append(1 if w <= CHOICE_PX else
                        len(wrap_segment(seg, CHOICE_PX).split("{br}")))
        # the retail box: three rows at the 16-px pitch (a menu with more
        # replies than that gets one row each); a reply may wrap onto a
        # second row only while the whole menu still fits three rows, i.e.
        # in a menu of one or two replies (config/patch/choice_overrides.json
        # holds the DRAFT shortenings that make every menu fit)
        per_menu = max(CHOICE_ROWS_PER_MENU, len(rows))
        per_reply = CHOICE_ROWS_PER_REPLY if len(rows) <= 2 else 1
        over = [i for i, r in enumerate(rows) if r > per_reply]
        if sum(rows) > per_menu:
            over += [i for i, r in enumerate(rows) if r > 1 and i not in over]
        for i in sorted(set(over)):
            notes.append(f"choice {i + 1}: {line_width(replies[i])}px > {CHOICE_PX}"
                         f" ({rows[i]} rows; menu has {len(replies)} replies, "
                         f"{sum(rows)} rows)")
            stats["choice_too_wide"] += 1
        if not over:
            if sum(rows) > 3:
                stats["choice_four_rows"] += 1       # a 4-reply menu, one row each
            elif sum(rows) > len(rows):
                stats["choice_two_rows"] += 1
        return "{opt}".join(replies), notes
    for seg in segs:
        seg = seg.strip()
        lines = [ln.strip() for ln in seg.split("{br}")]
        if all(line_width(ln) <= LINE_PX for ln in lines):
            out.append("{br}".join(lines))
            continue
        stats["reflowed"] += 1
        out.append(wrap_segment(" ".join(lines), LINE_PX))
    return "{opt}".join(out), notes


# ---------------------------------------------------------------------------
# DTE dictionary
# ---------------------------------------------------------------------------

def ascii_runs(text: str):
    """the ASCII runs of an encoded-to-be string (tokens and Japanese split
    them; DTE entries never cross those boundaries)"""
    return [r for r in TOKEN_SPLIT_RE.split(text) if r]


def build_dte(corpus_texts, count=textcodec.DTE_COUNT, min_len=2, max_len=8,
              per_pass=8, verbose=False):
    """Greedy dictionary: repeatedly take the substring with the largest
    (len-1) * occurrences over the corpus as it would be encoded with the
    entries chosen so far (chosen entries are replaced by private
    placeholder characters between passes, so later picks never overlap
    them).  Returns the list of entries (longest first is NOT required; the
    encoder matches longest-first itself)."""
    runs = []
    for t in corpus_texts:
        for r in ascii_runs(t):
            if any(not (0x20 <= ord(c) <= 0x7E) for c in r):
                continue
            runs.append(r)
    chosen = []
    text = "\x00".join(runs)
    while len(chosen) < count:
        cnt = Counter()
        n = len(text)
        for L in range(min_len, max_len + 1):
            for i in range(n - L + 1):
                s = text[i:i + L]
                if "\x00" in s or any(ord(c) > 0x7E for c in s):
                    continue
                cnt[s] += 1
        best = sorted(((c * (len(s) - 1), s) for s, c in cnt.items() if c > 1),
                      reverse=True)
        picked = []
        for save, s in best:
            if len(picked) >= per_pass or len(chosen) + len(picked) >= count:
                break
            if any(s in p or p in s for p in picked):
                continue
            picked.append(s)
        if not picked:
            break
        for s in picked:
            k = len(chosen)
            chosen.append(s)
            text = text.replace(s, chr(0x100 + k))
            if verbose:
                print(f"  dte[{k:2d}] {s!r}")
    return chosen


# ---------------------------------------------------------------------------
# containers
# ---------------------------------------------------------------------------

class Row:
    __slots__ = ("id", "off", "maxbytes", "sites", "kind", "jp", "en", "status",
                 "raw", "slot", "enc", "new_off", "translated", "notes", "text",
                 "tag", "speaker", "speaker_en")

    def __init__(self, r):
        self.id = r["ID"]
        self.off = int(r["Offset"], 16)
        self.maxbytes = int(r["MaxBytes"])
        self.sites = [int(s, 16) for s in r["PtrSite"].split()]
        self.jp = r["Japanese"]
        # a choice with {br} is not a menu: the event picks ONE of these
        # alternatives (case 2/5, text_event.c pt_nth_segment) and draws it
        # as a message body (wrapped at 201 px, scrolled like any message);
        # a menu reply is one authored row
        self.kind = row_kind(r["Kind"], TOKEN_RE.findall(self.jp))
        self.en = r.get("English", "") or ""
        self.status = r.get("Status", "untranslated")
        self.raw = b""
        self.slot = 0
        self.enc = None
        self.new_off = None
        self.translated = False
        self.notes = []
        self.text = ""
        self.tag = r.get("Tag", "") or ""
        self.speaker = r.get("Speaker", "") or ""
        self.speaker_en = ""


CHOICE_EDITS_CACHE = {}
TAGGED_CACHE = {}


def row_kind(kind: str, tokens) -> str:
    """the kind the injector fits a row as: a `choice` whose Japanese has
    {br} is not a menu but `alternatives` (Row.__init__); `tokens` are the
    Japanese's tokens (the sheet's Tokens column, or the Japanese itself)"""
    return "alternatives" if kind == "choice" and "br" in tokens else kind


def edited_english(row_id: str, kind: str, en: str):
    """(English, from_override) the build uses for a sheet row instead of
    its own English, or (None, False): a DRAFT shortened reply of
    config/patch/choice_overrides.json, else config/patch/choice_edits.json
    by ID, else (a menu choice) by its fitted English.  Reads only the
    English, so the disc-free lint (lint_sheets.py) shares it."""
    if "rows" not in CHOICE_EDITS_CACHE:
        e = json.loads(CHOICE_EDITS.read_text()) if CHOICE_EDITS.exists() else {}
        CHOICE_EDITS_CACHE["rows"] = e.get("by_id", {})
        CHOICE_EDITS_CACHE["text"] = e.get("by_text", {})
    if "over" not in CHOICE_EDITS_CACHE:
        o = json.loads(CHOICE_OVERRIDES.read_text()) if CHOICE_OVERRIDES.exists() else {}
        CHOICE_EDITS_CACHE["over"] = o.get("rows", {})
    ov = CHOICE_EDITS_CACHE["over"].get(choice_key(row_id))
    new = ov or CHOICE_EDITS_CACHE["rows"].get(row_id)
    if not new and kind == "choice" and en.strip():
        # keyed by the FITTED English (as wide_choices.csv lists it)
        fitted, _ = fit_text(normalise(en.strip()), kind, Counter())
        new = CHOICE_EDITS_CACHE["text"].get(fitted) or \
            CHOICE_EDITS_CACHE["text"].get(en.strip())
    return (new or None), bool(ov)


class Container:
    def __init__(self, rel: str, info: dict, accept, trust_maxbytes=False):
        self.rel = rel                      # assets/extracted_iso/CDROM/...
        self.cdrom = rel.split("extracted_iso/")[1]      # CDROM/DIR/FILE.BIN
        self.base = int(info["base"], 16)
        self.data = bytearray(locate(rel).read_bytes())
        self.size = len(self.data)
        self.rows = [Row(r) for r in retail_text.read_sheet(locate(info["sheet"]))]
        self.stats = Counter()
        self.report = {}
        # the pointer-target strings the sheet skipped (speaker-prefixed
        # case-7 lines and a few plain lines): tagged_rows.py finds them,
        # config/patch/tagged_rows_en.json carries their English
        if "rows" not in TAGGED_CACHE:
            t = json.loads(TAGGED_EN.read_text()) if TAGGED_EN.exists() else {}
            TAGGED_CACHE["rows"] = t.get("rows", {})
            TAGGED_CACHE["speakers"] = t.get("speakers", {})
        sheet_offs = {r.off for r in self.rows}
        for t in tagged_rows.scan_container(rel, info, sheet_offs):
            key = tagged_rows.en_key(rel, int(t["Offset"], 16))
            en = TAGGED_CACHE["rows"].get(key, "")
            t["English"] = en
            t["Status"] = "draft" if en else "untranslated"
            row = Row(t)
            row.kind = "line"
            if row.tag:
                row.speaker_en = TAGGED_CACHE["speakers"].get(row.speaker, "")
                if not row.speaker_en:
                    row.notes.append(f"speaker {row.speaker!r} has no English: kept Japanese")
                    row.en = ""
                elif textcodec.width(row.speaker_en) > LABEL_PX_MAX:
                    self.stats["label_over_budget"] += 1
                    row.notes.append(f"speaker label {row.speaker_en!r} is "
                                     f"{textcodec.width(row.speaker_en)} px > {LABEL_PX_MAX}")
            self.rows.append(row)
            self.stats["tagged_rows"] += 1
        for row in self.rows:
            new, ov = edited_english(row.id, row.kind, row.en)
            if ov:
                row.notes.append("DRAFT shortened reply from config/patch/choice_overrides.json")
            if new:
                row.en = new
                if not ov:
                    row.notes.append("English from config/patch/choice_edits.json")
            e = self.data.find(b"\0", row.off)
            row.raw = bytes(self.data[row.off:e])
            if trust_maxbytes:
                row.slot = row.maxbytes + 1
            else:
                row.slot = ceil4(len(row.raw) + 1)
            # sanity: every pointer site must hold base + offset
            for s in row.sites:
                w = struct.unpack_from("<I", self.data, s)[0]
                if w != self.base + row.off:
                    raise SystemExit(f"[inject] {self.cdrom} {row.id}: pointer "
                                     f"site 0x{s:X} holds 0x{w:08X}, expected "
                                     f"0x{self.base + row.off:08X}")
            # a real string slot is NUL-terminated and zero-padded to the
            # word; the extractor also lists a few script-node words whose
            # low byte happens to be a token letter (e.g. 0x801A0020 reads as
            # " " = {br}).  Those, 1-byte strings and rows whose English is
            # the Japanese (token-only rows) stay immutable.
            pad = bytes(self.data[row.off + len(row.raw) + 1:row.off + row.slot])
            en = row.en.strip()
            if len(row.raw) < 2 or any(pad) or en == row.jp:
                self.stats["immutable_rows"] += 1
                continue
            # translated?
            if en and row.status in accept and tokens_of(row.jp) == tokens_of(en):
                row.translated = True
            elif en and row.status in accept:
                row.notes.append("token mismatch: kept Japanese")
                self.stats["token_mismatch"] += 1

    def prepare(self, dte, stats_global):
        """normalise, fit and encode every translated row"""
        for row in self.rows:
            if not row.translated:
                continue
            en = row.en.strip()
            noshow = False
            if row.tag or row.id.endswith(f":{row.off:#x}") and row.jp.endswith("nn"):
                # retail skip marker "nn" (the dispatcher's case 0/1/2/12/13
                # test): becomes PT_C_NOSHOW at the end of the message
                if en.endswith("nn") and row.jp.endswith("nn"):
                    en = en[:-2]
                    noshow = True
            text, notes = fit_text(normalise(en), row.kind, self.stats)
            row.notes += notes
            row.text = text
            try:
                row.enc = textcodec.encode(text, dte)
                if noshow:
                    row.enc += bytes([TAG_NOSHOW])
                if row.tag:
                    row.enc = (bytes([TAG_BYTES[row.tag]]) + row.speaker_en.encode("ascii")
                               + bytes([TAG_SEP]) + row.enc)
                row.enc += b"\0"
            except ValueError as e:
                row.notes.append(f"unencodable: {e}")
                row.translated = False
                self.stats["unencodable"] += 1
                continue
            # legacy-mode guard: an English string with no control byte, no
            # ASCII letter other than the 13 retail letters and a Japanese
            # pair would be mistaken for retail text; prefix a NOP (0x1E)
            if not any(b < 0x20 for b in row.enc[:-1]) and \
                    any(textcodec.is_sjis_lead(b) for b in row.enc) and \
                    all(chr(b) in " qPGpmFYSOWAM" for b in row.enc[:-1] if b < 0x80):
                row.enc = b"\x1e" + row.enc

    def pack(self):
        """Place the translated rows.

        A region is a run of adjacent slots of translated rows (the script
        nodes between runs are immutable, so regions are small: one to a few
        strings).  Pass 1 is LOCAL: each region keeps its own rows, packed
        back to back from its start; while they do not fit, the row with the
        largest growth (English bytes - retail slot) reverts to its retail
        bytes IN PLACE, which splits the region into two sub-regions that are
        handled the same way.  Pass 2 is GLOBAL: rows that reverted in pass 1
        are offered, largest first, the leftover space of every region
        (best fit); a row placed that way leaves its retail slot (zeroed).
        What remains reverted stays Japanese and is reported.  No cascade:
        a reverted row never disturbs a placed one."""
        movable = [r for r in self.rows if r.translated]
        regions = self._regions(movable)
        self._zero_ranges = []
        self._free = []                       # [cursor, end] leftovers
        by_off = {r.off: r for r in movable}
        for s, e in regions:
            rows = [by_off[o] for o in sorted(o for o in by_off if s <= o < e)]
            self._pack_local(rows, s, e)
        # pass 2: global best fit of the reverted rows into the leftovers
        reverted = [r for r in movable if not r.translated and r.enc is not None]
        for r in sorted(reverted, key=lambda r: -len(r.enc)):
            n = len(r.enc)
            best = None
            for gap in self._free:
                room = gap[1] - gap[0]
                if room >= n and (best is None or room < best[1] - best[0]):
                    best = gap
            if best is None:
                continue
            r.new_off = best[0]
            best[0] += n
            r.translated = True
            r.notes = [x for x in r.notes if not x.startswith("does not fit")]
            r.notes.append("placed in another region's leftover")
            self._zero_ranges.append((r.off, r.off + r.slot))
            self.stats["no_fit"] -= 1
            self.stats["no_fit_bytes"] -= n
        self._regions_final = regions
        return [r for r in movable if r.translated]

    def _pack_local(self, rows, s, e):
        """rows (offset order) into [s, e); reverts the worst-growing row in
        place and recurses on both sides when they do not fit"""
        if not rows:
            if e > s:
                self._free.append([s, e])
            return
        need = sum(len(r.enc) for r in rows)
        if need <= e - s:
            cur = s
            for r in rows:
                r.new_off = cur
                cur += len(r.enc)
            self._zero_ranges.append((s, e))
            self._free.append([cur, e])
            return
        worst = max(rows, key=lambda r: len(r.enc) - r.slot)
        worst.translated = False
        worst.notes.append(f"does not fit ({len(worst.enc)} B in a "
                           f"{e - s}-byte region); kept Japanese")
        self.stats["no_fit"] += 1
        self.stats["no_fit_bytes"] += len(worst.enc)
        i = rows.index(worst)
        self._pack_local(rows[:i], s, worst.off)
        self._pack_local(rows[i + 1:], worst.off + worst.slot, e)

    def _regions(self, movable):
        slots = sorted((r.off, r.off + r.slot) for r in movable)
        regions = []
        for s, e in slots:
            if regions and s <= regions[-1][1]:
                regions[-1][1] = max(regions[-1][1], e)
            else:
                regions.append([s, e])
        return regions

    def write(self, out_dir: Path):
        """zero the rewritten ranges, write the placed strings, rewrite the
        pointers"""
        placed = [r for r in self.rows if r.translated]
        for s, e in self._zero_ranges:
            self.data[s:e] = b"\0" * (e - s)
        for r in placed:
            n = len(r.enc)
            if any(self.data[r.new_off:r.new_off + n]):
                raise SystemExit(f"[inject] {self.cdrom} {r.id}: destination "
                                 f"0x{r.new_off:X}+{n} not free: "
                                 f"{bytes(self.data[r.new_off:r.new_off + n]).hex()} "
                                 f"notes={r.notes}")
            self.data[r.new_off:r.new_off + n] = r.enc
            for site in r.sites:
                struct.pack_into("<I", self.data, site, self.base + r.new_off)
        assert len(self.data) == self.size
        out = out_dir / self.cdrom
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes(self.data))
        return out

    def verify(self):
        """every placed string reads back; every immutable row untouched"""
        for r in self.rows:
            if r.translated:
                e = self.data.find(b"\0", r.new_off)
                assert bytes(self.data[r.new_off:e]) == r.enc[:-1], r.id
                for site in r.sites:
                    assert struct.unpack_from("<I", self.data, site)[0] == \
                        self.base + r.new_off
            else:
                e = self.data.find(b"\0", r.off)
                assert bytes(self.data[r.off:e]) == r.raw, (r.id, "immutable row changed")

    def summary(self, dte):
        rows = self.rows
        cap = sum(r.slot for r in rows)
        trans = [r for r in rows if r.enc is not None]
        raw_demand = sum(len(textcodec.encode(r.text)) + 1 for r in trans)
        dte_demand = sum(len(r.enc) for r in rows if r.enc is not None)
        placed = [r for r in rows if r.translated]
        rep = {
            "file": self.cdrom, "size": self.size, "base": f"0x{self.base:08X}",
            "rows": len(rows), "rows_with_english": len(trans),
            "capacity_bytes": cap,
            "demand_raw_bytes": raw_demand,
            "demand_dte_bytes": dte_demand,
            "dte_saving_pct": round(100.0 * (1 - dte_demand / raw_demand), 1) if raw_demand else 0,
            "rows_placed": len(placed),
            "rows_fallback": len(trans) - len(placed),
            "fallback_bytes": self.stats["no_fit_bytes"],
            "token_mismatch": self.stats["token_mismatch"],
            "reflowed": self.stats["reflowed"],
            "choice_too_wide": self.stats["choice_too_wide"],
            "choice_two_rows": self.stats["choice_two_rows"],
            "choice_four_rows": self.stats["choice_four_rows"],
            "tagged_rows": self.stats["tagged_rows"],
            "label_over_budget": self.stats["label_over_budget"],
            "fallback_rows": [{"id": r.id, "bytes": len(r.enc), "note": "; ".join(r.notes)}
                              for r in rows if r.enc is not None and not r.translated],
            # the Japanese that stays on the disc (untranslated, mismatched or
            # fallen back): the kanji-subset builder counts its glyphs
            "japanese_left": [r.jp for r in rows if not r.translated and len(r.raw) >= 2],
            "wide_choices": [{"id": r.id, "text": r.text, "note": "; ".join(r.notes)}
                             for r in rows if r.notes and any(n.startswith("choice ") for n in r.notes)],
        }
        self.report = rep
        return rep


# ---------------------------------------------------------------------------

CONTAINERS_EXTRA = PATCH_CONFIG / "containers_extra.json"


def load_containers(dirs, only, accept, trust_maxbytes):
    index = json.loads(CONTAINERS.read_text())
    # the patch's own containers (no sheet in translation/): their sheets
    # are generated under build/ by tools/patch/overlay_sheets.py --containers
    if CONTAINERS_EXTRA.exists():
        for rel, info in json.loads(CONTAINERS_EXTRA.read_text()).items():
            if locate(info["sheet"]).exists():
                index[rel] = info
            else:
                print(f"[inject] {rel}: sheet {info['sheet']} missing (run "
                      f"overlay_sheets.py --containers); skipped")
    out = []
    for rel, info in sorted(index.items()):
        cdrom = rel.split("extracted_iso/CDROM/")[1]
        d = cdrom.split("/")[0]
        stem = cdrom.rsplit(".", 1)[0]
        if only:
            if stem not in only and cdrom not in only:
                continue
        elif d not in dirs:
            continue
        if d in BINARY_DIRS:
            raise SystemExit(f"[inject] {cdrom}: {d} containers are mini-game "
                             f"data, not text (see the sheet notes); not injectable")
        out.append(Container(rel, info, accept, trust_maxbytes))
    return out


def run(dirs=None, only=None, dte_path=None, no_dte=False, accept=ACCEPT_STATUS,
        out_dir=OUT_FILES, gen_dir=OUT_GEN, trust_maxbytes=False, verbose=False,
        dte_count=textcodec.DTE_COUNT, wide_choices="fail"):
    """Inject; returns (files{cdrom_rel: out_path}, dte_entries, report).
    wide_choices: "fail" refuses a build with a reply the box cannot show
    (list in build/patch/gen/wide_choices.csv), "warn" only reports."""
    dirs = dirs or DEFAULT_DIRS
    conts = load_containers(dirs, set(only or []), set(accept), trust_maxbytes)
    if not conts:
        raise SystemExit("[inject] no containers selected")
    # DTE
    dte = []
    if not no_dte:
        if dte_path:
            dte = json.loads(Path(dte_path).read_text())["entries"]
        else:
            corpus = []
            for c in conts:
                for r in c.rows:
                    if r.translated:
                        text, _ = fit_text(normalise(r.en.strip()), r.kind, Counter())
                        corpus.append(text)
            print(f"[inject] building the DTE dictionary from {len(corpus)} rows ...")
            dte = build_dte(corpus, count=dte_count, verbose=verbose)
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "dte.json").write_text(json.dumps(
            {"entries": dte, "count": len(dte),
             "note": "DTE dictionary for the PS1 English patch; index k is "
                     "byte 0xA0+k (k<64) or 0xF0+(k-64); built by tools/patch/inject.py"},
            indent=1) + "\n")
    files = {}
    reports = []
    for c in conts:
        c.prepare(dte, None)
        c.pack()
        out = c.write(out_dir)
        c.verify()
        files[c.cdrom] = out
        rep = c.summary(dte)
        reports.append(rep)
        flag = "" if rep["rows_fallback"] == 0 else f"  FALLBACK {rep['rows_fallback']} rows / {rep['fallback_bytes']} B"
        print(f"[inject] {c.cdrom:22s} rows {rep['rows']:5d} en {rep['rows_with_english']:5d} "
              f"cap {rep['capacity_bytes']:7d} raw {rep['demand_raw_bytes']:7d} "
              f"dte {rep['demand_dte_bytes']:7d} ({rep['dte_saving_pct']:4.1f}%) "
              f"placed {rep['rows_placed']:5d}{flag}")
    tot = {
        "containers": len(reports),
        "rows": sum(r["rows"] for r in reports),
        "rows_with_english": sum(r["rows_with_english"] for r in reports),
        "capacity_bytes": sum(r["capacity_bytes"] for r in reports),
        "demand_raw_bytes": sum(r["demand_raw_bytes"] for r in reports),
        "demand_dte_bytes": sum(r["demand_dte_bytes"] for r in reports),
        "rows_placed": sum(r["rows_placed"] for r in reports),
        "rows_fallback": sum(r["rows_fallback"] for r in reports),
        "fallback_bytes": sum(r["fallback_bytes"] for r in reports),
        "containers_fully_fit": sum(1 for r in reports if r["rows_fallback"] == 0),
        "reflowed": sum(r["reflowed"] for r in reports),
        "choice_too_wide": sum(r["choice_too_wide"] for r in reports),
        "choice_two_rows": sum(r["choice_two_rows"] for r in reports),
        "token_mismatch": sum(r["token_mismatch"] for r in reports),
        "tagged_rows": sum(r["tagged_rows"] for r in reports),
        "label_over_budget": sum(r["label_over_budget"] for r in reports),
        "dte_entries": len(dte),
    }
    raw_over = sum(max(0, r["demand_raw_bytes"] - r["capacity_bytes"]) for r in reports)
    dte_over = sum(max(0, r["demand_dte_bytes"] - r["capacity_bytes"]) for r in reports)
    tot["overflow_raw_bytes_sum_over_containers"] = raw_over
    tot["overflow_dte_bytes_sum_over_containers"] = dte_over
    tot["containers_over_capacity_raw"] = sum(1 for r in reports if r["demand_raw_bytes"] > r["capacity_bytes"])
    tot["containers_over_capacity_dte"] = sum(1 for r in reports if r["demand_dte_bytes"] > r["capacity_bytes"])
    by_dir = {}
    for r in reports:
        d = r["file"].split("/")[1]
        t = by_dir.setdefault(d, {"containers": 0, "rows": 0, "rows_with_english": 0,
                                  "capacity_bytes": 0, "demand_raw_bytes": 0,
                                  "demand_dte_bytes": 0, "rows_placed": 0,
                                  "rows_fallback": 0, "choice_too_wide": 0, "choice_two_rows": 0,
                                  "containers_fully_fit": 0})
        t["containers"] += 1
        for k in ("rows", "rows_with_english", "capacity_bytes", "demand_raw_bytes",
                  "demand_dte_bytes", "rows_placed", "rows_fallback", "choice_too_wide",
                  "choice_two_rows"):
            t[k] += r[k]
        t["containers_fully_fit"] += 1 if r["rows_fallback"] == 0 else 0
    for d, t in sorted(by_dir.items()):
        print(f"[inject] {d:9s} {t['containers']:3d} containers, {t['rows_placed']}/{t['rows_with_english']} "
              f"rows placed ({t['rows_fallback']} fallback), capacity {t['capacity_bytes']} B, "
              f"raw {t['demand_raw_bytes']} B, dte {t['demand_dte_bytes']} B, "
              f"over-wide choices {t['choice_too_wide']}, two-row choices {t['choice_two_rows']}")
    report = {"totals": tot, "by_dir": by_dir, "dte": dte, "containers": reports}
    gen_dir.mkdir(parents=True, exist_ok=True)
    wide = [(r["file"], w) for r in reports for w in r["wide_choices"]]
    with open(gen_dir / "wide_choices.csv", "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["ID", "File", "English", "Note"])
        for f, w in wide:
            wr.writerow([w["id"], f, w["text"], w["note"]])
    over = [(r["file"], n) for r in reports for f in r["fallback_rows"] + r["wide_choices"]
            for n in [f.get("note", "")] if "speaker label" in n]
    if tot["label_over_budget"]:
        print(f"[inject] {tot['label_over_budget']} speaker labels wider than {LABEL_PX_MAX} px "
              f"(drawn on their own row): {over[:6]}")
    if wide:
        msg = (f"[inject] {len(wide)} choice replies cannot be shown without clipping "
               f"(> {CHOICE_ROWS_PER_REPLY} rows or a menu > {CHOICE_ROWS_PER_MENU} rows); "
               f"shorten them in {CHOICE_OVERRIDES.relative_to(ROOT)} -- list: "
               f"{gen_dir / 'wide_choices.csv'}")
        if wide_choices == "fail":
            raise SystemExit(msg)
        print(msg)
    (ROOT / "build" / "patch" / "inject.report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"[inject] TOTAL {tot['containers']} containers, {tot['rows_with_english']}/{tot['rows']} rows "
          f"with English; capacity {tot['capacity_bytes']} B, demand raw {tot['demand_raw_bytes']} B "
          f"(over capacity in {tot['containers_over_capacity_raw']} files, {raw_over} B), "
          f"with DTE {tot['demand_dte_bytes']} B (over in {tot['containers_over_capacity_dte']} files, "
          f"{dte_over} B); placed {tot['rows_placed']}, fallback {tot['rows_fallback']} rows "
          f"({tot['fallback_bytes']} B); {tot['containers_fully_fit']} containers fully fit; "
          f"reflowed {tot['reflowed']}, over-wide choices {tot['choice_too_wide']}, "
          f"token mismatches {tot['token_mismatch']}")
    return files, dte, report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dirs", nargs="*", default=None)
    ap.add_argument("--only", nargs="*", default=None, help="DIR/STEM ...")
    ap.add_argument("--dte", help="reuse a dte.json")
    ap.add_argument("--no-dte", action="store_true")
    ap.add_argument("--dte-count", type=int, default=textcodec.DTE_COUNT)
    ap.add_argument("--status", nargs="*", default=list(ACCEPT_STATUS))
    ap.add_argument("--trust-maxbytes", action="store_true",
                    help="use the sheet's MaxBytes slot instead of ceil4(len+1)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--allow-wide", action="store_true",
                    help="only report replies the choice box cannot show")
    a = ap.parse_args()
    run(a.dirs, a.only, a.dte, a.no_dte, a.status, trust_maxbytes=a.trust_maxbytes,
        verbose=a.verbose, dte_count=a.dte_count,
        wide_choices="warn" if a.allow_wide else "fail")


if __name__ == "__main__":
    main()
