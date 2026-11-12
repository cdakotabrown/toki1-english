#!/usr/bin/env python3
"""debug_run.py - drive the DEBUG BUILD (config/patch/debug.json) headless.

Boots build/patch/debug/iso/patched_disc.cue in the reference emulator regtest host
(the local regtest_input.patch, pc/tools/refemu.py: -input, -inputhold,
-loadstate, -savestate, -poke, -memdump, -dumpvram) at full speed -- the host
hard-codes EmulationSpeed 0 (unthrottled), the Null audio backend, the
software renderer and BIOS fast boot, so ~3,500 frames/s on this machine;
frame numbers are EMULATED frames, so CD seek/read time costs the same
frames it costs on hardware (a 96-sector EXN is ~40 frames) and no CD
speed-up setting is needed.

Modes
  --boot-calendar      the retail route from power-on to the first calendar
                       idle (46,000 frames, see tools/patch/regtest_screens.py
                       route_calendar): saves build/patch/debug/states/
                       cal_idle.state (and title.state at frame 3000).  Run
                       once per rebuild of the disc: a save state carries the
                       executable, so states made on another disc are useless.
  --scene ID           load cal_idle.state (or --load STATE), open the scene
                       selector with L2+R2, set its rows (by -poke into the
                       module's variables, whose addresses come from the
                       build report; --ui drives the rows with pad presses
                       instead), press Circle, run --frames frames with a
                       screenshot every --interval, and save
                       states/scene_<ID>[_g<G>].state.
  --goto ID            the same without the selector: the retail goto_step
                       memory writes (regtest_screens.goto_step_pokes).
  --menu               open the selector and screenshot it (no jump).
  --run                just run --frames from the loaded state with --inputs.

Common options
  --girl G --sub S --subsub SS   rows of the selector (now_girl, and the
                       sub-step preset applied once the scene is up)
  --date Y-M-D         set now_year/month/day (two-digit year, 95..98)
  --unlock             press Triangle in the selector (dbg_unlock_all)
  --inputs SPEC        pad schedule after the jump, frames relative to the
                       load: '300-1500/150:CIRCLE,900:START' (buttons:
                       SELECT START UP RIGHT DOWN LEFT L1 L2 R1 R2 TRIANGLE
                       CIRCLE CROSS SQUARE, or a hex mask of the regtest
                       host's bit numbers)
  --frames N --interval N --tag NAME --dumpvram

Outputs: build/patch/debug/shots/<tag>/patched_disc/frame_NNNNN.png (NNNNN
counts from power-on, so a run from cal_idle.state starts at ~27000),
build/patch/debug/shots/<tag>/run.log and run.json (final step block, date,
now_girl, the selector state).

Examples
  tools/patch/debug_run.py --boot-calendar
  tools/patch/debug_run.py --scene 80 --girl 0 --frames 1500
  tools/patch/debug_run.py --scene 99 --girl 1 --unlock --frames 6000 \\
      --inputs "600-6000/150:CIRCLE"
  tools/patch/debug_run.py --menu --interval 10
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, locate  # noqa: E402  (this checkout, either layout)
import regtest_screens as rs                     # noqa: E402

OUT = ROOT / "build" / "patch" / "debug"
DISC = OUT / "iso" / "patched_disc.cue"
REPORT = OUT / "debug.report.json"
STATES = OUT / "states"
SHOTS = OUT / "shots"
from roots import refemu as _refemu                # noqa: E402
refemu = _refemu()   # pc/tools/refemu.py of the PC port, if present
# the reference emulator's regtest host (not distributed: pc/tools/refemu.py)
REGTEST = Path(refemu.regtest())

# regtest -input masks (the reference emulator's AnalogController button numbers)
BTN = {"SELECT": 0x0001, "START": 0x0008, "UP": 0x0010, "RIGHT": 0x0020,
       "DOWN": 0x0040, "LEFT": 0x0080, "L2": 0x0100, "R2": 0x0200,
       "L1": 0x0400, "R1": 0x0800, "TRIANGLE": 0x1000, "CIRCLE": 0x2000,
       "CROSS": 0x4000, "SQUARE": 0x8000}
OPEN_COMBO = BTN["L2"] | BTN["R2"]

# retail globals (fixed addresses: the names are only documentation)
STEP_BLOCK = 0x800EF85C      # D_800EF85C, D_800EF860, step_counter, now_step..
NOW_STEP = 0x800EF868
NOW_GIRL = 0x800EF6BF
DATE = 0x800EE79E            # now_year, now_month, now_day
DBG_FLAG = 0x800B9710
PN = 0x800BA280


def module_symbols():
    if not REPORT.exists():
        sys.exit(f"{REPORT} missing: build the profile first "
                 f"(tools/patch/build_patched.py config/patch/debug.json)")
    rep = json.loads(REPORT.read_text())
    return {k: int(v, 16) for k, v in rep["module"]["symbols"].items()}


def scene_table():
    """rows of src/patch/debug/dbg_scenes.c: [(index, id, girl, exn, label)]"""
    src = (locate("src/patch/debug/dbg_scenes.c")).read_text()
    rows = re.findall(r'\{\s*(\d+),\s*(\d+),\s*"([^"]+)",\s*"([^"]+)"\s*\}', src)
    return [(i, int(a), int(b), c, d) for i, (a, b, c, d) in enumerate(rows)]


def parse_inputs(spec):
    out = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        when, what = item.split(":")
        mask = BTN.get(what.upper())
        if mask is None:
            mask = int(what, 16)
        if "-" in when:
            rng, _, step = when.partition("/")
            a, b = rng.split("-")
            out += [(f, mask) for f in range(int(a), int(b), int(step or 4))]
        else:
            out.append((int(when), mask))
    return out


def run_regtest(disc, frames, out, inputs=(), load=None, save=None,
                interval=100, hold=4, memdumps=(), pokes=(), extra=()):
    out.mkdir(parents=True, exist_ok=True)
    cmd = [str(REGTEST), "-frames", str(frames), "-console",
           "-inputhold", str(hold), "-dumpdir", str(out),
           "-dumpinterval", str(interval)]
    if load:
        cmd += ["-loadstate", str(load)]
    if save:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        cmd += ["-savestate", str(save)]
    for f, m in sorted(inputs):
        cmd += ["-input", f"{f}:{m:04X}"]
    for f, addr, data in pokes:
        cmd += ["-poke", f"{f}:{addr:X}:{bytes(data).hex()}"]
    for addr, size, label in memdumps:
        cmd += ["-memdump", f"{addr:X}", str(size), label]
    cmd += list(extra) + ["--", str(disc)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = r.stdout + r.stderr
    (out / "run.log").write_text(log)
    hexes = {}
    fps = None
    for line in log.splitlines():
        if "Memory Hex" in line:
            body = line.split("Memory Hex ", 1)[1]
            label = body.split(" ")[0]
            hexes[label] = body.rsplit(": ", 1)[1].strip().split("\x1b")[0]
        m = re.search(r"([\d.]+) FPS", line)
        if m:
            fps = float(m.group(1))
    return r.returncode, hexes, fps


def decode_state(hexes):
    st = bytes.fromhex(hexes.get("step", "")) if hexes.get("step") else b""
    out = {}
    if len(st) >= 16:
        out.update({"dispatch_counter": int.from_bytes(st[0:4], "little"),
                    "scene_counter": int.from_bytes(st[4:8], "little"),
                    "step_counter": int.from_bytes(st[8:12], "little"),
                    "now_step": st[12], "now_sub_step": st[13],
                    "now_sub_sub_step": st[14], "step_mode_byte": st[15]})
    if hexes.get("date"):
        d = bytes.fromhex(hexes["date"])
        out["date"] = f"{d[0]}-{d[1]:02d}-{d[2]:02d}"
    for k in ("girl", "dbgflag", "pn", "dbg"):
        if hexes.get(k):
            out[k] = hexes[k]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc", default=str(DISC))
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--boot-calendar", action="store_true")
    mode.add_argument("--scene", type=int)
    mode.add_argument("--goto", type=int)
    mode.add_argument("--menu", action="store_true")
    mode.add_argument("--run", action="store_true")
    ap.add_argument("--load", help="save state to start from (default states/cal_idle.state)")
    ap.add_argument("--girl", type=int, default=None)
    ap.add_argument("--sub", type=int, default=0)
    ap.add_argument("--subsub", type=int, default=0)
    ap.add_argument("--date", help="Y-M-D, e.g. 96-12-24")
    ap.add_argument("--unlock", action="store_true")
    ap.add_argument("--ui", action="store_true",
                    help="drive the selector rows with pad presses instead of pokes")
    ap.add_argument("--inputs", default="")
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--hold", type=int, default=4)
    ap.add_argument("--tag")
    ap.add_argument("--dumpvram", action="store_true")
    ap.add_argument("--no-save", action="store_true", help="do not write a save state")
    a = ap.parse_args()
    if not REGTEST.exists():
        sys.exit(refemu.explain("debug_run"))
    disc = Path(a.disc)
    if not disc.exists():
        sys.exit(f"disc missing: {disc} (build config/patch/debug.json first)")

    dumps = [(STEP_BLOCK, 16, "step"), (DATE, 3, "date"), (NOW_GIRL, 1, "girl"),
             (DBG_FLAG, 1, "dbgflag"), (PN, 1, "pn")]
    syms = module_symbols()
    if "dbg_open" in syms:
        dumps.append((syms["dbg_open"], 16, "dbg"))
    extra = []
    inputs = []
    pokes = []
    load = None
    save = None

    if a.boot_calendar:
        tag = a.tag or "boot_calendar"
        frames = a.frames or 46000
        interval = a.interval or 1000
        inputs = rs.route_calendar()
        save = STATES / "cal_idle.state"
        # also keep a title-screen state: a second, short run
        rc, hx, fps = run_regtest(disc, 3000, SHOTS / "boot_title", [],
                                  save=STATES / "title.state", interval=1000,
                                  memdumps=dumps)
        print(f"[title.state] rc={rc} {decode_state(hx)}")
    else:
        load = Path(a.load) if a.load else STATES / "cal_idle.state"
        if not load.exists():
            sys.exit(f"state missing: {load} (run --boot-calendar first)")
        frames = a.frames or 1500
        interval = a.interval or 100
        jump_frame = 0
        if a.scene is not None or a.menu:
            rows = {r[1]: r for r in scene_table()}
            if a.scene is not None and a.scene not in rows:
                sys.exit(f"scene {a.scene} is not in src/patch/debug/dbg_scenes.c "
                         f"(ids: {sorted(rows)})")
            inputs.append((10, OPEN_COMBO))
            if a.scene is not None:
                idx = rows[a.scene][0]
                if a.ui:
                    f = 20
                    for _ in range(idx):
                        inputs.append((f, BTN["RIGHT"]))
                        f += 6
                    if a.girl is not None:
                        inputs.append((f, BTN["DOWN"]))
                        f += 6
                        for _ in range(a.girl):
                            inputs.append((f, BTN["RIGHT"]))
                            f += 6
                    jump_frame = f + 10
                else:
                    pokes.append((20, syms["dbg_scene_idx"], (idx).to_bytes(2, "little")))
                    if a.girl is not None:
                        pokes.append((20, syms["dbg_girl"], bytes([a.girl])))
                    pokes.append((20, syms["dbg_sub"], bytes([a.sub & 0xFF])))
                    pokes.append((20, syms["dbg_subsub"], bytes([a.subsub & 0xFF])))
                    jump_frame = 40
                if a.unlock:
                    inputs.append((jump_frame - 8, BTN["TRIANGLE"]))
                inputs.append((jump_frame, BTN["CIRCLE"]))
            tag = a.tag or (f"scene_{a.scene}" + (f"_g{a.girl}" if a.girl is not None else "")
                            if a.scene is not None else "menu")
            if a.menu:
                frames = a.frames or 60
                interval = a.interval or 10
        elif a.goto is not None:
            pokes += rs.goto_step_pokes(10, a.goto)
            if a.girl is not None:
                pokes.append((10, NOW_GIRL, bytes([a.girl])))
            jump_frame = 10
            tag = a.tag or f"goto_{a.goto}" + (f"_g{a.girl}" if a.girl is not None else "")
        else:
            tag = a.tag or "run"
        if a.date:
            y, m, d = (int(v) for v in a.date.split("-"))
            pokes.append((5, DATE, bytes([y, m, d])))
        inputs += parse_inputs(a.inputs)
        if not a.no_save and not a.menu:
            save = STATES / f"{tag}.state"
    if a.dumpvram:
        extra += ["-dumpvram", str(SHOTS / tag / "vram.bin")]
    out = SHOTS / tag
    for stale in out.rglob("frame_*.png"):      # one run per tag directory
        stale.unlink()
    rc, hx, fps = run_regtest(disc, frames, out, inputs, load=load, save=save,
                              interval=interval, hold=a.hold, memdumps=dumps,
                              pokes=pokes, extra=extra)
    state = decode_state(hx)
    shots = sorted(str(p.relative_to(ROOT)) for p in out.rglob("frame_*.png"))
    result = {"tag": tag, "rc": rc, "frames": frames, "fps": fps,
              "load": str(load) if load else None,
              "save": str(save) if save else None,
              "final": state, "shots": shots}
    (out / "run.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"[{tag}] rc={rc} frames={frames} fps={fps} final={state}")
    print(f"  shots: {out}  ({len(shots)} frames)" + (f"  state: {save}" if save else ""))


if __name__ == "__main__":
    main()
