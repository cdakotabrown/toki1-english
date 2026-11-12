#!/usr/bin/env python3
"""scene_sweep.py - force every scene of the retail scene table on a disc
and screenshot it (the English patch's broad regression test).

For each scene id of the loader's switch (NAME_ENT 17.., OPTION 32.., ETC,
OLH 58, TEL, DATE, SHUGAKU
81, SHOUGATU, VALEN, GEKO, DATE2, KANGEI, OMIMAI, ENDING 99, BUNKASAI 112,
BUNKAKEN 113, TAIIKU, RENSYU, MASTER, BUNKA_SD 128, RPG_BAT 129, EN_NICHI
130, TT 208) the reference emulator regtest host loads a CALENDAR-IDLE save state
made on the SAME disc, pokes goto_step(scene) (regtest_screens.goto_step_pokes),
parks the pointer on the first reply row, presses Circle every 60 frames
and dumps a frame every 100.  Every scene gets a contact sheet
(build/patch/shots/sweep_<tag>/<scene>/sheet.png) and the summary table
(sweep.md + sweep.json) counts, per scene, the frames with text and the
frames where the renderer drew its MISSING-GLYPH BOX (the 9x9 outline
pt_box_rows draws for a kanji that is not in the pool); garbled Latin
text still needs eyes, which is what the sheets are for.

The save state must come from the disc under test: a state carries the
exe (the text module, its DTE table and string pool) in RAM, so a state
made on an older build decodes the new containers through the old table
and every injected line reads as letter salad.  regtest_screens.py writes
<state>.exe.sha1 next to each state it saves and refuses a mismatch.

  python3 tools/patch/scene_sweep.py --disc build/patch/iso/patched_disc.bin \\
      --state build/patch/states/en13_calidle_calendar.state --tag en13 \\
      [--scenes 81 113] [--frames 1200] [--jobs 4]
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, TOOLS_PATCH  # noqa: E402  (this checkout, either layout)
import regtest_screens as rt  # noqa: E402

SCENES = {
    17: "NAME_ENT", 19: "NAME_ENT", 20: "NAME_ENT", 21: "NAME_ENT",
    32: "OPTION", 33: "OPTION", 34: "OPTION",
    53: "ETC", 54: "ETC", 55: "ETC", 145: "ETC", 194: "ETC", 195: "ETC", 196: "ETC",
    58: "OLH", 67: "TEL", 69: "TEL", 80: "DATE", 94: "DATE", 81: "SHUGAKU",
    82: "SHOUGATU", 83: "SHOUGATU", 85: "SHOUGATU", 91: "SHOUGATU", 84: "VALEN",
    86: "GEKO", 87: "GEKO", 89: "GEKO", 90: "GEKO", 93: "GEKO", 88: "DATE2", 92: "DATE2",
    95: "KANGEI", 96: "KANGEI", 97: "OMIMAI", 98: "OMIMAI", 99: "ENDING",
    112: "BUNKASAI", 113: "BUNKAKEN", 114: "TAIIKU", 115: "RENSYU",
    116: "MASTER", 117: "MASTER", 118: "MASTER", 128: "BUNKA_SD", 129: "RPG_BAT",
    130: "EN_NICHI", 208: "TT", 18: "TACO",
}


def box_glyphs(png: Path, y_from=0):
    """count of the renderer's missing-glyph placeholders in the frame: a
    9x9 bright outline with a bright main diagonal and a dark interior
    otherwise (text_vwf.c pt_box_rows); a cheap, conservative detector"""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()

    def bright(x, y):
        r, g, b = px[x, y]
        return r > 150 and g > 150 and b > 120

    n = 0
    for y in range(max(0, y_from), h - 9):
        for x in range(1, w - 10):
            if not bright(x, y) or bright(x - 1, y) or bright(x + 9, y):
                continue
            if not all(bright(x + i, y) for i in range(9)):
                continue
            if not all(bright(x + i, y + 8) for i in range(9)):
                continue
            if not all(bright(x, y + j) and bright(x + 8, y + j) for j in range(1, 8)):
                continue
            if not all(bright(x + j, y + j) for j in range(1, 8)):
                continue
            if any(bright(x + i, y + j) for i in range(2, 7) for j in range(2, 7) if i != j):
                continue
            n += 1
    return n


def has_text(png: Path):
    """rough: text-coloured pixels (the renderer's pale cyan-white,
    ~(164,201,201), or white) inside the message window band (y 160..210)"""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    c = 0
    for y in range(160, min(h, 210)):
        for x in range(20, w - 40, 2):
            r, g, b = px[x, y]
            if r > 120 and g > 160 and b > 160:
                c += 1
    return c > 60


def run_scene(disc, state, scene, out_root, frames, interval, hold, rescan=False, dumpram=False):
    out = out_root / f"{scene:03d}_{SCENES.get(scene, '?')}"
    rc = 0
    if not rescan:
        inputs = rt.park_on_reply1(120) + [(f, rt.CIRCLE) for f in range(300, frames, 60)]
        pokes = rt.goto_step_pokes(10, scene)
        extra = ["-dumpram", str(out / "ram.bin")] if dumpram else []
        out.mkdir(parents=True, exist_ok=True)
        rc, hx = rt.run(Path(disc), frames, out, inputs, load=state, save=None,
                        interval=interval, hold=hold, pokes=pokes, extra=extra)
    subdirs = [d for d in out.iterdir() if d.is_dir() and any(d.glob("frame_*.png"))] if out.exists() else []
    frames_dir = subdirs[0] if len(subdirs) == 1 else (out / "patched_disc" if (out / "patched_disc").exists() else out)
    pngs = sorted(frames_dir.glob("frame_*.png"))
    res = {"scene": scene, "overlay": SCENES.get(scene, "?"), "rc": rc,
           "frames": len(pngs), "text_frames": 0, "box_frames": 0, "boxes": 0}
    for p in pngs:
        if has_text(p):
            res["text_frames"] += 1
        b = box_glyphs(p, 0)
        if b:
            res["box_frames"] += 1
            res["boxes"] += b
    try:
        subprocess.run([sys.executable, str(TOOLS_PATCH / "contact_sheet.py"),
                        str(frames_dir), str(out / "sheet.png"), "--scale", "1", "--cols", "4"],
                       check=False, capture_output=True)
        res["sheet"] = str((out / "sheet.png").relative_to(ROOT))
    except OSError:
        pass
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc", required=True)
    ap.add_argument("--state", required=True, help="calendar-idle save state made on --disc")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--scenes", nargs="*", type=int, default=None)
    ap.add_argument("--frames", type=int, default=1200)
    ap.add_argument("--interval", type=int, default=100)
    ap.add_argument("--hold", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--allow-stale-state", action="store_true")
    ap.add_argument("--dumpram", action="store_true",
                    help="write each scene's RAM (ram.bin; tools/patch/draw_log.py reads the "
                         "drawn-text log of an english-drawlog disc from it)")
    ap.add_argument("--rescan", action="store_true",
                    help="only recompute the table from the frames already dumped")
    a = ap.parse_args()
    if not a.allow_stale_state and not a.rescan:
        rt.check_state_matches_disc(Path(a.state), Path(a.disc))
    scenes = a.scenes or sorted(SCENES)
    out_root = ROOT / "build" / "patch" / "shots" / f"sweep_{a.tag}"
    out_root.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(run_scene, a.disc, a.state, s, out_root, a.frames, a.interval, a.hold,
                          a.rescan, a.dumpram) for s in scenes]
        for f in futs:
            r = f.result()
            results.append(r)
            print(f"[sweep] scene {r['scene']:3d} {r['overlay']:9s} rc={r['rc']} frames={r['frames']:3d} "
                  f"text={r['text_frames']:3d} box-frames={r['box_frames']} boxes={r['boxes']}")
    results.sort(key=lambda r: r["scene"])
    (out_root / "sweep.json").write_text(json.dumps(results, indent=1) + "\n")
    lines = ["| scene | overlay | frames | frames with text | frames with a missing-glyph box | boxes | sheet |",
             "|---:|---|---:|---:|---:|---:|---|"]
    for r in results:
        lines.append(f"| {r['scene']} | {r['overlay']} | {r['frames']} | {r['text_frames']} | "
                     f"{r['box_frames']} | {r['boxes']} | `{r.get('sheet', '')}` |")
    (out_root / "sweep.md").write_text("\n".join(lines) + "\n")
    print(f"[sweep] {len(results)} scenes -> {out_root.relative_to(ROOT)}/sweep.md")


if __name__ == "__main__":
    main()
