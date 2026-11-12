#!/usr/bin/env python3
"""soak_test.py - long-run robustness checks for a patched disc (headless).

Drives the reference emulator regtest host (tools/patch/regtest_screens.py; the
host built with the local input patch, pc/tools/refemu.py) at full
emulation speed.  Two modes:

  memcard   save / reset / load round trip on a real card file:
            boot -> album + name entry -> prologue -> calendar -> the night
            room's Save/Load icon -> Save to file 1 (overwriting the album's
            new game) -> power off; boot again with the same card -> title ->
            file select -> Load file 1 -> the night room -> Save to file 2.
            PASS when file 1 and file 2 hold the same save block (the
            checksummed slot record of save_game_set.c) and every step
            reached the screen it should.

  soak      random but valid play: from a calendar save state, segments of
            N frames with seeded random input (Circle presses, pointer
            moves, a few Cross / Triangle / Start), forever re-seeded per
            segment; after every segment the step block, the date and the
            whole RAM are read back.  FAILS on a hang (step block AND date
            AND screen unchanged for --stall segments), on a write into the
            patch module's code/rodata or string pool, or on a change of the
            retail kanji glyphs the module keeps, or on a write into an
            extra module region / a poison test build's trap words (the
            region map comes from the build report).  Writes <out>/soak.json and a contact sheet
            per segment.

  python3 tools/patch/soak_test.py memcard --disc build/patch/iso/patched_disc.cue
  python3 tools/patch/soak_test.py soak --disc build/patch/iso/patched_disc.cue \
      --report build/patch/english.report.json --segments 40 --frames 20000

Pad masks are regtest button bits (regtest_screens.py BUTTONS).  Every
input is expanded to per-frame presses with -inputhold 1, so a hold of N
frames moves the free pointer exactly 3*N pixels.
"""
import argparse
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
import regtest_screens as rs                            # noqa: E402

UP, DOWN, LEFT, RIGHT = rs.UP, rs.DOWN, rs.LEFT, rs.RIGHT
CIRCLE, CROSS, TRIANGLE, START = rs.CIRCLE, rs.CROSS, rs.TRIANGLE, rs.START
RAM_BASE = 0x80000000
STEP = 0x800EF860          # D_800EF860 counter, step_counter, now_step.. (16 B)
DATE = 0x800EE79E          # now_year, now_month, now_day
CARD_SIZE = 128 * 1024


def expand(events):
    """[(frame, mask[, length])] -> per-frame presses (hold 1).  A tap is
    4 frames (what the stage routes used with -inputhold 4)."""
    out = {}
    for ev in events:
        f, m = ev[0], ev[1]
        n = ev[2] if len(ev) > 2 else 4
        for k in range(f, f + n):
            out[k] = out.get(k, 0) | m
    return sorted(out.items())


def route_events(fn, upto):
    """a regtest_screens stage route (hold-4 presses every 4 frames) as
    events, cut at frame `upto`"""
    return [(f, m, 4) for f, m in fn() if f < upto]


def run(disc, frames, out, events, load=None, save=None, memcard=None,
        dumpram=None, interval=None, ppf=False, pokes=()):
    extra = []
    if memcard:
        extra += ["-memcard", str(Path(memcard).resolve())]
    if dumpram:
        extra += ["-dumpram", str(dumpram)]
    if ppf:
        extra += ["-ppf"]
    rc, hx = rs.run(Path(disc), frames, Path(out), expand(events), load=load,
                    save=save, interval=interval or frames, hold=1,
                    memdumps=[(STEP, 16, "step"), (DATE, 3, "date")],
                    extra=extra, pokes=pokes)
    return rc, hx


def blank_card(path: Path):
    import debug_memcard
    path.write_bytes(bytes(debug_memcard.blank_card()))


def card_files(path: Path):
    """{name: bytes} of the files on a raw 128 KB card"""
    d = path.read_bytes()
    files = {}
    for i in range(1, 16):
        fr = d[i * 128:(i + 1) * 128]
        state = struct.unpack_from("<I", fr, 0)[0]
        if state != 0x51:                       # first block of a file
            continue
        size = struct.unpack_from("<I", fr, 4)[0]
        name = fr[10:30].split(b"\0")[0].decode("ascii", "replace")
        data = bytearray()
        blk = i
        while True:
            data += d[blk * 8192:(blk + 1) * 8192]
            nxt = struct.unpack_from("<H", d, blk * 128 + 8)[0]
            if nxt == 0xFFFF or len(data) >= size:
                break
            blk = nxt + 1
        files[name] = bytes(data[:size])
    return files


# --- memcard round trip -----------------------------------------------------

NIGHT = 25240              # boot frame of the night room (calendar route)
PTR_REST = (-116, -10)     # the free pointer where the calendar route leaves it
PTR_LOADED = (-130, -11)   # where it sits after Load from the file select
CLIPBOARD = (-90, 31)      # night room: the Save/Load icon (weekday grid c3 r5)
SAVE_BTN = (-67, -10)      # "Save" on the Save/Load page
SLOTS = {1: (-122, -59), 2: (-122, -43)}   # file grid, column 1


def to_night_events():
    """boot -> ... -> the Sunday room (April 23) -> rest -> the night room
    ("What do I do from tomorrow?"), English and retail discs alike"""
    ev = route_events(rs.route_calendar, 24560)
    ev.append((25070, CIRCLE))         # holiday room: "stay home" (pointer rest)
    return ev


def move(t, a, b):
    """events that walk the pointer from a to b (3 px per held frame);
    returns (events, frame after the walk)"""
    ev = []
    dx, dy = b[0] - a[0], b[1] - a[1]
    for d, pos, neg in ((dx, RIGHT, LEFT), (dy, DOWN, UP)):
        n = round(abs(d) / 3)
        if n:
            ev.append((t, pos if d > 0 else neg, n))
            t += n + 5
    return ev, t


def save_events(t0, start, slot):
    """from the night room at t0 (pointer at `start`): clipboard icon ->
    "Checking the memory card" -> Save -> file `slot` -> confirm"""
    ev, t = move(t0 + 10, start, CLIPBOARD)
    ev.append((t + 10, CIRCLE))
    e2, t = move(t0 + 600, CLIPBOARD, SAVE_BTN)
    ev += e2 + [(t + 20, CIRCLE)]
    e3, t = move(t0 + 800, SAVE_BTN, SLOTS[slot])
    ev += e3 + [(t0 + 880, CIRCLE), (t0 + 1300, CIRCLE)]
    return ev


def load_events():
    """boot with a card: title -> Game start -> file select (file 1 is
    selected) -> Load -> file 1 -> the night room it was saved in"""
    return [(3030, CIRCLE), (4400, RIGHT, 15), (4420, UP, 20), (4500, CIRCLE),
            (5000, CIRCLE)]


def title_warnings(files: dict):
    """the BIOS card manager draws a save's title (block 0, bytes 4..67)
    with its Shift-JIS font only: report single-byte characters in it"""
    out = []
    for name, data in sorted(files.items()):
        t = data[4:68].split(b"\0")[0]
        i = 0
        while i < len(t):
            if t[i] >= 0x81 and i + 1 < len(t):
                i += 2
                continue
            out.append(f"{name}: title byte 0x{t[i]:02x} at {i} is not "
                       f"Shift-JIS ({t.decode('shift_jis', 'replace')!r})")
            break
    return out


def memcard_mode(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    card = out / "card.mcd"
    blank_card(card)
    res = {"disc": str(a.disc), "steps": {}}
    # 1. new game -> night room -> save to file 1, power off
    ev = to_night_events() + save_events(NIGHT, PTR_REST, 1)
    rc, hx = run(a.disc, NIGHT + 2000, out / "save1", ev, memcard=card,
                 dumpram=out / "save1.ram", interval=200, ppf=a.ppf)
    f1 = card_files(card)
    res["steps"]["save1"] = {"rc": rc, "step": hx.get("step"), "date": hx.get("date"),
                             "card_files": sorted(f1)}
    print(f"[memcard] 1 new game + save to file 1: step {hx.get('step', '')[16:]} "
          f"date {hx.get('date')} card {sorted(f1)}")
    # 2. power on again with the same card: load file 1, save to file 2
    t0 = 5700
    ev = load_events() + save_events(t0, PTR_LOADED, 2)
    rc, hx = run(a.disc, t0 + 2000, out / "load_save2", ev, memcard=card,
                 dumpram=out / "save2.ram", interval=100, ppf=a.ppf)
    f2 = card_files(card)
    res["steps"]["load_save2"] = {"rc": rc, "step": hx.get("step"), "date": hx.get("date"),
                                  "card_files": sorted(f2)}
    print(f"[memcard] 2 reset, load file 1, save to file 2: step "
          f"{hx.get('step', '')[16:]} date {hx.get('date')} card {sorted(f2)}")
    fails = []
    n1, n2 = "BISLPS-000651", "BISLPS-000652"
    if n1 not in f2 or n2 not in f2:
        fails.append(f"card lacks {n1} / {n2}: {sorted(f2)}")
    else:
        a1, a2 = f2[n1], f2[n2]
        diff = [i for i in range(min(len(a1), len(a2))) if a1[i] != a2[i]]
        res["file1_vs_file2"] = {"bytes": len(a1), "differing": len(diff),
                                 "offsets": [f"0x{x:x}" for x in diff[:64]]}
        print(f"[memcard] file 1 vs file 2: {len(a1)} bytes, {len(diff)} differ "
              f"{[hex(x) for x in diff[:16]]}")
        if len(a1) != len(a2):
            fails.append("file sizes differ")
        title_end = 4 + len(a1[4:68].split(b"\0")[0])
        other = [x for x in diff if not (title_end - 2 <= x < title_end)]
        if other:
            fails.append(f"file 2 (saved after the reload) differs from file 1 "
                         f"outside the title at {[hex(x) for x in other[:16]]}")
        if f1.get(n1) != a1:
            fails.append("file 1 changed between the first session and the second")
    res["failures"] = fails
    res["warnings"] = title_warnings(f2)
    for w in res["warnings"]:
        print(f"[memcard] WARN: {w}")
    for f in fails:
        print(f"[memcard] FAIL: {f}")
    if not fails:
        print("[memcard] OK: saved, reset, loaded and saved again: file 1 == "
              "file 2 apart from the title's file number")
    (out / "result.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


# --- soak ----------------------------------------------------------------------

def patch_regions(report_path: Path):
    """(immutable ranges, mutable ranges) of the patch module from a build
    report: code+rodata and the string pool (DTE strings, relocated names,
    kanji subset) must never change at run time; .data/.bss may."""
    rep = json.loads(report_path.read_text())
    m = rep["module"]
    base = int(m["base"], 16)
    data = int(m.get("data_start", m["bss_start"]), 16)
    end = int(m["end"], 16)
    pool = int(m["string_pool"]["base"], 16)
    pool_n = int(m["string_pool"]["bytes"])
    font_lo = 0x800BD250
    immut = [("module code+rodata", base, data),
             ("string pool", pool, pool + pool_n),
             ("kept kanji glyphs", font_lo, min(pool, base))]
    mut = [("module data+bss", data, end)]
    # module pieces linked into dead retail code (build_patched.py extra
    # regions): the loaded part never changes, the .bss tail may
    for r in m.get("extra_regions", []):
        lo = int(r["start"], 16)
        loaded = lo + int(r["loaded_bytes"])
        immut.append((f"extra region 0x{lo:08X}", lo, loaded))
        mut.append((f"extra region 0x{lo:08X} bss", loaded, int(r["used_end"], 16)))
        # the rest of the dead range keeps its retail bytes: nothing may write it
        immut.append((f"extra region 0x{lo:08X} unused tail", int(r["used_end"], 16),
                      int(r["end"], 16)))
    # a poison test build (config/patch/english-poison.json): the trap words
    for r in rep.get("poison_regions", []):
        immut.append((f"poison region {r['start']}", int(r["start"], 16), int(r["end"], 16)))
    return immut, mut


def ram_slice(ram: bytes, lo, hi):
    return ram[lo - RAM_BASE:hi - RAM_BASE]


def exe_slice(exe: bytes, lo, hi):
    off = lo - 0x80041000 + 0x800
    return exe[off:off + (hi - lo)]


# free-pointer targets (pointer coordinates; the pointer clamps to
# x -150.., y -100..100): the room's icon grid (weekday 3 x 5, holiday
# 2 x 5) and the event menu's reply rows (menu2_init: x -128, y 48 / 64)
ICON_X = (-138, -113, -90)
ICON_Y = (-42, -25, -9, 15, 30)
# never the system-settings icon (column 1, row 5): random clicks there flip
# "Menu mode" to a pad cursor and the free-pointer model stops working
# (seen on retail and English alike, 2026-10-09)
NO_TARGET = {(-138, 30)}
MINIGAMES = {0x72, 0x81, 0x82}      # TAIIKU, RPG_BAT, EN_NICHI (now_step)
L1, R1 = 0x0400, 0x0800
REPLIES = ((-116, 52), (-116, 68), (-116, 84))
CLAMP = (-150, -100)


def minigame_events(rng, t0, frames):
    """mini-games read the pad directly (TAIIKU's spoon relay balances with
    L1 / R1, the races and battles take the d-pad and Circle): dense random
    presses of those buttons"""
    ev = []
    t = t0 + 5
    while t < t0 + frames - 20:
        ev.append((t, rng.choice((L1, R1, LEFT, RIGHT, UP, DOWN, CIRCLE, CIRCLE)),
                   rng.randint(2, 20)))
        t += rng.randint(4, 30)
    return ev


def random_events(rng, t0, frames):
    """random but valid play, as actions of 250-700 frames: re-home the free
    pointer in the top-left corner (so it cannot drift into a dead corner
    for good), walk it to a random room icon (70 %) or reply row (30 %),
    press Circle 1-4 times (advance text, take the icon / reply), now and
    then Cross (back out of a menu) or a d-pad nudge"""
    ev = []
    t = t0 + 5
    end = t0 + frames - 20
    while t < end:
        ev.append((t, LEFT, 60))
        ev.append((t, UP, 70))
        t += 75
        if rng.random() < 0.7:
            target = (rng.choice(ICON_X), rng.choice(ICON_Y))
            while target in NO_TARGET:
                target = (rng.choice(ICON_X), rng.choice(ICON_Y))
        else:
            target = rng.choice(REPLIES)
        e, t = move(t, CLAMP, target)
        ev += e
        for _ in range(rng.randint(1, 4)):
            t += rng.randint(30, 120)
            ev.append((t, CIRCLE))
        r = rng.random()
        if r < 0.12:
            t += rng.randint(40, 120)
            ev.append((t, CROSS))
        elif r < 0.20:
            t += 30
            ev.append((t, rng.choice((UP, DOWN, LEFT, RIGHT)), rng.randint(2, 12)))
        t += rng.randint(60, 300)
    return [x for x in ev if x[0] < end]


def soak_mode(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    immut, mut = patch_regions(Path(a.report)) if a.report else ([], [])
    exe = Path(a.exe).read_bytes() if a.exe else None
    state = Path(a.state)
    rng = random.Random(a.seed)
    log = []
    stall = 0
    prev = None
    fails = []
    for seg in range(a.segments):
        nxt = out / f"seg{seg:03d}.state"
        ram = out / "last.ram"
        cur = int(prev[0][:2], 16) if prev and prev[0] else -1
        if cur in MINIGAMES:
            ev = minigame_events(rng, 0, a.frames)
        else:
            ev = random_events(rng, 0, a.frames)
        pokes = []
        if seg == 0 and a.set_date:
            # what the debug selector's MONTH/DAY rows do (now_month, now_day;
            # keep the weekday: pick a date on the same day of the week)
            m, d = (int(x) for x in a.set_date.split("/"))
            pokes = [(2, DATE + 1, bytes([m, d]))]
        rc, hx = run(a.disc, a.frames, out / f"seg{seg:03d}", ev, load=state,
                     save=nxt, dumpram=ram, interval=a.frames // 10, pokes=pokes)
        if not nxt.exists() or not ram.exists():
            fails.append(f"segment {seg}: the host did not finish (rc {rc})")
            break
        r = ram.read_bytes()
        step, date = hx.get("step", ""), hx.get("date", "")
        shots = sorted((out / f"seg{seg:03d}").rglob("frame_*.png"))
        shot_hash = hashlib.sha1(shots[-1].read_bytes()).hexdigest() if shots else ""
        entry = {"segment": seg, "step": step, "date": date, "rc": rc,
                 "last_frame_sha1": shot_hash[:12], "writes": []}
        if exe:
            for name, lo, hi in immut:
                if hi <= lo:
                    continue
                if ram_slice(r, lo, hi) != exe_slice(exe, lo, hi):
                    a_ = ram_slice(r, lo, hi)
                    b_ = exe_slice(exe, lo, hi)
                    diff = [lo + i for i in range(hi - lo) if a_[i] != b_[i]]
                    entry["writes"].append({"region": name, "bytes": len(diff),
                                            "first": f"0x{diff[0]:08X}",
                                            "last": f"0x{diff[-1]:08X}"})
                    fails.append(f"segment {seg}: {len(diff)} bytes written into "
                                 f"the {name} (0x{diff[0]:08X}..0x{diff[-1]:08X})")
        key = (step[16:], date, shot_hash)      # now_step.. + date + screen
        if prev is not None and key == prev:
            stall += 1
        else:
            stall = 0
        prev = key
        entry["stall"] = stall
        if seg and date == log[-1]["date"]:
            entry["same_date_segments"] = log[-1].get("same_date_segments", 0) + 1
        else:
            entry["same_date_segments"] = 0
        if stall >= a.stall:
            fails.append(f"segment {seg}: no progress for {stall} segments "
                         f"(step {step} date {date}): hang?")
        log.append(entry)
        print(f"[soak] seg {seg:3d} step {step[16:30]} date {date} "
              f"stall {stall} writes {len(entry['writes'])}", flush=True)
        state = nxt
        (out / "soak.json").write_text(json.dumps(
            {"disc": str(a.disc), "seed": a.seed, "frames_per_segment": a.frames,
             "segments": log, "failures": fails}, indent=1) + "\n")
        if stall >= a.stall:
            break
        prior = out / f"seg{seg - 2:03d}.state"
        if prior.exists():
            prior.unlink()
            side = rs.state_sidecar(prior)
            if side.exists():
                side.unlink()
    for f in fails:
        print(f"[soak] FAIL: {f}")
    if not fails:
        print(f"[soak] OK: {len(log)} segments x {a.frames} frames, no hang, no "
              f"write into the patch module's immutable ranges")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    m = sub.add_parser("memcard")
    m.add_argument("--disc", required=True)
    m.add_argument("--out", default="build/patch/soak/memcard")
    m.add_argument("--ppf", action="store_true")
    s = sub.add_parser("soak")
    s.add_argument("--disc", required=True)
    s.add_argument("--state", required=True, help="calendar save state of THIS disc")
    s.add_argument("--report", help="the build's <name>.report.json (omit for the "
                                     "retail disc: no module region to check)")
    s.add_argument("--exe", help="the build's SLPS_000.65 (default: beside the report)")
    s.add_argument("--out", default="build/patch/soak/run")
    s.add_argument("--segments", type=int, default=30)
    s.add_argument("--frames", type=int, default=20000)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--stall", type=int, default=3)
    s.add_argument("--set-date", help="M/D: jump the calendar at the start "
                                      "(same weekday as the state's date)")
    a = ap.parse_args()
    if a.mode == "memcard":
        sys.exit(1 if memcard_mode(a)["failures"] else 0)
    else:
        if not a.exe and a.report:
            a.exe = str(Path(a.report).parent / "SLPS_000.65")
        sys.exit(soak_mode(a))


if __name__ == "__main__":
    main()
