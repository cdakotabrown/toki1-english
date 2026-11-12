#!/usr/bin/env python3
"""debug_memcard.py - a memory card that unlocks Konami's retail debug mode.

The retail option screen (OPTION scene 32, `OPTION/func_80132BB4.c:177-191`)
calls `card_file_check(15)` at boot: `save_name_set(buf, 15)` builds the
file name `bu00:BISLPS-00065F` (the save prefix `BISLPS-00065` + suffix
`F`; normal saves use `0`..`E`), `open(buf, 2)` succeeds when a file of
that name exists in slot 1, "DEBUG MODE OK" goes to the TTY and
`D_800B9710 = 1`: the debug flag that gates the step overlay, the debug
text renderers and the hidden OPTION scenes 33 (sound test) and 34
(parameter editor with the page-F scene warp), entered with L1+L2+R1+R2 on
the option menu.  Only the
file's EXISTENCE is tested: nothing reads its contents.

This writes a standard 128 KB PlayStation memory card image (an emulator
`.mcd` is the raw image; the same bytes work in every emulator that takes
a raw card) with that one file in block 1: a valid directory frame (state
0x51, size 8192, no next block, the name, XOR checksum) and a data block
with the usual title frame ("SC", 1 icon frame, 1 block, the title
"DEBUG MODE" in Shift-JIS, a blank 16x16 icon and palette), so the BIOS
card manager lists it instead of refusing the card.  `--add CARD.mcd`
adds the file to an existing card (first free block) instead of making a
fresh one.

  python3 tools/patch/debug_memcard.py                      # build/patch/debug_card.mcd
  python3 tools/patch/debug_memcard.py --out my.mcd --add existing.mcd
  python3 tools/patch/regtest_screens.py ... --memcard build/patch/debug_card.mcd
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import locate                          # noqa: E402
CARD_SIZE = 128 * 1024
FRAME = 128
BLOCK = 8192
FILE_NAME = b"BISLPS-00065F"


def checksum(frame: bytes) -> int:
    x = 0
    for b in frame[:127]:
        x ^= b
    return x


def frame_with_sum(frame: bytearray) -> bytes:
    frame[127] = checksum(frame)
    return bytes(frame)


def blank_card() -> bytearray:
    card = bytearray(CARD_SIZE)
    # frame 0: header
    f = bytearray(FRAME)
    f[0:2] = b"MC"
    card[0:FRAME] = frame_with_sum(f)
    # frames 1..15: directory entries, all free
    for i in range(1, 16):
        f = bytearray(FRAME)
        f[0:4] = (0xA0).to_bytes(4, "little")
        f[8:10] = b"\xff\xff"
        card[i * FRAME:(i + 1) * FRAME] = frame_with_sum(f)
    # frames 16..35: broken-sector list (none)
    for i in range(16, 36):
        f = bytearray(FRAME)
        f[0:4] = (0xFFFFFFFF).to_bytes(4, "little")
        f[8:10] = b"\xff\xff"
        card[i * FRAME:(i + 1) * FRAME] = frame_with_sum(f)
    # frames 36..55: broken-sector replacement data, 56..62 unused: 0xFF
    for i in range(36, 63):
        card[i * FRAME:(i + 1) * FRAME] = b"\xff" * FRAME
    # frame 63: write-test frame
    card[63 * FRAME:64 * FRAME] = frame_with_sum(bytearray(b"MC" + bytes(126)))
    return card


def title_block() -> bytes:
    """block data: title frame + one icon frame + zeros"""
    blk = bytearray(BLOCK)
    blk[0:2] = b"SC"
    blk[2] = 0x11                 # one icon frame
    blk[3] = 1                    # one block
    title = "ＤＥＢＵＧ　ＭＯＤＥ".encode("shift_jis")
    blk[4:4 + len(title)] = title
    # palette (16 colours, 16-bit): transparent, white, ...
    pal = [0x0000, 0x7FFF] + [0x0000] * 14
    for i, c in enumerate(pal):
        blk[0x60 + 2 * i:0x62 + 2 * i] = c.to_bytes(2, "little")
    # icon frame (16x16 4-bpp): a white square outline
    icon = bytearray(128)
    for y in range(16):
        for x in range(16):
            on = (x in (0, 15) or y in (0, 15))
            idx = y * 8 + x // 2
            if on:
                icon[idx] |= 0x1 if x % 2 == 0 else 0x10
    blk[0x80:0x100] = icon
    return bytes(blk)


def add_file(card: bytearray, name: bytes = FILE_NAME) -> int:
    """put the file into the first free block; returns the block number"""
    for i in range(1, 16):
        d = card[i * FRAME:(i + 1) * FRAME]
        if d[10:30].rstrip(b"\0") == name:
            return i                          # already there
    for i in range(1, 16):
        d = card[i * FRAME:(i + 1) * FRAME]
        if int.from_bytes(d[0:4], "little") == 0xA0:
            f = bytearray(FRAME)
            f[0:4] = (0x51).to_bytes(4, "little")      # in use, first block
            f[4:8] = BLOCK.to_bytes(4, "little")
            f[8:10] = b"\xff\xff"
            f[10:10 + len(name)] = name
            card[i * FRAME:(i + 1) * FRAME] = frame_with_sum(f)
            card[i * BLOCK:(i + 1) * BLOCK] = title_block()
            return i
    raise SystemExit("card is full")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build/patch/debug_card.mcd")
    ap.add_argument("--add", help="existing 128 KB card to add the file to")
    a = ap.parse_args()
    if a.add:
        card = bytearray(Path(a.add).read_bytes())
        if len(card) != CARD_SIZE:
            raise SystemExit(f"{a.add}: {len(card)} bytes, not a raw 128 KB card")
    else:
        card = blank_card()
    blk = add_file(card)
    out = locate(a.out) if not Path(a.out).is_absolute() else Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(card))
    print(f"{out}: {FILE_NAME.decode()} in block {blk} ({len(card)} bytes); "
          f"OPTION scene 32 now reports DEBUG MODE OK (L1+L2+R1+R2 on the option "
          f"menu opens the sound test / parameter editor)")


if __name__ == "__main__":
    main()
