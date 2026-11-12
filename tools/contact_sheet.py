#!/usr/bin/env python3
"""contact_sheet.py - tile the frame_NNNNN.png screenshots of a regtest run
into one image (for reviewing a long headless run at a glance).

Usage: contact_sheet.py SHOTS_DIR OUT.png [--cols 6] [--scale 0.5]
         [--crop x0,y0,x1,y1]
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shots")
    ap.add_argument("out")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--crop", help="x0,y0,x1,y1 of the source frame")
    ap.add_argument("--every", type=int, default=1)
    a = ap.parse_args()
    files = sorted(Path(a.shots).rglob("frame_*.png"))[::a.every]
    if not files:
        raise SystemExit("no frames")
    crop = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
    im0 = Image.open(files[0])
    if crop:
        im0 = im0.crop(crop)
    w, h = int(im0.width * a.scale), int(im0.height * a.scale)
    rows = (len(files) + a.cols - 1) // a.cols
    sheet = Image.new("RGB", (a.cols * w, rows * (h + 12)), (32, 32, 32))
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        if crop:
            im = im.crop(crop)
        im = im.resize((w, h))
        x, y = (i % a.cols) * w, (i // a.cols) * (h + 12)
        sheet.paste(im, (x, y + 12))
        d.text((x + 2, y), f.stem.replace("frame_", ""), fill=(255, 255, 0))
    sheet.save(a.out)
    print(f"{len(files)} frames -> {a.out} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
