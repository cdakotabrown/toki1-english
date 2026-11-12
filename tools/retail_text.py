"""The retail Japanese of a sheet row, read from the player's own disc.

Project decision D4 (2026-11): the localization sheets carry the project's work
(IDs, offsets, budgets, English, status, notes) and **not** Konami's Japanese
text. A row names the file it was extracted from (`File`, repo-relative), the
byte offset (`Offset`) and the in-place budget (`MaxBytes`); the string runs
from that offset to the first NUL, so the Japanese is a pure function of the
disc plus three columns. `tools/translation/extract_containers.py` is the one
implementation of that format, and this module reuses its decoder so the text
the reviewer shows is byte-identical to the text the extractor sheeted.

Resolution order for `File`:

  1. as written (repo-relative, e.g. `assets/extracted_iso/CDROM/BUNKA/...`);
  2. under `$TOKI_RETAIL_ROOT` (default: the toki1-decomp checkout, which
     holds the extracted disc; tools/repo_paths.py).

A missing file is reported, not guessed: a reviewer that silently shows blank
Japanese would let a translator "fix" a line that was never read.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT, TOOLS_TRANSLATION  # noqa: E402  (this checkout, either layout)
_TOOLS = TOOLS_TRANSLATION
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from extract_containers import decode  # noqa: E402  (one decoder for both sides)

sys.path.insert(0, str(ROOT / "tools"))
from repo_paths import DECOMP  # noqa: E402  (the extracted disc lives in toki1-decomp)


class RetailTextError(RuntimeError):
    """The row's source file or string is not available."""


_CACHE: dict[Path, bytes] = {}


def retail_root() -> Path:
    return Path(os.environ.get("TOKI_RETAIL_ROOT") or DECOMP)


def _file(rel: str) -> bytes:
    written = Path(rel)
    for candidate in (written if written.is_absolute() else ROOT / written,
                      retail_root() / written):
        if candidate in _CACHE:
            return _CACHE[candidate]
        if candidate.is_file():
            data = candidate.read_bytes()
            _CACHE[candidate] = data
            return data
    raise RetailTextError(
        f"{rel} is not on disk. The sheets carry no Japanese: extract the disc "
        f"first (docs/GETTING-STARTED.md, 'Extract the assets').")


def japanese_for(row: dict) -> str:
    """The row's retail string with control bytes rendered as {tokens}."""
    data = _file(row["File"])
    offset = int(row["Offset"], 16)
    if not 0 <= offset < len(data):
        raise RetailTextError(f"{row.get('ID', '?')}: offset {row['Offset']} is past the end of {row['File']}.")
    end = data.find(b"\0", offset)
    text = decode(data[offset:end if end >= 0 else len(data)])
    if text is None:
        raise RetailTextError(f"{row.get('ID', '?')}: {row['File']}+{row['Offset']} is not retail text.")
    return text


def fill(rows) -> None:
    """Give every row its `Japanese` (in place), as the extractor would."""
    for row in rows:
        row["Japanese"] = japanese_for(row)

def read_sheet(path) -> list[dict]:
    """CSV rows of a localization sheet, with `Japanese` filled from the disc.

    A sheet that still carries the column (a locally generated draft) is read
    as-is; the tracked sheets do not, so this is the single place that turns
    `File`+`Offset` back into text.
    """
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if rows and "Japanese" not in rows[0]:
        fill(rows)
    return rows