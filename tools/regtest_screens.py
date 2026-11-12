#!/usr/bin/env python3
"""regtest_screens.py - scripted headless runs that reach the game's text
screens, for the English patch (and the retail disc, as the reference).

Uses the reference emulator's regtest host with its local input patch (pc/tools/refemu.py)
applied (-input F:MASK, -inputhold, -loadstate, -savestate, -memdump).

Route (mapped on the retail disc, 2026-10-08; frame numbers are from boot
at 60 fps and hold for both discs):

  ~2700  title screen up (it idles into the attract opening at ~3725)
   3030  Circle on "Game start" -> file select (NAME_ENT, 14-px cells)
  ~4500  "no data, create an album?"      4560 Circle = yes
  ~4800  "which slot?": the free pointer (D_801271D6/DA, 3 px per held
         frame, rests at (64,100)) is moved Left 60 f / Up 28 f onto slot 1
         (menu_check hover D_800EF7F3 = 0); 5000 Circle
  ~5200  system-file explanation           5300 Circle = yes
  ~5500  "creating album 1 + system file"  (5600 Circle is harmless)
  ~6000  NAME ENTRY (16-px cells). Pointer clamped to the bottom-left
         "End" button (Left 80 f, Down 60 f), 6500 Circle -> defaults are
         filled in -> "Is this OK?" card; Right 44 f puts the pointer on
         "Yes", 6740 Circle
  ~6900  birthday / blood type screen for Shiori: 7100 Start skips it ->
         her card, 7400 Circle = yes
  ~7600  PROLOGUE: field dialogue window (gnsx + sndisp path),
         auto-advancing with voice.  No input needed.

Screenshots: build/patch/shots/<tag>_<stage>/<disc>/frame_NNNNN.png (not
committed).  States: build/patch/states/<tag>_<stage>.state.

Event choices (2026-10-09).  The choice menu (menu2_init: rows at x=-128,
y=48/64, 252x16, menu slot 1) is answered through the FREE POINTER in cursor
mode 0 (D_800EF7F2 = 0, the album default): menu_check_1 hit-tests the
pointer D_801271D6/DA STRICTLY inside a row (0 < dx < w, 0 < dy < h), so the
pointer must sit at e.g. (-116, 52..63) for reply 1, then Circle.  The
d-pad moves it 3 px per held frame; "clamp to the bottom (y=100), then Up
for 16 frames" lands on reply 1 from anywhere (probe_choice2).  Watching
sel[0] (0x800EF7F3) was the earlier mistake: the event choice uses slot 1.

Forced scenes (--goto FRAME:SCENE, needs the -poke regtest host): emulate
goto_step(scene) from a calendar-idle state (cal_idle.state) and the
overlay loader brings the scene up.  Verified this way: 82/83/85 SHOUGATU
(83 + poke now_sub_step=2, now_sub_sub_step=28, now_girl=3 at the shrine =
the greeting label), 99 ENDING (epilogue + bad-ending song, sub_step 7),
92 DATE2 karaoke (song menu: pointer to (16,64) then Circle -> lyric page),
128 BUNKA_SD (speech contest roll call), 112 BUNKASAI (+ poke now_sub_step
= 8 at frame 300 for the computer-club visit).

Usage:
  regtest_screens.py --disc build/patch/iso/patched_disc.cue --tag vwf --stage prologue
  regtest_screens.py --disc "disks/<retail>.cue" --tag retail --stage title
  regtest_screens.py --disc DISC --tag probe --load build/patch/states/X.state \
      --frames 400 --inputs "10-100/4:DOWN,110-126/4:UP,200:CIRCLE"
  regtest_screens.py --disc DISC --tag ending --load build/patch/states/cal_idle.state \
      --frames 16000 --goto 10:99 --inputs "600-16000/150:CIRCLE"
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import refemu as _refemu                # noqa: E402
refemu = _refemu()   # pc/tools/refemu.py of the PC port, if present
# the reference emulator's regtest host (not distributed: pc/tools/refemu.py)
REGTEST = Path(refemu.regtest())
STATES = ROOT / "build" / "patch" / "states"
SHOTS = ROOT / "build" / "patch" / "shots"

# pad-1 bits (bit i = the reference emulator's AnalogController::Button i); the game's
# own pad word D_800EF6E0/E8 is byte-swapped (Circle 0x2000 here = 0x20 there)
SELECT, START = 0x0001, 0x0008
UP, RIGHT, DOWN, LEFT = 0x0010, 0x0020, 0x0040, 0x0080
TRIANGLE, CIRCLE, CROSS, SQUARE = 0x1000, 0x2000, 0x4000, 0x8000

PTR = (0x801271D6, 8, "ptr")        # pointer x, y (s16 each)
HOVER = (0x800EF7F3, 1, "hover")    # menu_check sel[0] (ff = none)
# the menu table D_800EE760: row[i][slot] at +3984 (x,y s16; w,h,hit,skip
# u8), cnt[3] at +4240, sel[2] at +4243, chosen[2] at +4245; D_800EF7F2 is
# the cursor MODE (0 = free pointer, hit-tested by menu_check_1; 1 = d-pad
# cursor; set by game_system_init / the album's config byte)
MENU_ROWS = (0x800EF6F0, 64, "rows")
MENU_SEL = (0x800EF7F0, 8, "sel")
# step block: D_800EF860 (s32), step_counter 864 (s32), now_step 868,
# now_sub_step 869, now_sub_sub_step 86A, 86B, 86C, step_mode 86D, scene 86E
STEP = (0x800EF860, 16, "step")
DATE = (0x800EE79E, 3, "date")      # now_year, now_month, now_day
BUTTONS = {"SELECT": SELECT, "START": START, "UP": UP, "RIGHT": RIGHT,
           "DOWN": DOWN, "LEFT": LEFT, "TRIANGLE": TRIANGLE, "CIRCLE": CIRCLE,
           "CROSS": CROSS, "SQUARE": SQUARE}


def parse_inputs(spec: str):
    """'10:CIRCLE,20-80/4:DOWN,300:2000' -> [(frame, mask)]; a range
    F1-F2/STEP schedules a press every STEP frames (a hold with
    -inputhold >= STEP)."""
    out = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        when, what = item.split(":")
        mask = BUTTONS.get(what.upper())
        if mask is None:
            mask = int(what, 16)
        if "-" in when:
            rng, _, step = when.partition("/")
            a, b = rng.split("-")
            out += [(f, mask) for f in range(int(a), int(b), int(step or 4))]
        else:
            out.append((int(when), mask))
    return out


def goto_step_pokes(frame: int, scene: int):
    """The memory writes of retail goto_step(scene) followed by
    step_state_save_and_redirect(): the step block D_800EF85C.. and the
    overlay loader's mode byte, so the next frame loads that scene's
    overlay exactly as the calendar would (the regtest host's -poke).
    D_800EF868 now_step = 2 (overlay load), D_800EF86E = scene."""
    return [
        (frame, 0x800EF85C, bytes(16)),                 # 85C, 860 counters,
                                                       # 864 step_counter, 868..86B
        (frame, 0x800EF868, bytes([2, 0, 0, 0, 0, 0, scene & 0xFF])),
        (frame, 0x800D07AC, bytes(2)),                  # sound_seek_time
        (frame, 0x800BD234, bytes(1)),                  # overlay_load_main mode
    ]


def run(disc, frames, out, inputs=(), load=None, save=None, interval=100,
        hold=4, memdumps=(), extra=(), pokes=()):
    out.mkdir(parents=True, exist_ok=True)
    cmd = [str(REGTEST), "-frames", str(frames), "-console",
           "-inputhold", str(hold), "-dumpdir", str(out),
           "-dumpinterval", str(interval)]
    if load:
        cmd += ["-loadstate", str(load)]
    if save:
        STATES.mkdir(parents=True, exist_ok=True)
        cmd += ["-savestate", str(save)]
    for f, m in sorted(inputs):
        cmd += ["-input", f"{f}:{m:04X}"]
    for f, addr, data in pokes:
        cmd += ["-poke", f"{f}:{addr:X}:{bytes(data).hex()}"]
    for addr, size, label in memdumps:
        cmd += ["-memdump", f"{addr:X}", str(size), label]
    cmd += list(extra) + ["--", str(disc)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    (out / "run.log").write_text(r.stdout + r.stderr)
    hexes = {}
    for line in (r.stdout + r.stderr).splitlines():
        if "Memory Hex" in line:
            body = line.split("Memory Hex ", 1)[1]
            label = body.split(" ")[0]
            hexes[label] = body.rsplit(": ", 1)[1].strip().split("\x1b")[0]
    return r.returncode, hexes


def hold(button, start, frames, step=4):
    """Hold a direction for `frames` frames (a press every `step` frames,
    each held `-inputhold` frames, so the pad stays down continuously)."""
    return [(f, button) for f in range(start, start + frames, step)]


# --- the route, as absolute boot-relative frames -------------------------

def route_title():
    return []


def route_filesel():
    return [(3030, CIRCLE)]


def route_album():
    return (route_filesel() + [(4560, CIRCLE)] + hold(LEFT, 4860, 60)
            + hold(UP, 4930, 28) + [(5000, CIRCLE), (5300, CIRCLE),
                                     (5600, CIRCLE)])


def route_nameent():
    # clamp the pointer to the bottom-left corner (-150,100), then step
    # back onto the "End" button (its box is about x -143..-115, y 88..103):
    # End on the name page -> the player's birthday page (same End button)
    # (the first Circles after the move are sometimes ignored: press until
    # it takes, ~7300; the extra presses land on the birthday page's End,
    # which is the same button).  Start does NOT leave the name page but
    # it does leave the birthday pages (func_80138720: pad bit 0x800).
    return (route_album() + hold(LEFT, 6300, 80) + hold(DOWN, 6400, 60)
            + [(6470, RIGHT), (6480, UP), (6520, CIRCLE), (6700, CIRCLE),
               (6900, CIRCLE), (7300, CIRCLE)]
            + [(8000, START)])


def route_prologue():
    # "Is this OK?" card (~8050): Right 44 f puts the pointer on Yes;
    # Shiori's birthday page (~8350) is skipped with Start; her card: Yes
    return (route_nameent() + hold(RIGHT, 8100, 44) + [(8300, CIRCLE)]
            + [(8700, START), (9000, CIRCLE)])


# --- save states carry the exe: refuse a state from another build ---------

def disc_exe_sha1(disc: Path) -> str:
    """SHA1 of PSX.EXE as stored on the disc image (the text module, its DTE
    table and string pool live in it, so a state saved on another build
    decodes the containers through the wrong table)"""
    import hashlib
    from text_sources import Image
    disc = Path(disc)
    if disc.suffix.lower() == ".cue":       # the track-1 FILE the sheet names
        for line in disc.read_text(errors="replace").splitlines():
            if line.strip().upper().startswith("FILE "):
                disc = disc.parent / line.split('"')[1]
                break
    return hashlib.sha1(Image(disc).read("/PSX.EXE")).hexdigest()


def state_sidecar(state: Path) -> Path:
    return state.with_suffix(state.suffix + ".exe.sha1")


def check_state_matches_disc(state: Path, disc: Path):
    side = state_sidecar(state)
    if not side.exists():
        sys.exit(f"[regtest] {state.name} has no .exe.sha1 sidecar: it predates the "
                 f"stale-state guard; re-make it on this disc (or --allow-stale-state)")
    want = side.read_text().split()[0]
    have = disc_exe_sha1(disc)
    if want != have:
        sys.exit(f"[regtest] {state.name} was saved on a disc whose exe is {want[:12]}, "
                 f"this disc's exe is {have[:12]}: a stale state decodes the injected "
                 f"text through the old DTE table (letter salad); re-make the state "
                 f"on this disc (or --allow-stale-state)")


def park_on_reply1(start):
    """clamp the pointer to the bottom (y=100), then Up for 16 frames: it
    rests at y=52, inside the first reply's hit box (x stays -116)"""
    return hold(DOWN, start, 100) + hold(UP, start + 110, 16)


def route_calendar():
    # through the prologue, then Circle every 150 frames: the classroom
    # event, April 9 .. May 25 (the birthday choice is answered with reply 1
    # because the pointer is parked on it), the gift choice, and on into
    # the calendar (May 28 is a holiday: the "What should I do today?"
    # monologue idles).  ~46,000 frames.
    # The calendar advances when Circle lands on the icon under the pointer's
    # resting spot (-116,-10) (any d-pad use before the first choice derails
    # it), so the pointer is left alone until the birthday choice is up
    # (~37,500 on both discs), parked on reply 1 at 38,000, Circle answers
    # it and the gift choice, then Up 21 frames (63 px) returns it to the
    # icon spot for the calendar.
    inputs = route_prologue() + [(f, CIRCLE) for f in range(13000, 37900, 150)]
    inputs += park_on_reply1(38000) + [(38150, CIRCLE), (38700, CIRCLE)]
    inputs += hold(UP, 39200, 21)
    inputs += [(f, CIRCLE) for f in range(39400, 46000, 150)]
    return inputs


def route_latin():
    # name entry on the English disc (page 0 = Latin keys at 16-px cells:
    # key (col,row) is at x = -120 + 16*col, y = -48 + 16*row; blocks of 5
    # keys with a gap column): clamp top-left (-150,-100), type S U Z on row
    # 1 (x -63 / -15 / 81, y -25), then End (bottom-left), the defaults fill
    # the other fields, "Is this OK?" -> Yes, Shiori's birthday page -> Start.
    return (route_album() + hold(LEFT, 6300, 80) + hold(UP, 6400, 60)
            + hold(RIGHT, 6500, 29) + hold(DOWN, 6540, 25) + [(6600, CIRCLE)]
            + hold(RIGHT, 6650, 16) + [(6700, CIRCLE)]
            + hold(RIGHT, 6750, 32) + [(6800, CIRCLE)]
            + hold(LEFT, 6900, 80) + hold(DOWN, 7000, 60)
            + [(7070, RIGHT), (7080, UP), (7120, CIRCLE), (7300, CIRCLE)]
            + hold(RIGHT, 7500, 44) + [(7600, CIRCLE), (7900, START), (8200, CIRCLE)])


STAGES = {
    # name: (inputs, frames to run, screenshot interval)
    "latin": (route_latin, 8600, 50),
    "title": (route_title, 3000, 300),
    "filesel": (route_filesel, 4700, 100),
    "album": (route_album, 6200, 100),
    "nameent": (route_nameent, 7000, 100),
    "prologue": (route_prologue, 12800, 50),
    "calendar": (route_calendar, 46000, 500),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc", required=True)
    ap.add_argument("--tag", required=True, help="state/screenshot prefix")
    ap.add_argument("--stage", default="prologue", choices=sorted(STAGES))
    ap.add_argument("--frames", type=int, help="override the frame count")
    ap.add_argument("--load", help="start from this save state instead of boot "
                                   "(frames are then relative to the load)")
    ap.add_argument("--inputs", default=None,
                    help="ad-hoc schedule '10:CIRCLE,20-80/4:DOWN,300:2000' "
                         "(replaces the stage's route)")
    ap.add_argument("--interval", type=int, help="screenshot interval")
    ap.add_argument("--hold", type=int, default=4, help="-inputhold")
    ap.add_argument("--memdump", action="append", default=[],
                    help="ADDR:SIZE:LABEL (hex addr)")
    ap.add_argument("--dumpvram", help="write the 1 MB VRAM after the last frame")
    ap.add_argument("--dumpram", help="write the 2 MB RAM after the last frame")
    ap.add_argument("--memcard", help="128 KB .mcd used as the slot-1 card (host -memcard; "
                                      "tools/patch/debug_memcard.py makes the debug one)")
    ap.add_argument("--ppf", action="store_true",
                    help="let the reference emulator apply <disc>.ppf beside the image (host "
                         "-ppf): boots a retail cue + english.ppf through the "
                         "emulator's own PPF reader (tools/patch/verify_ppf.py)")
    ap.add_argument("--allow-stale-state", action="store_true",
                    help="load a state saved on a disc with a different exe")
    ap.add_argument("--poke", action="append", default=[],
                    help="FRAME:ADDR:HEXBYTES written into RAM at that frame")
    ap.add_argument("--goto", action="append", default=[],
                    help="FRAME:SCENE force goto_step(SCENE) at FRAME (needs "
                         "the -poke regtest host)")
    a = ap.parse_args()
    if not REGTEST.exists():
        sys.exit(refemu.explain("regtest_screens"))
    inputs_fn, frames, interval = STAGES[a.stage]
    frames = a.frames or frames
    interval = a.interval or interval
    inputs = parse_inputs(a.inputs) if a.inputs is not None else inputs_fn()
    tag = a.tag if a.inputs is not None else f"{a.tag}_{a.stage}"
    out = SHOTS / tag
    st = STATES / f"{tag}.state"
    dumps = [PTR, HOVER, MENU_ROWS, MENU_SEL, STEP, DATE]
    for d in a.memdump:
        addr, size, label = d.split(":")
        dumps.append((int(addr, 16), int(size), label))
    pokes = []
    for p in a.poke:
        f, addr, data = p.split(":")
        pokes.append((int(f), int(addr, 16), bytes.fromhex(data)))
    for g in a.goto:
        f, scene = g.split(":")
        pokes += goto_step_pokes(int(f), int(scene))
    extra = []
    if a.dumpvram:
        extra += ["-dumpvram", a.dumpvram]
    if a.dumpram:
        extra += ["-dumpram", a.dumpram]
    if a.memcard:
        extra += ["-memcard", str(Path(a.memcard).resolve())]
    if a.ppf:
        extra += ["-ppf"]
    if a.load and not a.allow_stale_state:
        check_state_matches_disc(Path(a.load), Path(a.disc))
    rc, hx = run(Path(a.disc), frames, out, inputs, load=a.load, save=st,
                 interval=interval, hold=a.hold, memdumps=dumps, pokes=pokes,
                 extra=extra)
    if st.exists():
        state_sidecar(st).write_text(disc_exe_sha1(Path(a.disc)) + f"  {Path(a.disc).name}\n")
    print(f"[{tag}] rc={rc} frames={frames} state={st} shots={out}")
    for k, v in hx.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
