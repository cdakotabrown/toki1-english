#!/usr/bin/env python3
"""coverage_campaign.py - the English patch's runtime coverage campaign.

Reaches every text the player can see (heroine events, date spots, phone
calls, scheduled events, endings, mini-games, system flows) in the
the reference emulator regtest host and records, per item of the PLAN
(config/patch/coverage_plan.json):

  reached     the now_step ids the item expects drew English text (the
              drawlog build's per-step counters, src/patch/drawlog/drawlog.c
              DLG2), or the final step block matches `expect_final`
  drawlog     the Japanese strings drawn during the run (the DLG ring,
              cleared at the start of every item so a state's old entries
              do not count), minus the expected padding / button glyphs
  boxes       frames where the renderer drew its missing-glyph box
  sheet       a contact sheet of the DISTINCT frames (near-identical
              consecutive frames dropped) for the eyes
  verdict     the reviewer's reading of the sheet, from
              config/patch/coverage_review.json (ok / defect / note)

The disc is the english-drawlog build (the release English patch + the
drawn-text log; build it with
`tools/patch/build_patched.py config/patch/english-drawlog.json`).  Items
start from power-on or from the save state another item saved, so the plan
is a tree: `boot.title` -> `boot.calendar` -> `base.sun` -> scene items.
States carry the executable: every state is made by this campaign on the
disc under test (a sidecar records the exe SHA1 and a mismatch is refused).

Item fields (plan file):
  id, group, title          identity ("hero.shiori.date.park", ...)
  from                      "boot" or the id of an item with "save": true
  route                     a regtest_screens.py route (title, album, nameent,
                            latin, prologue, calendar) played before `inputs`
  frames, interval          run length and screenshot interval
  inputs                    pad schedule, frames relative to the start:
                            "300-1500/60:CIRCLE,900:START,1000:PARK1"
                            (SELECT START UP RIGHT DOWN LEFT L1 L2 R1 R2
                            TRIANGLE CIRCLE CROSS SQUARE, a hex mask, or
                            PARK1 = park the pointer on the first reply)
  pokes                     ["F:ADDR:HEX", ...] or ["ADDR:HEX"] (frame 5)
  use                       names of poke macros of the plan ("macros")
  type                      [[FRAME, "Text"], [FRAME, "@END"]]: type on the
                            Latin name-entry page (pointer pokes + Circle)
  pointer                   [[FRAME, X, Y]]: put the free pointer there
  goto                      [FRAME, SCENE]: retail goto_step(SCENE)
  girl                      now_girl, written with the goto
  sub, subsub               now_sub_step / now_sub_sub_step written a few
                            frames after the goto (the loader keeps them)
  memcard                   a .mcd for slot 1 (copied per run: the host
                            writes the card back), or "card:NAME" built from
                            the plan's "cards" (blank / zero / full / debug /
                            corrupt + copy of the card an item wrote)
  save                      true: save build/patch/campaign/states/<id>.state
  expect_steps              now_step ids that must draw English text
  expect_final              {"now_step": N} the final step block must match
  notes                     what the item is for / how retail gets there

  coverage_campaign.py [--plan P] [--only ID-PREFIX ...] [--jobs 4]
                       [--disc DISC] [--rescan] [--list]
  -> build/patch/campaign/<id>/{patched_disc/frame_*.png, sheet*.png,
     ram.bin, result.json}, build/patch/campaign/results.{md,json}
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import locate                          # noqa: E402
import regtest_screens as rt                     # noqa: E402
import draw_log                                  # noqa: E402
import textcodec                                 # noqa: E402

PLAN = PATCH_CONFIG / "coverage_plan.json"
REVIEW = PATCH_CONFIG / "coverage_review.json"
OUT = ROOT / "build" / "patch" / "campaign"
STATES = OUT / "states"
DISC = ROOT / "build" / "patch" / "english-drawlog" / "iso" / "patched_disc.cue"
DTE = ROOT / "build" / "patch" / "gen" / "dte.json"
from roots import refemu as _refemu                # noqa: E402
refemu = _refemu()   # pc/tools/refemu.py of the PC port, if present
# the reference emulator's regtest host (not distributed: pc/tools/refemu.py)
REGTEST = Path(refemu.regtest())

BTN = {"SELECT": 0x0001, "START": 0x0008, "UP": 0x0010, "RIGHT": 0x0020,
       "DOWN": 0x0040, "LEFT": 0x0080, "L2": 0x0100, "R2": 0x0200,
       "L1": 0x0400, "R1": 0x0800, "TRIANGLE": 0x1000, "CIRCLE": 0x2000,
       "CROSS": 0x4000, "SQUARE": 0x8000}
NOW_GIRL = 0x800EF6BF
NOW_SUB_STEP = 0x800EF869
RING_BYTES = 20 + 64 * 36 + 1024           # drawlog.c PtLog (DLG3)
MEMDUMPS = [(0x800EF860, 16, "step"), (0x800EE79E, 3, "date"),
            (NOW_GIRL, 1, "girl"), (0x800EF86E, 1, "scene"),
            (0x800EE855, 1, "clubsick")]


def parse_inputs(spec):
    out = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        when, what = item.split(":")
        if what.upper() == "PARK1":
            out += rt.park_on_reply1(int(when))
            continue
        mask = 0
        for part in what.split("+"):
            m = BTN.get(part.upper())
            mask |= m if m is not None else int(part, 16)
        if "-" in when:
            rng, _, step = when.partition("/")
            a, b = rng.split("-")
            out += [(f, mask) for f in range(int(a), int(b), int(step or 4))]
        else:
            out.append((int(when), mask))
    return out


# the English Latin name-entry page (src/patch/main/text_name_ent.c
# pt_latin_keys): 17 blocks of 5 keys, block = col/6 + row*3, a gap column
# after every 5 keys; key (col,row) is drawn at x = -120 + 16*col,
# y = -48 + 16*row (centre-origin) and hit-tested through the free pointer
# D_801271D6 / D_801271DA, which this campaign writes directly
LATIN_KEYS = ["ABCDE", "FGHIJ", "KLMNO", "PQRST", "UVWXY", "Z.-' ",
              "abcde", "fghij", "klmno", "pqrst", "uvwxy", "z,!?:",
              "01234", "56789", "&+=/*", "()[]@", "#<>~^"]
NAME_BUTTONS = {"@END": (-129, 95), "@KANJI": (-136, 63), "@SYM": (-136, 31),
                "@KANA": (-136, -1), "@ABC": (-136, -33),
                "@FAMILY": (-96, -78), "@GIVEN": (-40, -78), "@NICK": (80, -78)}
PTR_X, PTR_Y = 0x801271D6, 0x801271DA


def type_name(frame, text, step=24):
    """pointer pokes + Circle presses that type `text` on the Latin key
    page (or press one of NAME_BUTTONS); returns (pokes, inputs, end frame)"""
    pokes, inputs = [], []
    tokens = [text] if text in NAME_BUTTONS else list(text)
    for ch in tokens:
        if ch in NAME_BUTTONS:
            x, y = NAME_BUTTONS[ch]
        else:
            blk = next(b for b, k in enumerate(LATIN_KEYS) if ch in k)
            key = LATIN_KEYS[blk].index(ch)
            col = (blk % 3) * 6 + key
            row = blk // 3
            x, y = -120 + 16 * col + 9, -48 + 16 * row + 7
        pokes.append((frame, PTR_X, (x & 0xFFFF).to_bytes(2, "little")))
        pokes.append((frame, PTR_Y, (y & 0xFFFF).to_bytes(2, "little")))
        inputs.append((frame + 8, BTN["CIRCLE"]))
        frame += step
    return pokes, inputs, frame


def parse_poke(p, default_frame=5):
    """'ADDR:HEX' (at default_frame), 'F:ADDR:HEX' or 'F1-F2/STEP:ADDR:HEX'
    (the write repeated: a value the game keeps recomputing) -> [(f, a, d)]"""
    parts = p.split(":")
    if len(parts) == 2:
        parts = [str(default_frame)] + parts
    f, addr, data = parts
    if "-" in f:
        rng, _, step = f.partition("/")
        a, b = rng.split("-")
        frames = range(int(a), int(b), int(step or 10))
    else:
        frames = [int(f)]
    return [(fr, int(addr, 16), bytes.fromhex(data)) for fr in frames]


def box_glyphs(png):
    """the renderer's missing-glyph boxes in a frame (scene_sweep.box_glyphs,
    vectorised): a 9x9 bright outline with a bright main diagonal, a dark
    interior otherwise, dark on both sides of the top row"""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    b = (a[:, :, 0] > 150) & (a[:, :, 1] > 150) & (a[:, :, 2] > 120)
    h, w = b.shape
    if h < 10 or w < 11:
        return 0
    H, W = h - 9, w - 10                        # anchors y < h-9, 1 <= x < w-10

    def at(dy, dx):                             # b[y+dy, x+dx] for every anchor
        return b[dy:dy + H, 1 + dx:1 + dx + W]
    ok = at(0, 0) & ~at(0, -1) & ~at(0, 9)
    for i in range(9):
        ok &= at(0, i) & at(8, i)
    for j in range(1, 8):
        ok &= at(j, 0) & at(j, 8) & at(j, j)
    for j in range(2, 7):
        for i in range(2, 7):
            if i != j:
                ok &= ~at(j, i)
    return int(ok.sum())


# memory cards (raw 128 KB images, tools/patch/debug_memcard.py format)
def card_blank():
    import debug_memcard as dm
    return dm.blank_card()


def card_file_block(card, name):
    """block number of the file `name` (bytes) or None"""
    for i in range(1, 16):
        d = card[i * 128:(i + 1) * 128]
        if int.from_bytes(d[0:4], "little") & 0xF0 == 0x50 and d[10:30].rstrip(b"\0") == name:
            return i
    return None


def make_card(spec, item_dir=None):
    """a card image for spec["kind"]: blank (formatted, empty), zero (all
    zero = unformatted), full (15 blocks of another title: no room for the
    system file), debug (Konami's BISLPS-00065F), corrupt (the card an item
    wrote, with save file `file` (0 = system, 1..14 albums) failing both
    record checksums: save_check.c sums bytes +4..+0xEFF of the records at
    +0x200 and +0x1100 against the u32 at +0)"""
    import debug_memcard as dm
    kind = spec["kind"]
    if kind == "zero":
        return bytearray(dm.CARD_SIZE)
    if kind == "blank":
        return card_blank()
    if kind == "debug":
        card = card_blank()
        dm.add_file(card)
        return card
    if kind == "full":
        card = card_blank()
        for n in range(15):
            dm.add_file(card, b"BISLPS-99999" + bytes([0x41 + n]))
        return card
    if kind in ("corrupt", "copy"):
        card = bytearray((item_dir / "card.mcd").read_bytes())
        if kind == "corrupt":
            name = b"BISLPS-00065" + b"0123456789ABCDEF"[int(spec["file"]):int(spec["file"]) + 1]
            blk = card_file_block(card, name)
            if blk is None:
                raise RuntimeError(f"card of {spec['from_item']} has no {name.decode()}")
            for rec in (0x200, 0x1100):
                o = blk * 8192 + rec + 0x10
                card[o] ^= 0x5A
                card[o + 1] ^= 0xA5
        return card
    raise RuntimeError(f"unknown card kind {kind}")


def exe_sha1(disc):
    return rt.disc_exe_sha1(Path(disc))


# the message window band (y 150..224 of the 320x224 frame): the review
# strip of a dialogue item (text.png) is deduplicated and tiled on it only
WINDOW_BAND = (0, 150, 320, 224)
WINDOW_INNER = (24, 158, 296, 212)     # inside the frame (the checkered border scrolls)


def frame_signature(png, crop=None):
    from PIL import Image
    im = Image.open(png).convert("L")
    return im.crop(crop) if crop else im


def distinct_frames(pngs, min_pixels=24, crop=None, masks=()):
    """drop frames that differ from the last kept one in fewer than
    `min_pixels` pixels by more than 48 grey levels (an idle screen, a
    held message); a typed letter or a new line of text is kept.  `masks`
    are frame-coordinate boxes left out of the comparison (the parked
    pointer, which animates)"""
    from PIL import ImageChops, ImageDraw
    kept, last = [], None
    for p in pngs:
        sig = frame_signature(p, crop)
        if masks:
            dr = ImageDraw.Draw(sig)
            ox, oy = (crop[0], crop[1]) if crop else (0, 0)
            for x0, y0, x1, y1 in masks:
                dr.rectangle((x0 - ox, y0 - oy, x1 - ox, y1 - oy), fill=0)
        if last is not None and sig.size == last.size:
            diff = ImageChops.difference(sig, last).point(lambda v: 255 if v > 48 else 0)
            if diff.histogram()[255] < min_pixels:
                continue
        kept.append(p)
        last = sig
    return kept


def contact_sheets(pngs, out_dir, cols=4, per_sheet=24, crop=None, stem="sheet"):
    from PIL import Image, ImageDraw
    sheets = []
    for k in range(0, len(pngs), per_sheet):
        chunk = pngs[k:k + per_sheet]
        w, h = (crop[2] - crop[0], crop[3] - crop[1]) if crop else (320, 224)
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w, rows * (h + 12)), (32, 32, 32))
        d = ImageDraw.Draw(sheet)
        for i, f in enumerate(chunk):
            im = Image.open(f).convert("RGB")
            if crop:
                im = im.crop(crop)
            if im.size != (w, h):
                im = im.resize((w, h))
            x, y = (i % cols) * w, (i // cols) * (h + 12)
            sheet.paste(im, (x, y + 12))
            d.text((x + 2, y), f.stem.replace("frame_", ""), fill=(255, 255, 0))
        name = out_dir / (f"{stem}{len(sheets) + 1}.png" if len(pngs) > per_sheet else f"{stem}.png")
        sheet.save(name)
        sheets.append(str(name.relative_to(ROOT)))
    return sheets


class Campaign:
    def __init__(self, plan, disc, jobs):
        self.plan = plan
        self.disc = Path(disc)
        self.jobs = jobs
        self.items = {it["id"]: it for it in plan["items"]}
        self.macros = plan.get("macros", {})
        self.dte = json.loads(DTE.read_text())["entries"] if DTE.exists() else None
        # the report of the disc's own build (<out>/iso/patched_disc.cue ->
        # <out>/*.report.json): the drawn-text ring exists only in the
        # drawlog build; on any other disc nothing is cleared or decoded
        reps = sorted(self.disc.resolve().parent.parent.glob("*.report.json"))
        syms = json.loads(reps[0].read_text())["module"]["symbols"] if reps else {}
        self.ring = int(syms["pt_draw_log_ring"], 16) if "pt_draw_log_ring" in syms else None
        self.sha1 = exe_sha1(self.disc)
        self.lock = threading.Lock()
        self.done = {}

    def state_of(self, item_id):
        return STATES / (item_id.replace("/", "__") + ".state")

    def build_cmd(self, it, out):
        frames = int(it.get("frames", 1500))
        interval = int(it.get("interval", 100))
        inputs = parse_inputs(it.get("inputs", ""))
        if it.get("route"):                     # a regtest_screens.py route from power-on
            inputs = rt.STAGES[it["route"]][0]() + inputs
        pokes = []
        for f, text in it.get("type", []):     # name entry: [[frame, "Text" or "@END"], ...]
            tp, ti, _ = type_name(int(f), text)
            pokes += tp
            inputs += ti
        for f, x, y in it.get("pointer", []):  # [[frame, x, y]]: park the free pointer
            pokes.append((int(f), PTR_X, (int(x) & 0xFFFF).to_bytes(2, "little")))
            pokes.append((int(f), PTR_Y, (int(y) & 0xFFFF).to_bytes(2, "little")))
        # clear the drawn-text ring: a state carries the previous run's log
        if self.ring is not None:
            pokes.append((1, self.ring, bytes(RING_BYTES)))
        for name in it.get("use", []):
            for p in self.macros[name]:
                pokes += parse_poke(p, it.get("poke_frame", 5))
        for p in it.get("pokes", []):
            pokes += parse_poke(p, it.get("poke_frame", 5))
        if it.get("schedule"):
            # let the real day dispatcher fire the scene: one schedule
            # entry {type, a, b, c} at schedule_buf 0x800EEDFC (cursor
            # 0x800EEE7C, day_cnt, day_flag cleared), then now_step = 49
            # (schedule_day_main posts the scene and sets D_8012B1B0/B4 and
            # now_girl itself)
            f = int(it.get("schedule_frame", 10))
            ent = list(it["schedule"]) + [0] * (4 - len(it["schedule"]))
            pokes.append((f, 0x800EEDFC, bytes(v & 0xFF for v in ent)))
            pokes.append((f, 0x800EEE7C, bytes(3)))
            pokes.append((f, 0x800EF85C, bytes(16)))
            pokes.append((f, 0x800EF868, bytes([49, 0, 0, 0, 0, 0])))
        if it.get("step") is not None:          # a main-binary scene id: now_step = N directly
            f = int(it.get("step_frame", 10))
            pokes.append((f, 0x800EF85C, bytes(16)))
            pokes.append((f, 0x800EF868, bytes([int(it["step"]), int(it.get("sub") or 0),
                                                int(it.get("subsub") or 0), 0, 0, 0])))
        if it.get("goto"):
            f, scene = it["goto"]
            pokes += rt.goto_step_pokes(int(f), int(scene))
            if it.get("girl") is not None:
                pokes.append((int(f), NOW_GIRL, bytes([int(it["girl"])])))
            if it.get("sub") is not None or it.get("subsub") is not None:
                sf = int(it.get("sub_frame", int(f) + 1))
                pokes.append((sf, NOW_SUB_STEP, bytes([int(it.get("sub") or 0) & 0xFF,
                                                       int(it.get("subsub") or 0) & 0xFF])))
        cmd = [str(REGTEST), "-frames", str(frames), "-console",
               "-inputhold", str(it.get("hold", 4)), "-dumpdir", str(out),
               "-dumpinterval", str(interval), "-dumpram", str(out / "ram.bin")]
        src = it.get("from", "boot")
        if src != "boot":
            st = self.state_of(src)
            side = st.with_suffix(".state.exe.sha1")
            if not st.exists():
                raise RuntimeError(f"state {st.name} missing (run item {src} first)")
            if side.read_text().split()[0] != self.sha1:
                raise RuntimeError(f"state {st.name} was made on another exe: re-run {src}")
            cmd += ["-loadstate", str(st)]
        if it.get("save"):
            STATES.mkdir(parents=True, exist_ok=True)
            cmd += ["-savestate", str(self.state_of(it["id"]))]
        if it.get("memcard"):
            local = out / "card.mcd"
            mc = it["memcard"]
            if mc.startswith("card:"):
                spec = self.plan.get("cards", {})[mc[5:]]
                src_dir = OUT / spec["from_item"] if spec.get("from_item") else None
                local.write_bytes(bytes(make_card(spec, src_dir)))
            else:
                shutil.copyfile(locate(mc), local)
            cmd += ["-memcard", str(local)]
        for f, m in sorted(inputs):
            cmd += ["-input", f"{f}:{m:04X}"]
        for f, addr, data in pokes:
            cmd += ["-poke", f"{f}:{addr:X}:{data.hex()}"]
        for addr, size, label in MEMDUMPS + [(int(a, 16), int(n), l) for a, n, l in it.get("memdump", [])]:
            cmd += ["-memdump", f"{addr:X}", str(size), label]
        cmd += ["--", str(self.disc)]
        return cmd

    def run_item(self, it, rescan=False):
        out = OUT / it["id"]
        rc = None
        hexes = {}
        if not rescan:
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            cmd = self.build_cmd(it, out)
            r = subprocess.run(cmd, capture_output=True, text=True)
            log = r.stdout + r.stderr
            (out / "run.log").write_text(log)
            rc = r.returncode
            for line in log.splitlines():
                if "Memory Hex" in line:
                    body = line.split("Memory Hex ", 1)[1]
                    hexes[body.split(" ")[0]] = body.rsplit(": ", 1)[1].strip().split("\x1b")[0]
            (out / "memdumps.json").write_text(json.dumps(hexes, indent=1) + "\n")
            if it.get("save") and self.state_of(it["id"]).exists():
                self.state_of(it["id"]).with_suffix(".state.exe.sha1").write_text(
                    f"{self.sha1}  {self.disc.name}\n")
        else:
            p = out / "memdumps.json"
            hexes = json.loads(p.read_text()) if p.exists() else {}
        return self.evaluate(it, out, rc, hexes)

    def evaluate(self, it, out, rc, hexes):
        res = {"id": it["id"], "group": it.get("group", ""), "title": it.get("title", ""),
               "rc": rc}
        st = bytes.fromhex(hexes["step"]) if hexes.get("step") else b""
        if len(st) >= 16:
            res["final"] = {"now_step": st[8], "now_sub_step": st[9], "now_sub_sub_step": st[10]}
        if hexes.get("date"):
            d = bytes.fromhex(hexes["date"])
            res["final_date"] = f"{d[0]}-{d[1]:02d}-{d[2]:02d}"
        if hexes.get("girl"):
            res["final_girl"] = int(hexes["girl"], 16)
        ram = out / "ram.bin"
        jp = []
        expected = []
        if ram.exists():
            parsed = draw_log.parse(ram.read_bytes(), self.dte)
            if parsed:
                res["english_draws"] = parsed["english_draws"]
                res["step_english"] = parsed["step_english_draws"]
                res["step_japanese"] = parsed["step_japanese_draws"]
                ok = set("　○×△□")
                for e in parsed["entries"]:
                    chars = {c for c in e["text"] if ord(c) > 0x7E}
                    if chars and chars <= ok:
                        continue
                    if any(t in e["text"] for t in it.get("allow_japanese", [])):
                        continue
                    a = int(e["addr"], 16)
                    why = next((x["why"] for x in self.plan.get("expected_japanese", [])
                                if e["step"] == x["step"] and
                                int(x["from"], 16) <= a < int(x["to"], 16)), None)
                    if why:
                        expected.append(dict(e, why=why))
                        continue
                    jp.append({k: e[k] for k in ("scene", "step", "sub", "x", "y", "addr",
                                                 "source", "text")})
        res["japanese"] = jp
        res["japanese_expected"] = len(expected)
        # reached?
        exp = it.get("expect_steps", [])
        se = res.get("step_english", {})
        missing = [s for s in exp if not se.get(s)]
        reached = not missing
        if it.get("expect_final"):
            fin = res.get("final", {})
            reached = reached and all(fin.get(k) == v for k, v in it["expect_final"].items())
        for label, expected_text in it.get("expect_memdump_text", {}).items():
            raw = bytes.fromhex(hexes.get(label, ""))
            actual = textcodec.decode(raw, self.dte) if raw else ""
            res.setdefault("memdump_text", {})[label] = actual
            reached = reached and actual == expected_text
        for step, minimum in it.get("min_step_english", {}).items():
            reached = reached and se.get(int(step), 0) >= minimum
        res["reached"] = reached if (exp or it.get("expect_final") or
                                     it.get("expect_memdump_text") or it.get("min_step_english")) else None
        res["missing_steps"] = missing
        # frames
        pngs = sorted(out.rglob("frame_*.png"))
        kept = distinct_frames(pngs) if pngs else []
        res["frames"] = len(pngs)
        res["distinct_frames"] = len(kept)
        res["box_frames"] = [p.stem.replace("frame_", "") for p in kept if box_glyphs(p)]
        for old in list(out.glob("sheet*.png")) + list(out.glob("text*.png")):
            old.unlink()
        res["sheets"] = contact_sheets(kept, out) if kept else []
        # the review strip: the message window of every frame whose window
        # changed, 4 x 16 per image
        # the parked pointer (its hot spot is the top-left of a ~24x18 hand)
        masks = [(160 + int(x) - 36, 112 + int(y) - 10, 160 + int(x) + 30, 112 + int(y) + 22)
                 for _, x, y in it.get("pointer", [])]
        band = distinct_frames(pngs, crop=WINDOW_INNER, masks=masks) if pngs else []
        res["text_sheets"] = contact_sheets(band, out, per_sheet=64, crop=WINDOW_BAND,
                                            stem="text") if band else []
        (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
        return res

    def deps(self, i):
        """the items item i needs first: its state (`from`) and the item
        whose written card its memcard is derived from"""
        it = self.items[i]
        out = [it.get("from", "boot")]
        mc = it.get("memcard", "")
        if mc.startswith("card:"):
            spec = self.plan.get("cards", {}).get(mc[5:], {})
            if spec.get("from_item"):
                out.append(spec["from_item"])
        return [d for d in out if d != "boot"]

    def order(self, ids):
        """items in dependency order (a `from` item before its children)"""
        seen, out = set(), []

        def visit(i):
            if i in seen or i == "boot":
                return
            seen.add(i)
            for src in self.deps(i):
                if src in ids:
                    visit(src)
            out.append(i)
        for i in ids:
            visit(i)
        return out

    def run(self, ids, rescan=False):
        ids = self.order(ids)
        results = {}
        pending = list(ids)
        running = {}
        with ThreadPoolExecutor(max_workers=self.jobs) as ex:
            while pending or running:
                for i in list(pending):
                    if any(d in pending or d in running for d in self.deps(i)):
                        continue
                    if len(running) >= self.jobs:
                        break
                    pending.remove(i)
                    running[i] = ex.submit(self.run_item, self.items[i], rescan)
                if running:
                    wait(list(running.values()), return_when=FIRST_COMPLETED)
                done = [i for i, f in running.items() if f.done()]
                for i in done:
                    f = running.pop(i)
                    try:
                        r = f.result()
                    except Exception as e:      # noqa: BLE001
                        r = {"id": i, "error": str(e), "group": self.items[i].get("group", ""),
                             "title": self.items[i].get("title", ""), "japanese": [],
                             "reached": False, "sheets": [], "box_frames": []}
                    results[i] = r
                    print(f"[campaign] {i:40s} reached={r.get('reached')} "
                          f"jp={len(r.get('japanese', []))} boxes={len(r.get('box_frames', []))} "
                          f"final={r.get('final')} {r.get('error', '')}")
        return results


def write_results(plan, results):
    review = json.loads(REVIEW.read_text()) if REVIEW.exists() else {}
    allres = {}
    old = OUT / "results.json"
    if old.exists():
        allres = {r["id"]: r for r in json.loads(old.read_text())}
    allres.update(results)
    order = [it["id"] for it in plan["items"] if it["id"] in allres]
    rows = [allres[i] for i in order]
    old.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    md = ["| item | what | reached | English draws (step:n) | Japanese drawn | box frames | verdict | sheet |",
          "|---|---|---|---|---:|---:|---|---|"]
    for r in rows:
        rv = review.get(r["id"], {})
        steps = ", ".join(f"{s}:{n}" for s, n in sorted((int(k), v) for k, v in
                                                           r.get("step_english", {}).items()))
        reached = {True: "yes", False: "NO", None: "-"}[r.get("reached")]
        verdict = rv.get("verdict", "unreviewed")
        if rv.get("note"):
            verdict += ": " + rv["note"]
        sheet = r["sheets"][0] if r.get("sheets") else ""
        md.append(f"| `{r['id']}` | {r.get('title', '')} | {reached} | {steps} | "
                  f"{len(r.get('japanese', []))} | {len(r.get('box_frames', []))} | "
                  f"{verdict.replace('|', '/')} | `{sheet}` |")
    (OUT / "results.md").write_text("\n".join(md) + "\n")
    jp_lines = []
    for r in rows:
        for e in r.get("japanese", []):
            jp_lines.append(f"{r['id']}: scene {e['scene']} step {e['step']}/{e['sub']} "
                            f"({e['x']},{e['y']}) {e['addr']} {e['source']}  {e['text']}")
    (OUT / "japanese.txt").write_text("\n".join(jp_lines) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=str(PLAN))
    ap.add_argument("--disc", default=str(DISC))
    ap.add_argument("--out", help="output directory (default build/patch/campaign; give another "
                                  "one for another disc: states are per disc)")
    ap.add_argument("--only", nargs="*", help="item ids or id prefixes")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--rescan", action="store_true", help="re-evaluate the dumped runs only")
    ap.add_argument("--with-deps", action="store_true",
                    help="also re-run the items the selected ones start from")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--adhoc", help="run one item given as JSON under build/patch/campaign/adhoc/ "
                                    "(not written to results.md), e.g. "
                                    "'{\"id\": \"x\", \"from\": \"boot.sun\", \"frames\": 600, "
                                    "\"inputs\": \"10:CIRCLE\"}'")
    a = ap.parse_args()
    global OUT, STATES
    if a.out:
        OUT = Path(a.out).resolve()
        STATES = OUT / "states"
    plan = json.loads(Path(a.plan).read_text())
    if a.adhoc:
        it = json.loads(a.adhoc)
        it["id"] = "adhoc/" + it["id"]
        plan["items"].append(it)
        camp = Campaign(plan, a.disc, 1)
        r = camp.run_item(it)
        print(json.dumps({k: r.get(k) for k in ("final", "final_date", "final_girl", "step_english",
                                                 "step_japanese", "japanese", "box_frames",
                                                 "sheets", "reached")}, ensure_ascii=False, indent=1))
        return
    if a.list:
        for it in plan["items"]:
            print(f"{it['id']:44s} from={it.get('from', 'boot'):24s} {it.get('title', '')}")
        return
    if not REGTEST.exists():
        sys.exit(refemu.explain("coverage_campaign"))
    camp = Campaign(plan, a.disc, a.jobs)
    ids = [it["id"] for it in plan["items"]]
    if a.only:
        sel = [i for i in ids if any(i == p or i.startswith(p) for p in a.only)]
        if a.with_deps:
            extra = set(sel)
            pending = list(sel)
            while pending:
                for dep in camp.deps(pending.pop()):
                    if dep not in extra:
                        extra.add(dep)
                        pending.append(dep)
            sel = [i for i in ids if i in extra]
        ids = sel
    results = camp.run(ids, a.rescan)
    rows = write_results(plan, results)
    n_reach = sum(1 for r in rows if r.get("reached"))
    n_exp = sum(1 for r in rows if r.get("reached") is not None)
    n_jp = sum(len(r.get("japanese", [])) for r in rows)
    print(f"[campaign] {len(rows)} items in results.md: reached {n_reach}/{n_exp} with an "
          f"expectation, {n_jp} Japanese strings drawn -> {(OUT / 'results.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
