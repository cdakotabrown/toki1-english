#!/usr/bin/env python3
"""compose_check.py - every string the game ASSEMBLES at runtime, rendered
from the patched binaries and checked as English.

The game builds many visible strings from pieces: strcpy/strcat chains
(place + verb, player name + speech, number + "album"), sprintf formats
(the omikuji line), pieces drawn side by side at fixed x (the club
captain's line), and name builders (get_p_name / get_g_name).  A piece
translated on its own can read fine in the sheet and still compose into
"Tanaka"Stop it!" or "Treasure:Ruby" or an ideographic space inside a
Latin name.  config/patch/compositions.json lists every such composition
with its pieces (addresses in the main exe or an overlay, pointer tables,
sample variables) as read off the C; this tool

  * renders EVERY combination (tables x variables x alternatives) from the
    build's own bytes (build/patch/SLPS_000.65, build/patch/EXEDIR/*.EXN,
    decoded with the build's DTE table), and
  * fails on: Japanese left in an English composition, a byte that draws
    as the '?' fallback, a double space, a space before punctuation, two
    words joined at a piece boundary ("FujisakiShiori", 'Tanaka"Stop'),
    punctuation glued to the next word at a boundary ("Treasure:Ruby"),
    a line wider than the draw site allows, a composed string longer than
    the buffer it is built in (the retail strcat has no bound), and for
    fixed-x pieces an overlap or a gap wider than a word space;
  * COVERAGE: every C file under src/main/matched and src/overlay that
    calls strcat / strncat / sprintf must be named by a composition or by a
    waiver with its reason, so a newly decompiled composer cannot slip by.

  python3 tools/patch/compose_check.py              # check (exit 1 on error)
  python3 tools/patch/compose_check.py --show ID    # print every rendering
  python3 tools/patch/compose_check.py --list       # one sample per composition

Spec (config/patch/compositions.json):
  "vars":  {"name": [samples...] | {"from": "girl_given"|...}}
  "compositions": [{
      "id", "src" (C file), "ov" (overlay name; omit = main exe),
      "pieces": [piece, ...]  or  "alts": [[piece, ...], ...],
      "max_px" (line width limit, after {br} splits), "buf" (bytes incl. NUL),
      "row": true (pieces carry "x": fixed draw positions, one line),
      "allow": ["ideographic_space", "japanese", "double_space"], "note"}]
  piece: {"s": "0xADDR"} string | {"t": "0xADDR", "n": N} N pointers |
         {"t": ..., "pick": [i, ...]} | {"v": "var"} | {"lit": "text"} |
         {"rec": "0xADDR", "stride": B, "n": N} fixed-width records
  "waive": {"<C file>": "reason"}
  "draw_slots": [{"ov", "s" (slot address), "gloss" (English; the retail
      Japanese is on the disc), "src" ([every C file that
      reads it]), "why", "max_px" (default 201), "buf" (strcpy destination
      bytes), "breaks" (the drawer honours {br}), "wraps" (N: the drawer
      word-wraps the text itself at max_px -- sndi -> pt_field_line ->
      pt_field_queue -- and it may take up to N rows)}] -- standalone strings
      with no pointer word whose readers only draw them (or strcpy them):
      a module string may stand in when the English does not fit
"""
import argparse
import itertools
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, SHEETS, PATCH_CONFIG, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import textcodec  # noqa: E402
import patch_symbols  # noqa: E402
import retail_text  # noqa: E402

SPEC = PATCH_CONFIG / "compositions.json"
MAIN_BASE = 0x80041000 - 0x800
OV_BASE = 0x80132000
OV_SIZE = 192 * 1024
MAX_COMBOS = 4000
PT_C_STR, PT_C_DST, PT_STR_BASE, PT_STR_COUNT = 0x1D, 0x1A, 0x20, 64
CALL_RE = re.compile(r"\b(strcat|strncat|sprintf)\s*\(")
ALLOWED_SJIS = set("○×△□")
PUNCT_AFTER = ".,!?:;)"


class Image:
    """the patched (or retail) main exe + overlays, addressed by RAM"""

    def __init__(self, patched=True, out="build/patch"):
        self.patched = patched
        self.out = locate(out)
        exe = (self.out / "SLPS_000.65") if patched else (DECOMP / "disks" / "SLPS_000.65")
        self.exe = exe.read_bytes()
        self.ovs = {}
        dte = self.out / "gen" / "dte.json"
        if not dte.exists():                # a profile with its own out dir shares
            dte = ROOT / "build" / "patch" / "gen" / "dte.json"   # build/patch/gen
        self.dte = json.loads(dte.read_text())["entries"] if (patched and dte.exists()) else None
        # module strings (PT_C_STR): patch_str_table from the build report
        self.strs = {}
        rep = self.out / "english.report.json"
        if not rep.exists():                # english-debug.report.json, ...
            reps = sorted(p for p in self.out.glob("*.report.json")
                          if p.name != "inject.report.json")
            rep = reps[0] if len(reps) == 1 else rep
        if patched and rep.exists():
            syms = json.loads(rep.read_text()).get("module", {}).get("symbols", {})
            tab = syms.get("patch_str_table")
            if tab:
                tab = int(tab, 16)
                for k in range(PT_STR_COUNT):
                    ptr = struct.unpack_from("<I", self.exe, tab - MAIN_BASE + 4 * k)[0]
                    if ptr:
                        self.strs[k] = self.exe[ptr - MAIN_BASE:self.exe.index(b"\0", ptr - MAIN_BASE)]

    def ov(self, name):
        if name not in self.ovs:
            p = self.out / "EXEDIR" / f"{name}.EXN"
            if not self.patched or not p.exists():
                p = DECOMP / "assets" / "overlays" / f"{name}.EXN"
            self.ovs[name] = p.read_bytes()
        return self.ovs[name]

    def _loc(self, ov, addr):
        if ov and OV_BASE <= addr < OV_BASE + OV_SIZE:
            return self.ov(ov), addr - OV_BASE
        return self.exe, addr - MAIN_BASE

    def raw(self, ov, addr, n=None):
        d, off = self._loc(ov, addr)
        if not 0 <= off < len(d):
            raise ValueError(f"0x{addr:08X} is outside the image")
        if n is not None:
            return d[off:off + n]
        return d[off:d.index(b"\0", off)]

    def word(self, ov, addr):
        return struct.unpack("<I", self.raw(ov, addr, 4))[0]

    def module_str(self, raw):
        """the pool text of a PT_C_STR reference, or None"""
        if len(raw) >= 2 and raw[0] == PT_C_STR:
            k = raw[1] - PT_STR_BASE
            if k not in self.strs:
                raise ValueError(f"module string {k} is not in the build's patch_str_table")
            return self.strs[k]
        return None

    def text(self, raw):
        if self.patched:
            return textcodec.decode(raw, self.dte)
        return raw.decode("shift_jis", "replace")


def width(text):
    """pixel width of one rendered line (ideographic space = 14 px)"""
    return textcodec.width(text)


# ---------------------------------------------------------------------------
# variables
# ---------------------------------------------------------------------------

def builtin_var(img, name):
    """samples derived from the build itself"""
    if name in ("p_sei", "p_mei", "p_adana"):
        tab, stride = {"p_sei": (0x8014CE6C, 8), "p_mei": (0x8014CEE4, 8),
                       "p_adana": (0x8014CF5C, 12)}[name]
        # the 15 default names of the build, plus the longest name the
        # Latin keyboard accepts (7 / 7 / 15 letters, text_name_ent.c)
        out = [(img.raw("NAME_ENT", tab + i * stride, stride).split(b"\0")[0], None)
               for i in range(15)]
        longest = {"p_sei": "Kitagaw", "p_mei": "Kenichi", "p_adana": "Kenichi-kun-dan"}[name]
        return out + [(longest.encode("ascii"), None)]
    if name == "girl_family":            # date_name_set_tbl0 (D_800B9AE0[0..15])
        return [(img.raw(None, img.word(None, 0x800B9AE0 + 4 * i)), None) for i in range(16)]
    if name == "girl_given":             # get_g_name(i) for every girl (get_g_name.c)
        out = []
        for i in range(16):
            if i == 0:
                s = img.raw(None, 0x800B633C)
            elif i == 10:
                s = img.raw(None, img.word(None, 0x800B9B1C)) + img.raw(None, 0x800B6344)
            elif i == 12:
                s = img.raw(None, img.word(None, 0x800B9B10))
            else:
                s = img.raw(None, img.word(None, 0x800B9AE0 + 4 * i)) + img.raw(None, 0x800B634C)
            out.append((s, None))
        return out
    if name == "girl_full":              # D_800B9A24[0..12] (phone book / profile)
        return [(img.raw(None, img.word(None, 0x800B9A24 + 4 * i)), None) for i in range(13)]
    if name == "club":                   # album_info_disp_tbl1 (club names)
        return [(img.raw(None, img.word(None, 0x800B9DF4 + 4 * i)), None) for i in range(12)]
    if name == "place":                  # machiawase_menu_set_tbl0 (date spots)
        return [(img.raw(None, img.word(None, 0x800B9918 + 4 * i)), None) for i in range(21)]
    if name == "digits":                 # album_info_disp_tbl0 ("0".."16")
        return [(img.raw(None, img.word(None, 0x800B9774 + 4 * i)), None) for i in range(17)]
    return None


def var_samples(img, spec_vars, name):
    v = builtin_var(img, name)
    if v is not None:
        return v
    if name not in spec_vars:
        raise SystemExit(f"[compose] unknown variable {name!r}")
    return [(textcodec.encode(s), None) for s in spec_vars[name]]


# ---------------------------------------------------------------------------
# pieces
# ---------------------------------------------------------------------------

def piece_values(img, comp, p, spec_vars):
    """[(raw bytes, x or None), ...] -- the alternatives of one piece; a
    "max" cuts each to the first N bytes, as strncat(dst, src, N) does"""
    vals = _piece_values(img, comp, p, spec_vars)
    if "max" in p:
        vals = [(r[:int(p["max"])], x) if r != "FMT" else (r, x) for r, x in vals]
    return vals


def _piece_values(img, comp, p, spec_vars):
    ov = comp.get("ov")
    x = p.get("x")
    if "s" in p:
        return [(img.raw(ov, int(p["s"], 16)), x)]
    if "t" in p:
        base = int(p["t"], 16)
        idx = p.get("pick", range(int(p.get("n", 1))))
        return [(img.raw(ov, img.word(ov, base + 4 * i)), x) for i in idx]
    if "rec" in p:
        base, stride = int(p["rec"], 16), int(p["stride"])
        idx = p.get("pick", range(int(p.get("n", 1))))
        return [(img.raw(ov, base + i * stride, stride).split(b"\0")[0], x) for i in idx]
    if "v" in p:
        vals = var_samples(img, spec_vars, p["v"])
        if "pick" in p:
            vals = [vals[i] for i in p["pick"]]
        return [(r, x) for r, _ in vals]
    if "lit" in p:
        return [(textcodec.encode(p["lit"]), x)]
    if "fmt" in p:
        # a printf format: the decoded format with each %s / %d replaced by
        # the matching argument piece (rendered as its own boundary)
        fmt = img.raw(ov, int(p["fmt"], 16))
        args = [piece_values(img, comp, a, spec_vars) for a in p.get("args", [])]
        out = []
        for combo in itertools.product(*args) if args else [()]:
            segs = re.split(rb"%[-0-9]*[sd]", fmt)
            if len(segs) - 1 != len(combo):
                raise SystemExit(f"[compose] {comp['id']}: format 0x{int(p['fmt'], 16):08X} "
                                 f"has {len(segs) - 1} conversions, {len(combo)} args")
            parts = []
            for i, seg in enumerate(segs):
                parts.append((seg, None))
                if i < len(combo):
                    parts.append(combo[i])
            out.append(("FMT", parts))
        return out
    raise SystemExit(f"[compose] {comp['id']}: bad piece {p}")


def combos(img, comp, spec_vars):
    alts = comp.get("alts") or [comp["pieces"]]
    for pieces in alts:
        choices = [piece_values(img, comp, p, spec_vars) for p in pieces]
        n = 1
        for c in choices:
            n *= len(c)
        it = itertools.product(*choices)
        if n > MAX_COMBOS:
            # every value of every piece appears at least once: walk the
            # longest list and cycle the others (diagonal), plus the first
            # MAX_COMBOS of the product
            longest = max(len(c) for c in choices)
            diag = [tuple(c[i % len(c)] for c in choices) for i in range(longest)]
            it = itertools.chain(diag, itertools.islice(itertools.product(*choices), MAX_COMBOS))
        for combo in it:
            flat = []
            for c in combo:
                if c[0] == "FMT":
                    flat.extend(c[1])
                else:
                    flat.append(c)
            yield flat


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def is_word(ch):
    return ch.isascii() and ch.isalnum()


def is_jp(ch):
    return ord(ch) > 0x7E and ch not in ALLOWED_SJIS and ch != "\n"


def compose(comp, parts, img):
    """what the game builds: strcpy the first piece, strcat the others,
    resolving module strings the way text_names.c does (a template with
    PT_C_DST replaces the text so far with itself, the old text spliced in).
    Returns [(text, x, nbytes)] segments."""
    segs = []
    for raw, x in parts:
        mod = img.module_str(raw)
        if mod is None:
            segs.append((img.text(raw), x, len(raw)))
            continue
        if PT_C_DST in mod and not comp.get("row"):
            before, _, after = mod.partition(bytes([PT_C_DST]))
            segs = [(img.text(before), None, len(before))] + segs + \
                [(img.text(after.replace(bytes([PT_C_DST]), b"")), None,
                  len(after.replace(bytes([PT_C_DST]), b"")))]
        else:
            plain = mod.replace(bytes([PT_C_DST]), b"")
            segs.append((img.text(plain), x, len(plain)))
    return segs


def check_render(comp, parts, img):
    """parts: [(raw, x)] -> (rendered text, [errors])"""
    allow = set(comp.get("allow", []))
    segs = compose(comp, parts, img)
    texts = [t for t, _, _ in segs]
    parts = [(b"\0" * n, x) for _, x, n in segs]
    full = "".join(texts)
    errs = []
    flat = full.replace("{br}", " ")
    if re.search(r"\{(x[0-9A-F]{2}|\?)\}", full):
        errs.append("undrawable byte (draws as the '?' fallback)")
    has_latin = bool(re.search(r"[A-Za-z]", flat))
    jp = list(dict.fromkeys(c for c in flat if is_jp(c)))
    if has_latin and jp:
        jp_ok = set()
        if "ideographic_space" in allow:
            jp_ok.add("　")
        if "japanese" in allow:
            jp_ok |= set(jp)
        bad = [c for c in jp if c not in jp_ok]
        if bad:
            errs.append(f"Japanese in an English composition: {''.join(bad)}")
    lines = [ln.strip() for ln in full.split("{br}")]
    if "double_space" not in allow and any("  " in ln for ln in lines):
        errs.append("double space")
    m = re.search(r" [.,!?:;)]", flat)
    if m:
        errs.append(f"space before punctuation ({m.group(0)!r})")
    if re.search(r"\( ", flat):
        errs.append("space after '('")
    # boundaries between consecutive pieces
    if not comp.get("row"):
        seq = [t for t in texts if t]
        before = ""
        for a, b in zip(seq, seq[1:]):
            before += a
            la, fb = a[-1], b[0]
            closing = fb == '"' and before.count('"') % 2 == 1   # a quote that closes
            if is_word(la) and (is_word(fb) or fb in "\"(") and not closing and \
                    not (la.isdigit() and fb.isdigit()):
                errs.append(f"words joined at a piece boundary: {a[-12:]!r}+{b[:12]!r}")
            elif la in ",:;!?" and fb.isalpha():
                errs.append(f"punctuation glued to the next word: {a[-12:]!r}+{b[:12]!r}")
            elif la == "." and fb.isalpha() and fb.isupper():
                errs.append(f"sentence glued to the next one: {a[-12:]!r}+{b[:12]!r}")
    # width
    if comp.get("max_px"):
        for line in full.split("{br}"):
            w = width(line)
            if w > comp["max_px"]:
                errs.append(f"{w} px > {comp['max_px']} px: {line!r}")
    # buffer (the bytes strcat really copies, NUL included)
    if comp.get("buf"):
        n = sum(len(r) for r, _ in parts) + 1
        if n > comp["buf"]:
            errs.append(f"{n} bytes > the {comp['buf']}-byte buffer it is built in")
    # fixed-x pieces on one row
    if comp.get("row"):
        xs = [(x, t) for (r, x), t in zip(parts, texts)]
        for (x0, t0), (x1, t1) in zip(xs, xs[1:]):
            if x0 is None or x1 is None:
                continue
            end = x0 + width(t0)
            if end > x1 - 1:
                errs.append(f"{t0!r} (x {x0}..{end}) overlaps {t1!r} at x {x1}")
            elif x1 - end > comp.get("max_gap", 9) and t0.strip() and t1.strip():
                errs.append(f"{x1 - end}-px gap between {t0!r} and {t1!r}")
        if xs and xs[0][0] is not None and comp.get("max_x"):
            end = xs[-1][0] + width(xs[-1][1])
            if end > comp["max_x"]:
                errs.append(f"row ends at x {end} > {comp['max_x']}")
        full = " | ".join(t for t in texts)
    return full, errs


# sample text for the name tokens around a script token's insert
TOKEN_SAMPLES = {"{P}": "Kenji", "{G}": "Shiori", "{p}": "Fukuda", "{m}": "Kenji",
                 "{F}": "Kenji Fukuda", "{Y}": "Yoshio", "{S}": "Kyoto", "{O}": "Great",
                 "{W}": "Good Health", "{A}": "a gift", "{M}": "the park"}


def sheet_rows(patterns):
    """(key, Japanese, English) of the container rows of the sheets matching
    the patterns, with config/patch/choice_overrides.json applied"""
    import csv
    import fnmatch
    sys.path.insert(0, str(TOOLS_PATCH))
    import inject
    over = {}
    po = PATCH_CONFIG / "choice_overrides.json"
    if po.exists():
        over = json.loads(po.read_text()).get("rows", {})
    sheets = SHEETS
    for path in sorted(sheets.glob("*/*.csv")):
        rel = f"{path.parent.name}/{path.stem}"
        if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            continue
        for r in retail_text.read_sheet(path):
                en = over.get(inject.choice_key(r["ID"])) or (r.get("English") or "")
                if en.strip() and r.get("Status") != "untranslated":
                    yield inject.choice_key(r["ID"]), r["Japanese"], en.strip()


def token_renders(img, comp, spec_vars):
    """a script token ({A} {M} {O} {W} {S}) inserted into every container
    row that carries it: the row's English with each value of the table the
    overlay copies into the token's buffer"""
    tok = comp["token"]
    vals = []
    for p in comp["values"]:
        for r, _ in piece_values(img, comp, p, spec_vars):
            mod = img.module_str(r)       # strcpy into the buffer resolves it
            vals.append(img.text(mod.replace(bytes([PT_C_DST]), b"")) if mod is not None
                        else img.text(r))
    match = re.compile(comp["match"]) if comp.get("match") else None
    rows = list(sheet_rows(comp.get("rows", [])))
    for a in comp.get("strings", []):
        # an overlay / exe string that carries the token (drawn through the
        # message formatter, which expands it)
        addr = int(a, 16)
        retail = Image(False)
        jp = textcodec.decode(textcodec.retail_to_patch(retail.raw(comp.get("ov"), addr)))
        rows.append((f"{comp.get('ov') or 'main'}:{a}", jp, img.text(img.raw(comp.get("ov"), addr))))
    for key, jp, en in rows:
        if tok not in jp or (match and not match.search(jp)):
            continue
        if re.fullmatch(r"(\{[A-Za-z]+\}|\s)*", en):
            continue                    # a bare token row (a buffer echo, not a sentence)
        for v in vals:
            if not v:
                continue
            text = en.replace(tok, v)
            for t, sample in TOKEN_SAMPLES.items():
                text = text.replace(t, sample)
            text = text.replace("{opt}", " / ")
            errs = check_text(comp, text, v)
            yield (f"{key}: {text}", errs), None


def check_text(comp, text, value):
    """the rules for a rendered row with a token insert"""
    errs = []
    lines = [ln.strip() for ln in text.split("{br}")]
    flat = " ".join(lines)
    if re.search(r"\{(x[0-9A-F]{2}|\?)\}", flat):
        errs.append("undrawable byte (draws as the '?' fallback)")
    jp = list(dict.fromkeys(c for c in flat if is_jp(c)))
    if jp and re.search(r"[A-Za-z]", flat):
        errs.append(f"Japanese in an English composition: {''.join(jp)}")
    if any("  " in ln for ln in lines):
        errs.append("double space")
    m = re.search(r" [.,!?:;)]", flat)
    if m:
        errs.append(f"space before punctuation ({m.group(0)!r})")
    # the insert opens a sentence: it must start with a capital
    i = flat.find(value)
    if i >= 0 and value[:1].islower() and (i == 0 or re.search(r"[.!?]\s*$", flat[:i])):
        errs.append(f"insert {value!r} opens a sentence in lower case")
    if i > 0 and flat[i - 1].isalnum():
        errs.append(f"insert {value!r} glued to the word before it")
    j = i + len(value)
    if i >= 0 and j < len(flat) and flat[j].isalnum():
        errs.append(f"insert {value!r} glued to the word after it")
    return errs


def composed_slots(spec_path=SPEC):
    """{(target, addr)}: the retail string slots that are pieces ("s") of a
    composition -- consumed only through strcpy / strcat / sprintf %s or a
    draw call, so they may hold a module-string reference (PT_C_STR) when
    their English does not fit (overlay_sheets.py, ui_strings.py,
    draft_check.py).  target = the overlay name or "main"."""
    spec = json.loads(Path(spec_path).read_text())
    out = set()

    def walk(comp, pieces):
        for p in pieces:
            if "s" in p:
                a = int(p["s"], 16)
                ov = comp.get("ov")
                tgt = ov if (ov and OV_BASE <= a < OV_BASE + OV_SIZE) else "main"
                out.add((tgt, a))
            if "fmt" in p:
                walk(comp, p.get("args", []))

    for comp in spec["compositions"]:
        for pieces in comp.get("alts") or [comp.get("pieces", [])]:
            walk(comp, pieces)
    out |= text_buffer_sources()
    return out


def draw_slots(spec_path=SPEC):
    """{(target, addr): entry} of the spec's "draw_slots": standalone
    strings (not composition pieces) whose every reader hands the slot
    straight to the patch renderer (set_kanji_string / basyo_init ->
    pt_basyo_init / a hooked step) or to strcpy (pt_strcpy resolves the
    reference into a buffer of "buf" bytes), so the slot may hold a
    module-string reference (PT_C_STR) when its English does not fit and
    the slot has no pointer word to relocate through.  Each entry names
    the C files that read it ("src"); check_draw_slots() fails when any
    other file names the address."""
    spec = json.loads(Path(spec_path).read_text())
    out = {}
    for e in spec.get("draw_slots", []):
        a = int(e["s"], 16)
        ov = e.get("ov")
        tgt = ov if (ov and OV_BASE <= a < OV_BASE + OV_SIZE) else "main"
        out[(tgt, a)] = e
    return out


def module_slots(spec_path=SPEC):
    """every slot a module string may stand in for: composition pieces
    (composed_slots) and the reasoned draw-only slots (draw_slots)"""
    return composed_slots(spec_path) | set(draw_slots(spec_path))


def check_draw_slots(spec, img):
    """errors for the spec's draw_slots: a reader the entry does not name
    (any C file of the overlay -- or the main exe -- that names the slot's
    address), a missing reason, and, in the patched build, a module string
    wider than max_px, longer than its copy buffer or not English"""
    errs = []
    entries = spec.get("draw_slots", [])
    if not entries:
        return errs
    readers = {}
    for p in sorted(list((DECOMP / "src" / "main" / "matched").glob("*.c")) +
                    list((DECOMP / "src" / "overlay").glob("*/*.c"))):
        ov = None if p.parent.name == "matched" else p.parent.name
        body = "\n".join(ln for ln in p.read_text(errors="replace").splitlines()
                         if "extern" not in ln
                         and not ln.lstrip().startswith(("*", "/*", "//")))
        for ident in set(re.findall(r"\b[A-Za-z_]\w*\b", body)):
            a = data_addr(ident, ov)
            if a is None:
                continue
            tgt = ov if (ov and OV_BASE <= a < OV_BASE + OV_SIZE) else "main"
            readers.setdefault((tgt, a), set()).add(str(p.relative_to(DECOMP)))
    for e in entries:
        a = int(e["s"], 16)
        ov = e.get("ov")
        tgt = ov if (ov and OV_BASE <= a < OV_BASE + OV_SIZE) else "main"
        key = f"{tgt}:0x{a:08X}"
        src = set(e.get("src", []))
        if not e.get("why") or not src:
            errs.append(f"draw slot {key}: needs \"src\" (its readers) and \"why\"")
        for s in sorted(src):
            if not (DECOMP / s).exists():
                errs.append(f"draw slot {key}: reader {s} does not exist (renamed? run "
                            f"`{patch_symbols.SYNC_HINT}`)")
        for s in sorted(readers.get((tgt, a), set()) - src):
            errs.append(f"draw slot {key}: {s} names the slot but is not one of its "
                        f"listed readers; prove it reads the slot only through the "
                        f"renderer or strcpy and add it, or drop the slot")
        if not img.patched:
            continue
        try:
            raw = img.raw(ov, a)
            mod = img.module_str(raw)
        except ValueError as ex:
            errs.append(f"draw slot {key}: {ex}")
            continue
        if mod is None:
            continue                    # the English fits in place
        if raw[2:3] not in (b"", b"\0"):
            errs.append(f"draw slot {key}: bytes after the module reference")
        txt = img.text(mod)
        if any(is_jp(c) for c in txt):
            errs.append(f"draw slot {key}: Japanese in {txt!r}")
        if "{br}" in txt and not e.get("breaks"):
            # set_kanji_string draws one row and skips control bytes: a
            # {br} would glue the words around it ("WorldDomination")
            errs.append(f"draw slot {key}: {{br}} in a one-row draw: {txt!r}")
        max_px = int(e.get("max_px", 201))
        lines = txt.split("{br}")
        if e.get("wraps"):
            # the drawer word-wraps at max_px (pt_field_queue): check the
            # rows it will make, not the unbroken text
            lines = [r for ln in lines for r in textcodec.wrap(ln, max_px).split("{br}")]
            if len(lines) > int(e["wraps"]):
                errs.append(f"draw slot {key}: wraps to {len(lines)} rows > {e['wraps']}: {txt!r}")
        for line in lines:
            w = width(line)
            if w > max_px:
                errs.append(f"draw slot {key}: {w} px > {max_px} px: {line!r}")
        if "buf" in e and len(mod) + 1 > int(e["buf"]):
            errs.append(f"draw slot {key}: {len(mod)} bytes + NUL > the {e['buf']}-byte "
                        f"buffer strcpy fills")
    return errs


# the game's text buffers: a string strcpy'd / strcat'd into one of them is
# drawn from the buffer (banner ba_string, the name / token buffers), so its
# slot is read only by the BIOS thunk -- which resolves a module string
TEXT_BUFFERS = ("ba_string", "ba_string2", "g_name", "g_name2", "p_name", "pp_name",
                "p_name2", "shu_name", "oname", "wname", "aname", "mname")
# their ADDRESSES (main scope): a rename of a buffer or of a copied string
# must not make the scan below silently match less, so the C is matched on
# any identifier and every name is resolved through the naming ledger
TEXT_BUFFER_ADDRS = (0x800D069C, 0x800D06DC, 0x800D0688, 0x800D0690, 0x800D066C,
                     0x800D0674, 0x800D067C, 0x800D073C, 0x800D0748, 0x800D0750,
                     0x800D075C, 0x800D0780)
_COPY_RE = re.compile(r"\bstr(?:cpy|cat)\s*\(\s*(?:\([^)]*\)\s*)?&?([A-Za-z_]\w*)\s*,\s*"
                      r"(?:\([^)]*\)\s*)?&?([A-Za-z_]\w*)\s*\)")


def data_addr(ident, ov):
    """the address a data identifier of a C file in overlay `ov` (None =
    main) names: an address-form D_ name by its suffix, a landed DATA name
    of the naming ledger (the overlay's own first) by its record; else
    None (functions, locals, anything the ledger does not know)"""
    a = patch_symbols.address_form(ident)
    if a is not None:
        return a if ident.startswith("D_") else None
    r = patch_symbols.ledger().resolve(ident, ov or "main")
    if r.status != "current":
        return None
    rec = patch_symbols.ledger().records.get((r.scope, r.addr), {})
    return r.addr if rec.get("kind", "data") == "data" else None


def text_buffer_sources():
    out = set()
    for p in list((DECOMP / "src" / "main" / "matched").glob("*.c")) + \
            list((DECOMP / "src" / "overlay").glob("*/*.c")):
        ov = None if p.parent.name == "matched" else p.parent.name
        for m in _COPY_RE.finditer(p.read_text(errors="replace")):
            if data_addr(m.group(1), None) not in TEXT_BUFFER_ADDRS:
                continue
            a = data_addr(m.group(2), ov)
            if a is None:
                continue
            tgt = ov if (ov and OV_BASE <= a < OV_BASE + OV_SIZE) else "main"
            out.add((tgt, a))
    return out


_DRAW_RE = re.compile(r"\b(set_kanji_string|sndisp|sndi|gnsx|basyo_init2?|x_taku_string_set|strncat|sprintf|"
                      r"msg_str_disp|strcpy|strcat)\s*\(([^;]*)\)\s*;")


def drawn_literals_japanese(img, kept):
    """the named data strings handed to a draw call (or copied into a text
    buffer) that still read Japanese in the build -- the inventory's blind
    spots (full-width Latin, one-kanji strings, command-letter records)
    show up here; `kept` lists the ones Japanese on purpose"""
    retail = Image(False)
    out = {}
    for p in sorted(list((DECOMP / "src" / "main" / "matched").glob("*.c")) +
                    list((DECOMP / "src" / "overlay").glob("*/*.c"))):
        ov = None if p.parent.name == "matched" else p.parent.name
        if ov in ("EVENT", "GYOZI"):
            continue
        for m in _DRAW_RE.finditer(p.read_text(errors="replace")):
            for ident in set(re.findall(r"\b[A-Za-z_]\w*\b", m.group(2))):
                a = data_addr(ident, ov)
                if a is None:
                    continue
                tgt = ov if (ov and OV_BASE <= a < OV_BASE + OV_SIZE) else "main"
                key = f"{tgt}:0x{a:08X}"
                if key in kept or key in out:
                    continue
                try:
                    raw = img.raw(ov, a)
                    w = img.raw(ov, a, 4)
                except (ValueError, IndexError):
                    continue
                if len(w) == 4 and 0x80000000 <= struct.unpack("<I", w)[0] < 0x80200000:
                    continue                    # a pointer table, not a string
                if re.search(r"\b%s\s*\[" % re.escape(ident), m.group(2)):
                    w1 = img.raw(ov, a + 4, 4)  # tbl[i] of a pointer table whose
                    if len(w1) == 4 and \
                            0x80000000 <= struct.unpack("<I", w1)[0] < 0x80200000:
                        continue                # slot 0 is unused (not a pointer)
                if tgt == "main" and not 0x800B5A60 <= a < 0x800BD250:
                    continue                    # code / bss, not the string data
                try:                            # the retail bytes must be Shift-JIS text
                    rj = retail.raw(ov, a).decode("shift_jis")
                except (UnicodeDecodeError, ValueError):
                    continue
                if not rj or any(ord(c) < 0x20 for c in rj) or not any(ord(c) > 0x7E for c in rj):
                    continue
                mod = img.module_str(raw)
                txt = img.text(mod if mod is not None else raw)
                if any(is_jp(c) and c != "　" for c in txt):
                    out[key] = (str(p.relative_to(DECOMP)), m.group(1), txt)
    return out


def coverage(spec):
    """(missing, stale, renamed): C files that compose strings but are named
    nowhere; named files that no longer exist; named files whose function
    the naming track renamed -- [(old path, new path, "OV:0xADDR")], which
    tools/patch/sync_patch_symbols.py --apply rewrites.  A file is matched
    to its entry BY ADDRESS (its function's), so a rename is reported as
    what it is instead of as one missing and one stale file."""
    L = patch_symbols.ledger()
    named = {c["src"] for c in spec["compositions"]} | set(spec.get("waive", {}))
    draw_src = {s for e in spec.get("draw_slots", []) for s in e.get("src", [])}
    stale, renamed = [], []
    for s in sorted(draw_src - named):
        if (DECOMP / s).exists():
            continue
        cur = L.current_path(s)
        if cur and cur != s and (DECOMP / cur).exists():
            k = L.path_key(s)
            renamed.append((s, cur, f"{k[0]}:0x{k[1]:08X}"))
    for s in sorted(named):
        if (DECOMP / s).exists():
            continue
        cur = L.current_path(s)
        if cur and cur != s and (DECOMP / cur).exists():
            k = L.path_key(s)
            renamed.append((s, cur, f"{k[0]}:0x{k[1]:08X}"))
        else:
            stale.append(s)
    moved_to = {new for _, new, _ in renamed}
    missing = []
    for p in sorted(list((DECOMP / "src" / "main" / "matched").glob("*.c")) +
                    list((DECOMP / "src" / "overlay").glob("*/*.c"))):
        rel = str(p.relative_to(DECOMP))
        txt = p.read_text(errors="replace")
        body = "\n".join(ln for ln in txt.splitlines() if "extern" not in ln
                         and not ln.lstrip().startswith(("*", "/*", "//")))
        if CALL_RE.search(body) and rel not in named and rel not in moved_to:
            missing.append(rel)
    return missing, stale, renamed


def run(spec_path=SPEC, out="build/patch", show=None, list_only=False, quiet=False):
    spec = json.loads(Path(spec_path).read_text())
    img = Image(True, out)
    spec_vars = spec.get("vars", {})
    n_err = n_combo = 0
    report = []
    for comp in spec["compositions"]:
        if show and comp["id"] != show:
            continue
        errs_seen = {}
        first = None
        renders = token_renders(img, comp, spec_vars) if "token" in comp else \
            ((None, combo) for combo in combos(img, comp, spec_vars))
        for pre, combo in renders:
            n_combo += 1
            full, errs = pre if pre is not None else check_render(comp, list(combo), img)
            if first is None:
                first = full
            if show:
                print(("ERR " if errs else "ok  ") + full + ("   <- " + "; ".join(errs) if errs else ""))
            for e in errs:
                errs_seen.setdefault(e, full)
        if list_only:
            print(f"{comp['id']:40s} {first}")
        kinds = {}
        for e, full in errs_seen.items():
            kinds.setdefault(re.split(r"[:(]", e)[0].strip(), []).append((e, full))
        for kind, lst in kinds.items():
            n_err += 1
            report.append({"id": comp["id"], "error": kind, "count": len(lst),
                           "examples": [f for _, f in lst[:3]]})
            print(f"ERROR {comp['id']}: {lst[0][0]}" +
                  (f" (+{len(lst) - 1} more like it)" if len(lst) > 1 else "") +
                  f"\n      e.g. {lst[0][1]!r}")
    # a strncat(dst, src, N) piece longer than N is cut in the middle
    for comp in spec["compositions"]:
        if show and comp["id"] != show:
            continue
        for pieces in comp.get("alts") or [comp.get("pieces", [])]:
            for pc in pieces:
                if "max" not in pc:
                    continue
                for raw, _ in _piece_values(img, comp, pc, spec_vars):
                    if len(raw) > int(pc["max"]):
                        n_err += 1
                        print(f"ERROR {comp['id']}: {img.text(raw)!r} is {len(raw)} bytes; "
                              f"strncat copies {pc['max']} ({img.text(raw[:int(pc['max'])])!r})")
                        report.append({"id": comp["id"], "error": "strncat cut", "count": 1,
                                       "examples": [img.text(raw)]})
    if not show:
        for e in check_draw_slots(spec, img):
            n_err += 1
            print(f"ERROR {e}")
            report.append({"id": "draw_slots", "error": e, "count": 1, "examples": []})
    missing, stale, renamed = coverage(spec)
    for old, new, key in renamed:
        n_err += 1
        print(f"ERROR coverage: {old} is named in {Path(spec_path).name} but its "
              f"function {key} is now {new} (renamed by the naming track); run "
              f"`{patch_symbols.SYNC_HINT}`")
    for m in missing:
        n_err += 1
        print(f"ERROR coverage: {m} composes strings (strcat/strncat/sprintf) but is "
              f"neither a composition nor waived in {Path(spec_path).name}")
    for s in stale:
        print(f"note  {s}: named in {Path(spec_path).name} but no longer exists")
    print(f"[compose] {len(spec['compositions'])} compositions, {n_combo} renderings, "
          f"{len(spec.get('draw_slots', []))} draw slots, {n_err} errors")
    return n_err, report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--out", default="build/patch", help="the build's output directory")
    ap.add_argument("--show", help="print every rendering of one composition")
    ap.add_argument("--list", action="store_true", help="one rendering per composition")
    a = ap.parse_args()
    n_err, _ = run(a.spec, a.out, a.show, a.list)
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
