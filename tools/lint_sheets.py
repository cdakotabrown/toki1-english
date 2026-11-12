#!/usr/bin/env python3
"""Disc-free lint of the translation sheets: `make lint`, CI, a pre-commit hook.

    python3 tools/translation/lint_sheets.py [--base REV] [--allow-rows]
        [--staged] [-q]

Every rule reuses the code of the gate that owns it, so a sheet edit that
passes here fails the full build only on what needs the disc:

  format    UTF-8 without a BOM, LF line ends, a final newline; the
            extractor's header (extract_containers.FIELDS) and no other
            column; every row exactly those fields under a strict CSV reader;
            the file in canonical CSV form (csv.writer writes the same
            bytes, so a diff shows only the cells that changed); ID equal to
            File:Offset, IDs unique, Offset hex, MaxBytes a number
  rows      against BASE: the same rows in the same order, and the columns
            the extractor writes from the disc (ID File Offset MaxBytes
            PtrSite Kind Tokens) unchanged; --allow-rows for an intended
            change.  BASE is --base, else HEAD when the sheets differ from
            it, else HEAD^ when there is one (else the rule says it skipped)
  japanese  the game's script never enters the repository: no Japanese in
            any column but Notes; in Notes, and in the glossary's Japanese
            and Notes columns, no run of JP_RUN (10) or more Japanese
            characters (japanese_text.py: the export preflight's rule and
            threshold); no `Japanese` column (a hydrated sheet copied back);
            no file of the hydrated work tree tracked or staged; no tracked
            text file of the English part with such a run
  text      check_translation.row_findings without the disc: status, empty
            English, tokens (the English's set against the Tokens column),
            syntax, charset (printable ASCII), budget-hard (255 bytes)
  fit       on the English the build uses (inject.edited_english: choice
            overrides and edits applied), as inject.py fits it: encodable
            (textcodec), no menu choice over-wide (inject.fit_text), no word
            wider than the 201-px window (text_gates.wide_words)
  budget    a WARNING, not a failure: rows longer than their in-place
            MaxBytes before DTE.  The build moves such rows into the free
            space of their container and compresses the whole corpus with a
            DTE dictionary, so only `make patch` (inject.py and the fit gate,
            with the disc) decides whether a container fits

Only the disc can check (make patch, or check_translation.py with the disc):
token COUNTS and the tokens of each {opt} segment (gate `codes`), translation
memory consistency and glossary hits (they key on the Japanese), the
container fit after DTE, the read-back of the built disc, and glyph coverage.

--staged also fails when a file of the hydrated work tree is staged (the
pre-commit hook passes it).  Exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("TOKI_DECOMP_OPTIONAL", "1")      # no toki1-decomp needed
_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import (ROOT, SHEETS, GUIDE, WORK, PATCH_CONFIG, ART, PATCH_SRC,  # noqa: E402
                   TOOLS_PATCH, TOOLS_TRANSLATION, REVIEWER, PUBLIC)
import japanese_text  # noqa: E402
from extract_containers import FIELDS  # noqa: E402
import check_translation  # noqa: E402
import inject  # noqa: E402
import text_gates  # noqa: E402
import textcodec  # noqa: E402

# the columns the extractor writes from the disc: a contributor never edits
# them (English, Status, Notes and Speaker are the editable ones)
EXTRACTED = ("ID", "File", "Offset", "MaxBytes", "PtrSite", "Kind", "Tokens")
JP_ALLOWED = {"Notes"}                       # sheet columns that may quote Japanese
GLOSSARY_JP_ALLOWED = {"Japanese", "Notes"}  # the glossary's term column


class Findings:
    def __init__(self):
        self.fails, self.warns, self.notes = [], [], []

    def fail(self, where, kind, msg):
        self.fails.append((kind, where, msg))

    def warn(self, where, kind, msg):
        self.warns.append((kind, where, msg))


def rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def parse(text: str, where: str, f: Findings):
    """rows (lists) of a sheet under a strict reader, or None"""
    try:
        return list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as e:
        f.fail(where, "format", f"not well-formed CSV: {e}")
        return None


def canonical(rows) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def check_format(path: Path, data: bytes, f: Findings, fields=FIELDS):
    """the format rules; returns the rows as dicts, or None"""
    where = rel(path)
    if data.startswith(b"\xef\xbb\xbf"):
        f.fail(where, "format", "starts with a byte-order mark")
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        f.fail(where, "format", f"not UTF-8: {e}")
        return None
    if "\r" in text:
        f.fail(where, "format", "CR line ends (write LF)")
        text = text.replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        f.fail(where, "format", "no newline at the end of the file")
    rows = parse(text, where, f)
    if rows is None:
        return None
    if not rows:
        f.fail(where, "format", "empty file")
        return None
    header = rows[0]
    if "Japanese" in header:
        f.fail(where, "japanese", "a `Japanese` column: a hydrated sheet (work/) never goes "
                                  "back into the repository; fold it (make fold)")
    if list(header) != list(fields):
        f.fail(where, "format", f"header {header} is not {list(fields)}")
        return None
    out = []
    for n, r in enumerate(rows[1:], 2):
        if len(r) != len(fields):
            f.fail(f"{where}:{n}", "format", f"{len(r)} fields, not {len(fields)}")
            continue
        out.append(dict(zip(fields, r)))
    if canonical(rows) != text:
        f.fail(where, "format", "not in canonical CSV form (quote a field only when it "
                                "needs it, double the quotes inside it, LF line ends)")
    return out


def check_ids(path: Path, rows, f: Findings):
    where = rel(path)
    seen = set()
    for r in rows:
        rid = r["ID"]
        if rid in seen:
            f.fail(where, "format", f"duplicate ID {rid}")
        seen.add(rid)
        try:
            off = int(r["Offset"], 16)
            if not r["Offset"].startswith("0x"):
                raise ValueError
        except ValueError:
            f.fail(f"{where} {rid}", "format", f"Offset {r['Offset']!r} is not hex (0x...)")
            continue
        if rid != f"{r['File']}:0x{off:x}":
            f.fail(f"{where} {rid}", "format", "ID is not File:Offset")
        if not r["MaxBytes"].isdigit():
            f.fail(f"{where} {rid}", "format", f"MaxBytes {r['MaxBytes']!r} is not a number")


def check_rows_against(path: Path, rows, base_rows, f: Findings, allow_rows=False):
    """same rows, same order, extracted columns unchanged"""
    where = rel(path)
    if base_rows is None:
        if not allow_rows:
            f.fail(where, "rows", "a new sheet (pass --allow-rows if that is intended)")
        return
    ids = [r["ID"] for r in rows]
    old = [r["ID"] for r in base_rows]
    if ids != old and not allow_rows:
        gone = [i for i in old if i not in set(ids)]
        new = [i for i in ids if i not in set(old)]
        what = []
        if gone:
            what.append(f"{len(gone)} removed (e.g. {gone[0]})")
        if new:
            what.append(f"{len(new)} added (e.g. {new[0]})")
        if not gone and not new:
            what.append("reordered")
        f.fail(where, "rows", "rows " + ", ".join(what) + " (pass --allow-rows if intended)")
    by_id = {r["ID"]: r for r in base_rows}
    for r in rows:
        b = by_id.get(r["ID"])
        if b is None:
            continue
        for col in EXTRACTED:
            if r[col] != b.get(col):
                f.fail(f"{where} {r['ID']}", "rows",
                       f"{col} changed ({b.get(col)!r} -> {r[col]!r}): the extractor's column")


def check_japanese_cells(where: str, rows, allowed, f: Findings):
    for r in rows:
        for col, v in r.items():
            if not v:
                continue
            if col in allowed:
                long = japanese_text.runs(v)
                if long:
                    f.fail(f"{where} {r.get('ID') or r.get('English', '')}", "japanese",
                           f"{col} quotes {len(max(long, key=len))} Japanese characters in a row "
                           f"(at most {japanese_text.JP_RUN - 1}: a name or a term, not a line)")
            elif japanese_text.JP_ANY_RE.search(v):
                f.fail(f"{where} {r.get('ID') or ''}", "japanese",
                       f"Japanese in the {col} column (only {', '.join(sorted(allowed))} may quote it)")


def check_text_and_fit(where: str, sheet_dir: str, rows, f: Findings, stats: Counter):
    for r in rows:
        res = check_translation.row_findings(r)
        for kind, msg in res["fails"]:
            f.fail(f"{where} {r['ID']}", "text", f"{kind}: {msg}")
        if "ascii" in res and res["ascii"] > res["budget"]:
            stats["over_maxbytes"] += 1
            stats["over_maxbytes_bytes"] += res["ascii"] - res["budget"]
        if res["fails"] or res["status"] not in inject.ACCEPT_STATUS \
                or sheet_dir not in inject.DEFAULT_DIRS:
            continue
        for msg in text_gates.wide_words(r):
            f.fail(f"{where} {r['ID']}", "fit", msg)
        tokens = (r.get("Tokens") or "").split()
        kind = inject.row_kind(r["Kind"], tokens)
        new, _ = inject.edited_english(r["ID"], kind, r["English"])
        en = (new or r["English"]).strip()
        if not en:
            continue
        local = Counter()
        text, notes = inject.fit_text(inject.normalise(en), kind, local)
        if local["choice_too_wide"]:
            f.fail(f"{where} {r['ID']}", "fit", "over-wide menu choice: " + "; ".join(notes)
                   + " (shorten it; config/patch/choice_overrides.json holds the build's"
                     " shortenings)")
        try:
            textcodec.encode(text, [])
        except ValueError as e:
            f.fail(f"{where} {r['ID']}", "fit", f"unencodable: {e}")


def git(*args, check=False):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def choose_base(explicit):
    if explicit:
        return explicit
    if git("rev-parse", "--verify", "-q", "HEAD").returncode:
        return None
    if git("diff", "--quiet", "HEAD", "--", str(SHEETS)).returncode:
        return "HEAD"
    if not git("rev-parse", "--verify", "-q", "HEAD^").returncode:
        return "HEAD^"
    return None


def base_rows(base, path: Path):
    r = git("show", f"{base}:{rel(path)}")
    if r.returncode:
        return None
    return list(csv.DictReader(io.StringIO(r.stdout, newline="")))


def english_part_files():
    """tracked files of the English part (in toki1-english: every file)"""
    if PUBLIC:
        args = []
    else:
        args = ["--"] + [str(d) for d in (SHEETS, GUIDE, PATCH_CONFIG, ART, PATCH_SRC.parent,
                                          TOOLS_PATCH, TOOLS_TRANSLATION, REVIEWER)]
        args.append(str(locate_text_pointers()))
    r = git("ls-files", "-z", *args)
    return [p for p in r.stdout.split("\0") if p]


def locate_text_pointers():
    from roots import locate
    return locate("translation/text_pointers.json")


def check_repository(f: Findings, staged=False):
    """nothing hydrated tracked or staged; no tracked English-part text
    file with Japanese text"""
    wrel = rel(WORK)
    tracked = [p for p in git("ls-files", "-z", "--", wrel).stdout.split("\0") if p]
    for p in tracked:
        f.fail(p, "japanese", "a hydrated work file is tracked (git rm --cached it)")
    if staged:
        names = git("diff", "--cached", "--name-only", "-z").stdout.split("\0")
        for p in names:
            if p and (p == wrel or p.startswith(wrel + "/")):
                f.fail(p, "japanese", "a hydrated work file is staged (git restore --staged it)")
    for p in english_part_files():
        if p.startswith(wrel + "/"):
            continue
        fp = ROOT / p
        if fp.suffix.lower() in (".png", ".jpg", ".gif", ".ico", ".ttf") or not fp.is_file():
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        long = japanese_text.runs(text)
        if long:
            f.fail(p, "japanese", f"{len(long)} run(s) of >= {japanese_text.JP_RUN} Japanese "
                                  f"characters, e.g. {max(long, key=len)[:12]!r}...")


def lint(sheets=SHEETS, glossary=None, base=None, allow_rows=False, repository=True,
         staged=False):
    """(Findings, stats)"""
    f, stats = Findings(), Counter()
    paths = sorted(Path(sheets).glob("*/*.csv"))
    if base is None:
        f.notes.append("rows: no base revision (a single commit and no local change): "
                       "row stability not checked")
    for p in paths:
        rows = check_format(p, p.read_bytes(), f)
        if rows is None:
            continue
        stats["sheets"] += 1
        stats["rows"] += len(rows)
        check_ids(p, rows, f)
        if base is not None:
            check_rows_against(p, rows, base_rows(base, p), f, allow_rows)
        check_japanese_cells(rel(p), rows, JP_ALLOWED, f)
        check_text_and_fit(rel(p), p.parent.name, rows, f, stats)
    if base is not None and not allow_rows:
        for line in git("ls-tree", "-r", "--name-only", base, "--", rel(Path(sheets))).stdout.split():
            if line.endswith(".csv") and not (ROOT / line).exists():
                f.fail(line, "rows", "a sheet was deleted (pass --allow-rows if intended)")
    gl = Path(glossary) if glossary else GUIDE / "GLOSSARY.csv"
    if gl.exists():
        with open(gl, encoding="utf-8", newline="") as fh:
            check_japanese_cells(rel(gl), list(csv.DictReader(fh)), GLOSSARY_JP_ALLOWED, f)
    if repository:
        check_repository(f, staged)
    return f, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="revision the rows must match (default: HEAD when the "
                                   "sheets differ from it, else HEAD^)")
    ap.add_argument("--allow-rows", action="store_true",
                    help="rows or sheets were added, removed or reordered on purpose")
    ap.add_argument("--staged", action="store_true",
                    help="also fail on a staged file of the hydrated work tree (pre-commit)")
    ap.add_argument("-q", "--quiet", action="store_true", help="failures and the summary only")
    a = ap.parse_args(argv)
    base = choose_base(a.base)
    f, stats = lint(base=base, allow_rows=a.allow_rows, staged=a.staged)
    for kind, where, msg in f.fails:
        print(f"FAIL {kind:9s} {where}: {msg}")
    if not a.quiet:
        for kind, where, msg in f.warns:
            print(f"WARN {kind:9s} {where}: {msg}")
        for n in f.notes:
            print(f"note: {n}")
    by = Counter(k for k, _, _ in f.fails)
    print(f"lint_sheets: {stats['sheets']} sheets, {stats['rows']:,} rows"
          + (f", rows checked against {base}" if base else "")
          + f"; {stats['over_maxbytes']} rows over their in-place MaxBytes before DTE "
            f"(+{stats['over_maxbytes_bytes']:,} bytes; the build relocates them: "
            f"`make patch` decides the fit)")
    print("lint_sheets: " + ("PASS" if not f.fails else
                             f"FAIL ({len(f.fails)}: " + ", ".join(f"{k} {n}" for k, n in sorted(by.items())) + ")"))
    return 1 if f.fails else 0


if __name__ == "__main__":
    sys.exit(main())
