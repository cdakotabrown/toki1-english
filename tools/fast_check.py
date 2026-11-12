#!/usr/bin/env python3
"""fast_check.py - the English patch's FAST build gate (no disc image).

Run after any change that can touch the patch: a naming-track landing, an
edit under src/patch/ or config/patch/, a change to the patch tools.  In
order, stopping at the first failure (exit 1):

  1. sync      tools/patch/sync_patch_symbols.py --check: src/patch/ and
               config/patch/ use the naming ledger's CURRENT names (else
               run it with --apply and commit the result)
  2. unit      tools/patch/test_sync_patch_symbols.py (the resolver, the
               sync tool, the build's resolver, compose coverage)
  3. profiles  the test profiles english-debug and english-drawlog:
               compile + link + every write, --no-iso --no-text-gates, then
               verify_hooks.py on their outputs (their extra C, hooks and
               call sites resolve too)
  4. english   the release profile config/patch/english.json: compile + link
               the module, strings, containers, art, loader seals, the
               coverage inventory and ALL text gates (build_patched.py
               --no-iso); then verify_hooks.py reads every hook and call-site
               word back from the bytes

What it does not do: build the ISO, write the PPF, run the disc audit
(`tools/patch/build_patched.py config/patch/english.json` does all three).
The clean bases (build/SLPS_000.65.clean, build/overlay/*/<OV>.clean.EXN)
are built on first use and reused, as build_patched.py always does.

  python3 tools/patch/fast_check.py [--english-only] [-v]
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, locate  # noqa: E402  (this checkout, either layout)
PY = sys.executable


def step(name, cmd, verbose, log_dir):
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    dt = time.time() - t0
    log = log_dir / f"{name}.log"
    log.write_text(r.stdout + r.stderr)
    ok = r.returncode == 0
    print(f"[fast_check] {name:22s} {'OK  ' if ok else 'FAIL'} {dt:6.1f}s  ({log.relative_to(ROOT)})")
    if verbose or not ok:
        tail = (r.stdout + r.stderr).strip().splitlines()
        for ln in tail[-40:] if not ok else tail[-5:]:
            print(f"    {ln}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--english-only", action="store_true",
                    help="skip the english-debug / english-drawlog profiles")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    os.environ.setdefault("TMPDIR", str(ROOT / "build" / "tmp"))
    Path(os.environ["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    log_dir = ROOT / "build" / "patch" / "fast_check"
    log_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    steps = [("sync", [PY, "tools/patch/sync_patch_symbols.py", "--check"]),
             ("unit", [PY, "tools/patch/test_sync_patch_symbols.py"])]
    if not a.english_only:
        for p in ("english-debug", "english-drawlog"):
            steps += [(f"build {p}", [PY, "tools/patch/build_patched.py",
                                      f"config/patch/{p}.json", "--no-iso",
                                      "--no-text-gates"]),
                      (f"hooks {p}", [PY, "tools/patch/verify_hooks.py",
                                      "--profile", f"config/patch/{p}.json"])]
    # the release profile LAST: build/patch/ is left in its state
    steps += [("build english", [PY, "tools/patch/build_patched.py",
                                 "config/patch/english.json", "--no-iso"]),
              ("hooks english", [PY, "tools/patch/verify_hooks.py",
                                 "--profile", "config/patch/english.json"])]
    # tools and profiles are named by their monorepo path; spell them for
    # this checkout's layout (roots.locate)
    steps = [(name, [str(locate(c).relative_to(ROOT)) if c.startswith(("tools/", "config/")) else c
                    for c in cmd])
             for name, cmd in steps]
    for name, cmd in steps:
        if not step(name.replace(" ", "_"), cmd, a.verbose, log_dir):
            print(f"[fast_check] FAILED at {name} after {time.time() - t0:.0f}s")
            return 1
    print(f"[fast_check] all green in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
