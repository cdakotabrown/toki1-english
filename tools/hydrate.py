#!/usr/bin/env python3
"""A local working view of the sheets with the Japanese beside the English,
read from YOUR disc, and the way back: `make hydrate`, `make fold`.

    python3 tools/translation/hydrate.py hydrate [--force] [SHEET ...]
    python3 tools/translation/hydrate.py fold [--dry-run] [SHEET ...]
    python3 tools/translation/hydrate.py status

The tracked sheets (translation/localization/sheets/<DIR>/<FILE>.csv; in
toki1-english sheets/) carry no Japanese: a row names its file, offset and
byte budget on the disc.  `hydrate` writes, for every sheet, a copy under the
work tree (translation/work/sheets/; in toki1-english work/sheets/) with a
`Japanese` column after `Speaker`, filled by tools/translation/retail_text.py
from the disc extracted in toki1-decomp (its `make setup`): the decoder the
extractor, the reviewer and the build gates share.  The rows stay in sheet
order, so the lines before and after a row are its context; Speaker and Kind
say who speaks and whether it is a menu.  Edit English, Status, Notes (and
Speaker) there, in a spreadsheet, an editor or the reviewer
(tools/reviewer/app.py --sheets work/sheets in toki1-english).

`fold` copies exactly those four columns back into the tracked sheets, row by
row (matched by ID; the rows must be the same and in the same order), and
writes a tracked sheet only when a cell changed, leaving every untouched row
byte for byte as it was.  It is a three-way merge against the sheet as it was
when it was hydrated (kept in the work tree's .base/): a cell you did not
edit never overwrites a newer tracked one (after a `git pull`), and a cell
both you and the tracked sheet changed is refused as a conflict.  The Japanese never goes back: the tracked sheets
have no column for it, and a cell that would carry a Japanese line into
Notes is refused (the rule of lint_sheets.py).  Hydrate then fold with no
edit leaves the tracked sheets byte-identical.

The work tree is ignored by git (and holds its own `.gitignore` of `*`), and
`make lint` fails when any of it is tracked or staged.  `status` lists the
hydrated sheets whose edits are not folded yet.  `hydrate` will not
overwrite such a sheet without --force.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT, SHEETS, WORK  # noqa: E402
from extract_containers import FIELDS  # noqa: E402
import japanese_text  # noqa: E402

HYDRATED = WORK / "sheets"
BASE = WORK / ".base"            # each tracked sheet as it was when hydrated
FOLDED = ("Speaker", "English", "Status", "Notes")     # what fold carries back
HYDRATED_FIELDS = FIELDS[:FIELDS.index("Speaker") + 1] + ["Japanese"] + \
    FIELDS[FIELDS.index("Speaker") + 1:]


def rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def sheets(selected):
    paths = sorted(SHEETS.glob("*/*.csv"))
    if selected:
        keys = [s.split("sheets/")[-1].removesuffix(".csv") for s in selected]
        paths = [p for p in paths if any(f"{p.parent.name}/{p.stem}".startswith(k) for k in keys)]
        if not paths:
            raise SystemExit(f"hydrate: no sheet matches {' '.join(selected)}")
    return paths


def work_of(sheet: Path) -> Path:
    return HYDRATED / sheet.parent.name / sheet.name


def base_of(sheet: Path) -> Path:
    return BASE / sheet.parent.name / sheet.name


def read_rows(path: Path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, strict=True))


def records(text: str):
    """[(raw text, fields)] of a CSV text, raw text exactly as written (its
    line end included), so an untouched record is written back unchanged"""
    lines = text.splitlines(keepends=True)
    pos = 0
    consumed = []

    def feed():
        nonlocal pos
        while pos < len(lines):
            consumed.append(lines[pos])
            pos += 1
            yield lines[pos - 1]

    out = []
    for fields in csv.reader(feed(), strict=True):
        out.append(("".join(consumed), fields))
        consumed.clear()
    return out


def serialise(fields, newline="\n") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator=newline).writerow(fields)
    return buf.getvalue()


def pending(sheet: Path):
    """the cells of the hydrated copy edited since it was hydrated"""
    w = work_of(sheet)
    if not w.exists():
        return []
    b = base_of(sheet)
    tracked = {r["ID"]: r for r in read_rows(b if b.exists() else sheet)}
    diffs = []
    for r in read_rows(w):
        t = tracked.get(r["ID"])
        if t is None:
            diffs.append((r["ID"], "row", "not in the tracked sheet"))
            continue
        for col in FOLDED:
            if (r.get(col) or "") != (t.get(col) or ""):
                diffs.append((r["ID"], col, r.get(col) or ""))
    return diffs


def do_hydrate(a):
    import retail_text                  # needs the extracted disc (toki1-decomp)
    n_rows = 0
    done = []
    for sheet in sheets(a.sheets):
        w = work_of(sheet)
        if w.exists() and not a.force and pending(sheet):
            raise SystemExit(f"hydrate: {rel(w)} has edits that are not folded "
                             f"(make fold first, or --force to discard them)")
        rows = read_rows(sheet)
        try:
            retail_text.fill(rows)
        except retail_text.RetailTextError as e:
            raise SystemExit(f"hydrate: {e}\n(the Japanese is read from your disc: in "
                             f"toki1-decomp, `make setup` extracts it)")
        w.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        wr = csv.DictWriter(buf, HYDRATED_FIELDS, lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)
        w.write_text(buf.getvalue(), encoding="utf-8")
        base_of(sheet).parent.mkdir(parents=True, exist_ok=True)
        base_of(sheet).write_bytes(sheet.read_bytes())
        n_rows += len(rows)
        done.append(w)
    (WORK / ".gitignore").write_text("# hydrated from the player's disc: never committed\n*\n")
    print(f"hydrate: {len(done)} sheet(s), {n_rows:,} rows -> {rel(HYDRATED)}/ "
          f"(Japanese from your disc; edit English / Status / Notes, then make fold)")
    return 0


def fold_one(sheet: Path, dry_run=False):
    """(cells changed, refusals) for one sheet"""
    w = work_of(sheet)
    if not w.exists():
        return 0, []
    text = sheet.read_text(encoding="utf-8")
    recs = records(text)
    header = recs[0][1]
    work = read_rows(w)
    b = base_of(sheet)
    base = {r["ID"]: r for r in read_rows(b)} if b.exists() else None
    tracked_ids = [f[header.index("ID")] for _, f in recs[1:]]
    if [r["ID"] for r in work] != tracked_ids:
        return 0, [f"{rel(w)}: its rows are not the tracked sheet's rows in the same order "
                   f"(rows are never added, removed or moved here); re-hydrate it"]
    newline = "\r\n" if recs[0][0].endswith("\r\n") else "\n"
    out = [recs[0][0]]
    changed, refusals = 0, []
    for (raw, fields), r in zip(recs[1:], work):
        row = dict(zip(header, fields))
        new = dict(row)
        then = base.get(row["ID"]) if base is not None else None
        conflicts = []
        for col in FOLDED:
            if col not in header:
                continue
            mine = r.get(col) or ""
            if then is None:
                new[col] = mine                 # no base: the work copy wins
            elif mine == (then.get(col) or ""):
                continue                        # not edited here: keep the sheet's
            elif row[col] != (then.get(col) or "") and row[col] != mine:
                conflicts.append(col)           # edited here AND in the sheet
            else:
                new[col] = mine
        if conflicts:
            refusals.append(f"{rel(w)} {row['ID']}: {', '.join(conflicts)} changed both here and "
                            f"in the tracked sheet since hydrate: not folded (merge it by hand)")
            out.append(raw)
            continue
        if new == row:
            out.append(raw)
            continue
        bad = [c for c in FOLDED if c != "Notes" and japanese_text.JP_ANY_RE.search(new[c] or "")]
        if japanese_text.runs(new.get("Notes") or ""):
            bad.append("Notes")
        if bad:
            refusals.append(f"{rel(w)} {row['ID']}: Japanese in {', '.join(bad)}: not folded "
                            f"(the Japanese stays on your disc)")
            out.append(raw)
            continue
        changed += sum(1 for c in FOLDED if new.get(c) != row.get(c))
        out.append(serialise([new[c] for c in header], newline))
    if changed and not dry_run:
        sheet.write_text("".join(out), encoding="utf-8", newline="")
    if not dry_run and b.exists() and not refusals:
        b.write_bytes(sheet.read_bytes())      # the next fold merges from here
    return changed, refusals


def do_fold(a):
    total, sheets_changed, refusals = 0, 0, []
    for sheet in sheets(a.sheets):
        n, r = fold_one(sheet, a.dry_run)
        refusals += r
        if n:
            sheets_changed += 1
            total += n
            print(f"fold: {rel(sheet)}: {n} cell(s)")
    for r in refusals:
        print(f"REFUSED {r}")
    print(f"fold: {total} cell(s) in {sheets_changed} sheet(s)"
          + (" (dry run: nothing written)" if a.dry_run else "")
          + ("; now `make lint`" if total and not a.dry_run else ""))
    return 1 if refusals else 0


def do_status(a):
    n = 0
    for sheet in sheets(a.sheets):
        d = pending(sheet)
        if d:
            n += 1
            print(f"{rel(work_of(sheet))}: {len(d)} cell(s) not folded")
    print(f"status: {n} hydrated sheet(s) with edits not folded")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hydrate", help="write the work tree with the Japanese from your disc")
    h.add_argument("--force", action="store_true", help="overwrite unfolded edits")
    f = sub.add_parser("fold", help="copy English / Status / Notes / Speaker back to the sheets")
    f.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("status", help="hydrated sheets with edits not folded yet")
    for p in (h, f, s):
        p.add_argument("sheets", nargs="*", help="DIR/FILE selectors (default: every sheet)")
    a = ap.parse_args(argv)
    return {"hydrate": do_hydrate, "fold": do_fold, "status": do_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
