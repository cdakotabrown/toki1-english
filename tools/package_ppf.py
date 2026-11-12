#!/usr/bin/env python3
"""Package the English PS1 patch for players: a zip with english.ppf and a
README that says which disc it needs and how to apply it.

    python3 tools/patch/package_ppf.py [--ppf build/patch/english.ppf]
        [--out build/tokimeki-english-ppf.zip]

The patch is a PPF 3.0 file (PlayStation Patch File): records of the byte
runs that differ between the player's Track 1 and the English disc
(build_patched.write_ppf3 stores no unchanged byte).  It is useless without
the player's own dump, but "changed" is not "ours": some changed bytes are
still derived from the original disc (relocated or repacked Japanese
strings, re-encoded glyphs, image bytes where one 4-bit pixel changed,
sector EDC/ECC), so the
README says exactly that and no more.  The README's checksums come
from the files on THIS machine: the player's dump, the PPF, and the result
of applying it (tools/patch/verify_ppf.py proves that result equals the
built English disc).
"""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))

TRACK1 = "Tokimeki Memorial - Forever with You (Japan) (Rev 1) (Track 1).bin"
TRACK2 = "Tokimeki Memorial - Forever with You (Japan) (Rev 1) (Track 2).bin"
CUE = "Tokimeki Memorial - Forever with You (Japan) (Rev 1).cue"

README = """Tokimeki Memorial: Forever with You -- English patch (PS1)
=============================================================

This is a fan translation patch for the PlayStation game Tokimeki Memorial:
Forever with You (Konami, 1995, Japan, SLPS-00065). You need your own copy
of the game, dumped as BIN/CUE: the patch is a binary diff and does nothing
on its own.

What the patch contains: only the byte runs that the translation changes in
Track 1 (no unchanged byte is stored). Most of them are the English text,
lettering and code. Some changed bytes are still derived from the original
disc: Japanese strings the patch moves or repacks, re-encoded font glyphs,
image bytes where only one of two pixels changed, and the sector checksums
(EDC/ECC) of every changed sector.

The patch is english.ppf, a PPF 3.0 file (the standard PlayStation patch
format). It changes Track 1 only. Track 2 (the audio track) and the .cue
stay exactly as they are.


1. Check that you have the right disc
-------------------------------------

The patch only works on this exact dump (Redump: "Tokimeki Memorial -
Forever with You (Japan) (Rev 1)", 2 tracks):

  {track1}
      size  {t1size:,} bytes
      SHA-1 {t1sha}
  {track2}
      size  {t2size:,} bytes
      SHA-1 {t2sha}

On Windows you can check a SHA-1 in PowerShell:
  Get-FileHash -Algorithm SHA1 "<file>"
(On Linux/macOS: sha1sum "<file>".)


2. Apply it (pick ONE way)
--------------------------

A) An emulator that applies .ppf itself, no patching tool needed (easiest)
   Copy english.ppf into the folder with your .cue and give it the SAME name
   as the .cue, ending in .ppf. For example:
     {cue}
     {cue_ppf}
   Start the game from the .cue as usual. Such an emulator applies the patch as
   it loads the disc (your files are not changed). Remove or rename the .ppf
   to play in Japanese again.

B) PPF-O-Matic (Windows, point and click)
   1. Make a COPY of your Track 1 .bin (the patch changes the file it is
      applied to).
   2. Open PPF-O-Matic. "ISO File": the copy of Track 1. "Patch": english.ppf.
   3. Click Apply. Use the patched copy together with your Track 2 .bin and a
      .cue that names the patched copy as Track 1.

C) applyppf (command line, any OS)
     cp "{track1}" "Track1-english.bin"
     applyppf3 a "Track1-english.bin" english.ppf

After B or C the patched Track 1 must have this SHA-1:
      {patched_sha}
If it does not, the patch was applied to a different dump or applied twice.


3. Files
--------

  english.ppf   {ppf_size:,} bytes, SHA-1 {ppf_sha}
  README.txt    this file

The English text is a draft by the fan translation project; corrections are
welcome. Tokimeki Memorial is (C) Konami. This patch is not affiliated with
or endorsed by Konami.
"""


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ppf", default=str(ROOT / "build/patch/english.ppf"))
    ap.add_argument("--built", default=str(ROOT / "build/patch/iso/patched_disc.bin"),
                    help="the English Track 1 the PPF was made from (for its SHA-1)")
    ap.add_argument("--disks", default=str(DECOMP / "disks"))
    ap.add_argument("--out", default=str(ROOT / "build/tokimeki-english-ppf.zip"))
    a = ap.parse_args(argv)

    ppf, built, disks = Path(a.ppf), Path(a.built), Path(a.disks)
    t1, t2 = disks / TRACK1, disks / TRACK2
    for p in (ppf, built, t1, t2):
        if not p.exists():
            print(f"package_ppf: missing {p}")
            return 1

    import verify_ppf  # the independent PPF reader: the package must verify
    if not verify_ppf.verify(ppf, t1, built, None):
        print("package_ppf: verify_ppf failed; not packaging")
        return 1

    readme = README.format(
        track1=TRACK1, track2=TRACK2, cue=CUE, cue_ppf=CUE[:-4] + ".ppf",
        t1size=t1.stat().st_size, t1sha=sha1(t1),
        t2size=t2.stat().st_size, t2sha=sha1(t2),
        patched_sha=sha1(built),
        ppf_size=ppf.stat().st_size, ppf_sha=sha1(ppf))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ppf, "tokimeki-english-patch/english.ppf")
        z.writestr("tokimeki-english-patch/README.txt", readme.replace("\n", "\r\n"))
    print(f"package_ppf: {out} ({out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
