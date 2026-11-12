#!/usr/bin/env python3
"""textcodec.py - the English patch's string encoding (single source of truth).

Mirrors src/patch/main/patch_text.h.  Every tool that writes text into a
patched disc (the container injector, the overlay/main string overrides in
build_patched.py, the test profiles) encodes through here, and every width
the injector pre-wraps with comes from the same font metrics the engine
draws with (tools/patch/font/latin12.txt via fontgen.py).

Encoding of one string (see patch_text.h for the renderer-side table):

  0x00         end
  0x01..0x1F   control bytes: the sheet tokens {br} {opt} {P} {G} {p} {m}
               {F} {Y} {S} {O} {W} {A} {M}
  0x20..0x7E   ASCII (proportional Latin font)
  0x81-0x9F, 0xE0-0xEF + trail   Shift-JIS pair (retail 12x12 font);
                                 0xEF40.. are the patch's button icons
                                 (ICONS, tools/patch/font/icons12.txt)
  0xA0..0xDF, 0xF0..0xFE         DTE codes 0..78 (dictionary, optional;
                                 64 + 15 codes: 0xFF is NOT a code)

`encode(text, dte=None)` turns a sheet-style string with {tokens} into
bytes; Japanese characters are passed through as Shift-JIS; a DTE
dictionary (list of up to 80 ASCII strings) is applied greedily, longest
match first, to ASCII runs only.  `decode(bytes, dte)` is the inverse and
`width(text)` the pixel width of a line as the engine lays it out.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # fontgen, its sibling

TOKENS = {
    "{br}": 0x01, "{opt}": 0x02, "{P}": 0x03, "{G}": 0x04, "{p}": 0x05,
    "{m}": 0x06, "{F}": 0x07, "{Y}": 0x08, "{S}": 0x09, "{O}": 0x0A,
    "{W}": 0x0B, "{A}": 0x0C, "{M}": 0x0D,
}
TOKEN_BY_BYTE = {v: k for k, v in TOKENS.items()}
# retail single-byte command letters (lead position) -> new control byte
RETAIL_LETTERS = {" ": 0x01, "q": 0x02, "P": 0x03, "G": 0x04, "p": 0x05,
                  "m": 0x06, "F": 0x07, "Y": 0x08, "S": 0x09, "O": 0x0A,
                  "W": 0x0B, "A": 0x0C, "M": 0x0D}
# 64 codes at 0xA0..0xDF + 15 at 0xF0..0xFE.  (A table of 80 put entry 79
# at 0xFF, which the renderer does not decode: it drew "Doesn't" as
# "Does?t" in every choice reply that used the entry -- 2026-10-09.)
DTE_COUNT = 79
_TOKEN_RE = re.compile(r"\{[A-Za-z]+\}")


def dte_byte(index: int) -> int:
    if not 0 <= index < DTE_COUNT:
        raise ValueError(index)
    return 0xA0 + index if index < 64 else 0xF0 + (index - 64)


def dte_index(b: int):
    if 0xA0 <= b <= 0xDF:
        return b - 0xA0
    if 0xF0 <= b <= 0xFE:
        return 64 + (b - 0xF0)
    return None


def is_sjis_lead(b: int) -> bool:
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def _encode_ascii_run(s: str, dte) -> bytes:
    if not dte:
        return s.encode("ascii")
    out = bytearray()
    i = 0
    entries = sorted(((e, k) for k, e in enumerate(dte) if e), key=lambda t: -len(t[0]))
    while i < len(s):
        for e, k in entries:
            if s.startswith(e, i):
                out.append(dte_byte(k))
                i += len(e)
                break
        else:
            out.append(ord(s[i]))
            i += 1
    return bytes(out)


# The patch's own button icons (tools/patch/font/icons12.txt, drawn by
# text_vwf.c pt_sjis_rows): name -> (the private-use character a string
# spells it with, its two-byte code in the unassigned 0xEF40.. block).
ICONS = {
    "mouse_left": ("\ue040", b"\xef\x40"),
    "mouse_right": ("\ue041", b"\xef\x41"),
}
MOUSE_LEFT = ICONS["mouse_left"][0]
MOUSE_RIGHT = ICONS["mouse_right"][0]
ICON_BYTES = {ch: code for ch, code in ICONS.values()}
ICON_CHARS = {code: ch for ch, code in ICONS.values()}

# characters an ENGLISH string may carry as Shift-JIS pairs (the renderer
# draws them from the kanji pool): the 14-px ideographic space the yes/no
# lines pad with, and the button glyphs (the retail font's, and the
# patch's own icons).  Anything else in a string with Latin letters is a
# translation leftover that would draw as a pool glyph or the missing-glyph
# box: encode() refuses it.
LATIN_SJIS_OK = set("　○×△□") | set(ICON_BYTES)


def render_problems(text: str, enc: bytes, dte=None):
    """what the patched renderer could not draw faithfully: a byte that
    falls back to '?' (text_vwf.c pt_ascii_rows / pt_char_width), a DTE
    code outside the table, or a Japanese character inside English"""
    probs = []
    i = 0
    while i < len(enc):
        b = enc[i]
        if 0x01 <= b <= 0x1F or 0x20 <= b <= 0x7E:
            i += 1
            continue
        k = dte_index(b)
        if k is not None:
            if dte is None or k >= min(len(dte), DTE_COUNT) or not dte[k] or \
                    not all(0x20 <= ord(c) <= 0x7E for c in dte[k]):
                probs.append(f"DTE byte 0x{b:02X} has no ASCII expansion")
            i += 1
            continue
        if is_sjis_lead(b) and i + 1 < len(enc) and (0x40 <= enc[i + 1] <= 0x7E or 0x80 <= enc[i + 1] <= 0xFC):
            i += 2
            continue
        probs.append(f"byte 0x{b:02X} at {i} draws as the '?' fallback")
        i += 1
    if any("a" <= c.lower() <= "z" for c in text):
        bad = sorted({c for c in text if ord(c) > 0x7E and c not in LATIN_SJIS_OK and c != "\n"})
        if bad:
            probs.append(f"Japanese characters in an English string: {''.join(bad)}")
    return probs


def encode(text: str, dte=None, check=True) -> bytes:
    """Sheet string ({tokens}, ASCII, Japanese) -> patch bytes (no NUL).
    With check (the default) a string the renderer would draw with a
    fallback glyph raises ValueError (render_problems)."""
    enc = _encode(text, dte)
    if check:
        probs = render_problems(text, enc, dte)
        if probs:
            raise ValueError(f"{text!r}: " + "; ".join(probs))
    return enc


def _encode(text: str, dte=None) -> bytes:
    out = bytearray()
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        out += _encode_segment(text[pos:m.start()], dte)
        tok = m.group(0)
        if tok not in TOKENS:
            raise ValueError(f"unknown token {tok} in {text!r}")
        out.append(TOKENS[tok])
        pos = m.end()
    out += _encode_segment(text[pos:], dte)
    return bytes(out)


def _encode_segment(seg: str, dte) -> bytes:
    out = bytearray()
    run = ""
    for ch in seg:
        if 0x20 <= ord(ch) <= 0x7E:
            run += ch
            continue
        if run:
            out += _encode_ascii_run(run, dte)
            run = ""
        if ch == "\n":
            out.append(0x01)
            continue
        if ch in ICON_BYTES:
            out += ICON_BYTES[ch]
            continue
        sj = ch.encode("shift_jis")
        if len(sj) != 2 or not is_sjis_lead(sj[0]):
            raise ValueError(f"character {ch!r} is not representable (needs a "
                             f"two-byte Shift-JIS code)")
        out += sj
    if run:
        out += _encode_ascii_run(run, dte)
    return bytes(out)


def retail_to_patch(raw: bytes) -> bytes:
    """Rewrite a RETAIL Shift-JIS string's command letters (at lead positions)
    to the patch control bytes, leaving every two-byte pair alone.  This is
    what the injector applies to UNTRANSLATED strings of a patched
    container so the patched parsers (which only honour bytes < 0x20) still
    see the breaks and name tokens."""
    out = bytearray()
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0:
            break
        if is_sjis_lead(b) and i + 1 < len(raw) and raw[i + 1] != 0:
            out += raw[i:i + 2]
            i += 2
            continue
        ch = chr(b)
        if ch in RETAIL_LETTERS:
            out.append(RETAIL_LETTERS[ch])
        else:
            out.append(b)
        i += 1
    return bytes(out)


def decode(data: bytes, dte=None) -> str:
    out = []
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0:
            break
        if b in TOKEN_BY_BYTE:
            out.append(TOKEN_BY_BYTE[b])
            i += 1
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
            i += 1
        elif dte_index(b) is not None:
            k = dte_index(b)
            out.append((dte[k] if dte and k < len(dte) and dte[k] else "{?}"))
            i += 1
        elif bytes(data[i:i + 2]) in ICON_CHARS:
            out.append(ICON_CHARS[bytes(data[i:i + 2])])
            i += 2
        elif is_sjis_lead(b) and i + 1 < len(data):
            out.append(data[i:i + 2].decode("shift_jis", "replace"))
            i += 2
        else:
            out.append(f"{{x{b:02X}}}")
            i += 1
    return "".join(out)


_FONT = None


def font():
    global _FONT
    if _FONT is None:
        import fontgen
        _FONT = fontgen.parse(fontgen.DEFAULT_SRC)
    return _FONT


def width(text: str, sjis_adv: int = 14) -> int:
    """Pixel width of one line (tokens count as 0; they are expanded by the
    engine, so measure after expansion when it matters)."""
    g = font()
    w = 0
    for seg in _TOKEN_RE.split(text):
        for ch in seg:
            if 0x20 <= ord(ch) <= 0x7E:
                w += g.get(ch, g["?"])[0]
            else:
                w += sjis_adv
    return w


def wrap(text: str, max_px: int) -> str:
    """Greedy word wrap of an ASCII line to max_px, inserting {br}."""
    words = text.split(" ")
    lines = []
    cur = ""
    for wd in words:
        cand = wd if not cur else cur + " " + wd
        if width(cand) <= max_px or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = wd
    lines.append(cur)
    return "{br}".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?")
    ap.add_argument("--width", action="store_true")
    ap.add_argument("--wrap", type=int, metavar="PX")
    a = ap.parse_args()
    if a.text is None:
        ap.print_help()
    elif a.width:
        print(width(a.text))
    elif a.wrap:
        print(wrap(a.text, a.wrap))
    else:
        print(encode(a.text).hex())
