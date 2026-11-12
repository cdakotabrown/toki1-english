#!/usr/bin/env python3
"""Every tracked JSON file parses (CI, tools/ci/run_ci_locally.sh)."""
import json
import subprocess

files = subprocess.run(["git", "ls-files", "*.json"], capture_output=True,
                       text=True, check=True).stdout.split()
bad = []
for path in files:
    try:
        with open(path, encoding="utf-8") as fh:
            json.load(fh)
    except Exception as exc:            # noqa: BLE001 - report, do not crash
        bad.append(f"{path}: {exc}")
print(f"{len(files)} JSON files parsed, {len(bad)} failed")
for line in bad:
    print("BAD", line)
raise SystemExit(1 if bad else 0)
