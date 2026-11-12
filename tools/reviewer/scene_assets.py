"""Extract local review art and link DATE dialogue through retail pointer tables.

No filename/nearest-string guesses become scene bindings. Outputs contain game
art and belong under gitignored extracted_assets/, never in a release binary.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from repo_paths import english_rel  # noqa: E402  (the sheets in either layout)

BASE = 0x80180000
PACK_SIZE = 45 * 2048
PAGE_OFFSETS = tuple(0x20AC + i * 0x4000 for i in range(5))
EVIDENCE = ["src/main/matched/bustup_ptr_init.c",
            "src/main/matched/bustup_sprite_init.c",
            "src/main/matched/sprite_slot_disp.c",
            "src/main/matched/search_tpage.c",
            "src/main/matched/bustup_face_set2.c",
            "src/main/matched/palette_load_vram.c"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_code(path):
    return re.sub(r"/\*.*?\*/", "", Path(path).read_text(encoding="utf-8"), flags=re.S)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() == raw:
        return
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def palette_rgba(words):
    colors = []
    for index, color in enumerate(words):
        # palette_upload_enqueue(...,16,1,2,0): row 0, mode 2.
        if index < 240:
            color &= 0x7FFF
        elif color & 0x7FFF:
            color |= 0x8000
        colors.append(((color & 31) * 255 // 31,
                       ((color >> 5) & 31) * 255 // 31,
                       ((color >> 10) & 31) * 255 // 31,
                       255 if color else 0))
    return colors


def decode_bustup(data):
    """Five 128x128 8bpp pages, CLUT row 0, six engine composition records."""
    if len(data) != PACK_SIZE:
        raise ValueError(f"Expected {PACK_SIZE} bytes, got {len(data)}")
    pointers = struct.unpack_from("<8I", data, 0x84)
    expected = tuple(BASE + offset for offset in PAGE_OFFSETS) + (BASE, BASE + 0x5C, BASE + 0x70)
    if pointers != expected or struct.unpack_from("<H", data)[0] != 6:
        raise ValueError("Unsupported bust-up pointer/cell layout")
    palette = palette_rgba(struct.unpack_from("<256H", data, 0xAC))
    pages = []
    for offset in PAGE_OFFSETS:
        image = Image.new("RGBA", (128, 128))
        image.putdata([palette[index] for index in data[offset:offset + 0x4000]])
        pages.append(image)
    cells = [struct.unpack_from("<7h", data, 8 + i * 14) for i in range(6)]
    for x, y, cel, tp, attr, width, height in cells:
        page, u, v = cel >> 6, (cel & 7) << 4, ((cel & 63) >> 3) << 4
        if not (0 <= page < 5 and -512 <= x <= 512 and -512 <= y <= 512 and
                0 < width <= 128 and 0 < height <= 128 and
                u + width <= 128 and v + height <= 128 and attr & ~3 == 0):
            raise ValueError("Composition record exceeds a page or uses unsupported attributes")
    if cells[4][5:] != (48, 32) or cells[5][5:] != (16, 16):
        raise ValueError("Unsupported face/mouth rectangle")
    left = min(0, *(c[0] for c in cells))
    top = min(0, *(c[1] for c in cells))
    size = (max(c[0] + c[5] for c in cells) - left,
            max(c[1] + c[6] for c in cells) - top)
    base = Image.new("RGBA", size)
    # sprite_slot_disp iterates cells back to front. Bias translates the whole
    # object; retaining local coordinates preserves relative layer positions.
    for x, y, cel, tp, attr, width, height in reversed(cells):
        page, u, v = cel >> 6, (cel & 7) << 4, ((cel & 63) >> 3) << 4
        part = pages[page].crop((u, v, u + width, v + height))
        if attr & 2:
            part = part.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if attr & 1:
            part = part.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        base.alpha_composite(part, (x - left, y - top))
    expressions = []
    for expression in range(6):
        image = base.copy()
        page = pages[2 + expression // 2]
        u = (expression & 1) * 64
        # Use the engine's face selectors; eye-open/mouth-rest is a reference,
        # never a claim about the animation frame for a particular line.
        image.alpha_composite(page.crop((u, 0, u + 48, 32)), (cells[4][0] - left, cells[4][1] - top))
        image.alpha_composite(page.crop((u + 48, 0, u + 64, 16)), (cells[5][0] - left, cells[5][1] - top))
        expressions.append(image)
    return pages, base, expressions, cells


def bs_dimensions(source):
    folder, name = source.parent.name, source.name
    if folder in {"FUKUTEST", "NAME_ENT", "TACO"} or (folder == "BS" and name.startswith("X_")):
        return (320, 240)
    if folder == "BS" and name.startswith("C_"):
        return (320, 88)
    return (320, 160)


def read_lbas(path):
    entries = {}
    pattern = r'\{\s*"([^"\n]+)",\s*(\d+),\s*(\d+)\s*\}'
    for name, lba, size in re.findall(pattern, Path(path).read_text(encoding="utf-8")):
        if int(lba) in entries:
            raise ValueError(f"Duplicate LBA {lba}")
        entries[int(lba)] = dict(source=name, size=int(size))
    if not entries:
        raise ValueError("File/LBA table has no entries")
    return entries


def pointer_assignments(code):
    return {name.upper(): int(value, 16) for name, value in re.findall(
        r"\b(D_[0-9A-Fa-f]+)\s*=\s*\(s32\)\s*(0x[0-9A-Fa-f]+)", code)}


def dialogue_references(data, base, root, kind, text_offsets):
    """Walk two parallel tables exactly as serifu_main does; return row offsets.

    The kind pointers address byte sequences after the root pointer array and
    before the kind-pointer array. 0xff terminates each sequence. Only target
    addresses already present in the exact CSV extraction can bind a row.
    """
    root, kind = root - base, kind - base
    if not (0 <= root < kind < len(data)) or root % 4 or kind % 4:
        raise ValueError("Dialogue root/kind tables outside the loaded container")
    fence, group = kind, 0
    found = {}
    while root + group * 4 < fence:
        if group >= 256 or kind + group * 4 + 4 > len(data):
            raise ValueError("Unbounded dialogue group table")
        pointer = struct.unpack_from("<I", data, root + group * 4)[0] - base
        types = struct.unpack_from("<I", data, kind + group * 4)[0] - base
        if not (0 <= pointer < root <= types < kind):
            raise ValueError("Invalid parallel dialogue/kind pointer")
        fence = min(fence, types)
        for index in range(256):
            if types + index >= kind:
                raise ValueError("Kind sequence missing 0xff terminator")
            if data[types + index] == 255:
                break
            site = pointer + index * 4
            if site + 4 > root:
                raise ValueError("Dialogue string-pointer array exceeds its region")
            offset = struct.unpack_from("<I", data, site)[0] - base
            if offset in text_offsets:
                found.setdefault(offset, []).append(dict(group=group, index=index, pointer_site=hex(site), command=data[types + index]))
        else:
            raise ValueError("Kind sequence exceeds 256 commands")
        group += 1
    return found


def date_loads(root, lbas):
    code = source_code(root / "src/overlay/DATE/date_girl_cdread.c")
    result = []
    # Default is the eleventh heroine in this validated loader, not an
    # arbitrary default-case inference in other source files.
    for match in re.finditer(r"(?:case\s+(\d+)|default)\s*:\s*(date_girl\w*_ptr_set)\(\);\s*cd_read_start2\(\s*\d+,\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+)\)", code):
        girl = int(match[1]) if match[1] else 10
        file = lbas[int(match[4], 16)]["source"]
        if not file.startswith("CDROM/SERIFU/DATE_"):
            raise ValueError(f"DATE loader points to unexpected file {file}")
        result.append(dict(girl=girl, setter=match[2], base=int(match[3], 16), source=file))
    if sorted(row["girl"] for row in result) != list(range(11)):
        raise ValueError("DATE loader is not the expected eleven-character dispatcher")
    return result


def scene_producers(root):
    producers = []
    for path in sorted((root / "src/overlay/DATE").glob("*.c")):
        code = source_code(path)
        text = re.search(r"\b(?:ss_serifu|ss_s)\s*=\s*(D_[0-9A-Fa-f]+)\s*;", code)
        kind = re.search(r"\b(?:ss_serifu_kind|ss_s_kind)\s*=\s*(D_[0-9A-Fa-f]+)\s*;", code)
        if not text or not kind:
            continue
        backgrounds = sorted({int(v, 0) for v in re.findall(r"\bdec_bg_cache_step\(\s*(0x[0-9A-Fa-f]+|\d+)\s*\)", code)})
        producers.append(dict(source=path.relative_to(root).as_posix(), label=path.stem,
                              root=text[1].upper(), kind=kind[1].upper(), backgrounds=backgrounds))
    return producers


def extract_art(root, out, force=False, decomp=None):
    """`decomp`: the tree holding the extracted disc and tools/assets
    (toki1-decomp; default `root`, the monorepo layout)."""
    decomp = decomp or root
    cdrom = decomp / "assets/extracted_iso/CDROM"
    previous = out / "asset-manifest.json"
    old = json.loads(previous.read_text()) if previous.exists() else {}
    decoder_sha256 = digest(Path(__file__))
    cached = {row["source"]: row for row in old.get("assets", [])}
    assets, failures = [], []
    files = sorted(cdrom.rglob("*.BS")) + sorted((cdrom / "BUSTUP").glob("*.BIN"))
    if not files:
        raise ValueError("No local BS/BUSTUP sources; supply the extracted legal disc first")
    for source in files:
        name = source.relative_to(decomp / "assets/extracted_iso").as_posix()
        sha = digest(source)
        record = dict(source=name, source_sha256=sha)
        prior = cached.get(name)
        if not force and old.get("decoder_sha256") == decoder_sha256 and prior and prior["source_sha256"] == sha and all(
                (out / file).is_file() and digest(out / file) == checksum
                for file, checksum in prior.get("output_hashes", {}).items()) and prior.get("output_hashes"):
            assets.append(prior)
            continue
        try:
            if source.suffix == ".BS":
                relative = Path("backgrounds") / source.relative_to(cdrom).with_suffix(".png")
                dest = out / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dimensions = bs_dimensions(source)
                # Decode anew on the first run; an existing PNG without a
                # source hash is not sufficient provenance for this manifest.
                with tempfile.TemporaryDirectory(prefix="review-bs-", dir=dest.parent) as temp:
                    copy = Path(temp) / source.name
                    shutil.copyfile(source, copy)
                    process = subprocess.run([str(decomp / "tools/assets/jpsxdec.sh"), "-f", str(copy), "-static", "bs", "-dim", f"{dimensions[0]}x{dimensions[1]}", "-fmt", "png"], cwd=temp, capture_output=True, text=True, timeout=30)
                    made = copy.with_suffix(".png")
                    if process.returncode or not made.exists():
                        raise ValueError("jPSXdec failed: " + (process.stdout + process.stderr)[-400:])
                    with Image.open(made) as image:
                        image.load()
                        if image.size != dimensions:
                            raise ValueError("Decoded BS dimensions disagree with the game call-site family")
                    os.replace(made, dest)
                record.update(kind="background", image=relative.as_posix(), dimensions=list(dimensions), evidence="tools/assets/convert_media.py:do_bs_stills; game-derived MDEC size families")
                outputs = [relative.as_posix()]
            else:
                pages, base, expressions, cells = decode_bustup(source.read_bytes())
                folder = Path("characters") / source.stem
                (out / folder).mkdir(parents=True, exist_ok=True)
                outputs = []
                for name_suffix, image in [("base", base)] + [(f"page-{i}", page) for i, page in enumerate(pages)] + [(f"expression-{i}", image) for i, image in enumerate(expressions)]:
                    relative = (folder / (name_suffix + ".png")).as_posix()
                    image.save(out / relative)
                    outputs.append(relative)
                record.update(kind="character", pack=source.stem, image=(folder / "base.png").as_posix(), pages=[(folder / f"page-{i}.png").as_posix() for i in range(5)], expressions=[(folder / f"expression-{i}.png").as_posix() for i in range(6)], cells=[list(cell) for cell in cells], dimensions=list(base.size), evidence=EVIDENCE, animation_note="All five source pages include eye/mouth animation art; composed previews use open eyes and resting mouth, not a captured runtime frame.")
            record["output_hashes"] = {file: digest(out / file) for file in outputs}
            assets.append(record)
        except (OSError, ValueError, struct.error, subprocess.SubprocessError) as exc:
            raw = out / "raw" / name
            raw.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, raw)
            failures.append(dict(source=name, source_sha256=sha, reason=str(exc),
                                 raw=raw.relative_to(out).as_posix()))
        print(f"art {len(assets) + len(failures)}/{len(files)} {name}", flush=True)
    report = dict(version=1, decoder_sha256=decoder_sha256, scope="Every standalone BS and every BUSTUP BIN in the supplied CDROM filesystem; excludes models/UI NBN atlases", assets=assets, failures=failures,
                  counts=dict(Counter(row["kind"] for row in assets)))
    write_json(previous, report)
    return report


def build_context(root, out, art, decomp=None, pc=None):
    """`decomp` holds the C tree and the extracted disc, `pc` the PC port's
    file/LBA table (default `root` for both, the monorepo layout)."""
    decomp, pc = decomp or root, pc or root
    lbas = read_lbas(pc / "pc/src/file_lba_table.c")
    assets = {row["source"]: row for row in art["assets"]}
    producers = scene_producers(decomp)
    rows, characters, errors = {}, {}, []
    coverage = []
    for loader in date_loads(decomp, lbas):
        source = decomp / "assets/extracted_iso" / loader["source"]
        code = source_code(decomp / "src/overlay/DATE" / (loader["setter"] + ".c"))
        assignments = pointer_assignments(code)
        sheet = root / english_rel("translation/localization/sheets/SERIFU", root) / (source.stem + ".csv")
        with sheet.open(encoding="utf-8", newline="") as stream:
            records = {int(row["Offset"], 0): row for row in csv.DictReader(stream)}
        data = source.read_bytes()
        # Match the heroine's sprite family through her actual seasonal CD
        # requests, not through a guessed Japanese/English filename spelling.
        seasons = source_code(decomp / "src/main/matched/girl_season_load.c")
        match = re.search(rf"case\s+{loader['girl']}\s*:(.*?)(?=\bcase\s+\d+\s*:|\Z)", seasons, re.S)
        ids = [int(v, 0) for v in re.findall(r"bustup_cd_read\((0x[0-9A-Fa-f]+|\d+)\)", match[1] if match else "")]
        if len(ids) != 4:
            raise ValueError(f"Seasonal loader for character {loader['girl']} is no longer the expected four branches")
        seasonal = [lbas[value]["source"] for value in ids]
        prefix = Path(seasonal[0]).stem[:2]
        character_assets = [row for row in art["assets"] if row["kind"] == "character" and row["pack"].startswith(prefix)]
        character_assets.sort(key=lambda row: (seasonal.index(row["source"]) if row["source"] in seasonal else 999, row["pack"]))
        options = []
        for asset in character_assets:
            try:
                season = ["Months 3–5", "Months 6–8", "Months 9–11", "Months 12, 1, 2"][seasonal.index(asset["source"])]
            except ValueError:
                season = "Other costume/reference; scene condition unresolved"
            for expression, image in enumerate(asset["expressions"]):
                options.append(dict(label=f"{asset['pack']} · {season} · expression {expression}", image=image, pack=asset["pack"], expression=expression, evidence="src/main/matched/girl_season_load.c; " + "; ".join(EVIDENCE), certainty="reference variant; active outfit/expression not established"))
        character_key = str(loader["girl"])
        characters[character_key] = dict(options=options, prefix=prefix,
                                         source=loader["source"], certainty="character established by DATE loader; outfit/expression conditional")
        for producer in producers:
            if producer["root"] not in assignments or producer["kind"] not in assignments:
                continue
            try:
                refs = dialogue_references(data, loader["base"], assignments[producer["root"]], assignments[producer["kind"]], records)
            except ValueError as exc:
                errors.append(dict(source=loader["source"], producer=producer["source"], reason=str(exc)))
                continue
            backgrounds = []
            for lba in producer["backgrounds"]:
                source_name = lbas.get(lba, {}).get("source")
                asset = assets.get(source_name)
                if asset and asset["kind"] == "background":
                    backgrounds.append(dict(label=f"{Path(source_name).stem} · loaded by dialogue setup", image=asset["image"], source=source_name, lba=lba, evidence=producer["source"], certainty="setup call established; branch/timing not resolved"))
            for offset, sites in refs.items():
                record = records[offset]
                # Require an actual pointer site from exact extraction, not
                # merely a numerically matching word somewhere in the file.
                csv_sites = {int(value, 0) for value in re.findall(r"0x[0-9A-Fa-f]+|\d+", record.get("PtrSite", ""))}
                linked = [site for site in sites if int(site["pointer_site"], 0) in csv_sites]
                if not linked:
                    errors.append(dict(source=loader["source"], row=record["ID"], producer=producer["source"], reason="No CSV pointer-site corroboration"))
                    continue
                # Source function names include old, incorrect venue guesses.
                # Display asset IDs; preserve function names only as evidence.
                label = " / ".join(Path(bg["source"]).stem for bg in backgrounds) or "Shared dialogue / background unresolved"
                variant = dict(label=label, producer=producer["label"], evidence=f"{producer['source']} + src/overlay/DATE/{loader['setter']}.c + exact CSV PtrSite", character_id=character_key, background_options=backgrounds, dialogue_sites=linked, background_certainty="conditional" if backgrounds else "unknown", expression_certainty="unknown; reference variants available")
                rows.setdefault(record["ID"], []).append(variant)
        count = sum(record["ID"] in rows for record in records.values())
        coverage.append(dict(sheet=sheet.relative_to(root).as_posix(), rows=len(records), linked=count, unresolved=len(records) - count))
        for record in records.values():
            if record["ID"] not in rows:
                rows[record["ID"]] = [dict(label="DATE character reference; scene unresolved", character_id=character_key, evidence="src/overlay/DATE/date_girl_cdread.c establishes the script's character; no validated dialogue-graph binding for this row", background_certainty="unknown", expression_certainty="unknown; costume references only")]
    total_rows = 0
    sheet_coverage = []
    for path in sorted((root / english_rel("translation/localization/sheets", root)).rglob("*.csv")):
        counts = Counter()
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                total_rows += 1
                counts["rows"] += 1
                variants = rows.get(row["ID"], [])
                counts["dialogue_linked"] += any(v.get("dialogue_sites") for v in variants)
                counts["background_linked"] += any(v.get("background_options") for v in variants)
                counts["character_reference"] += any("character_id" in v for v in variants)
        sheet_coverage.append(dict(sheet=path.relative_to(root).as_posix(), **counts))
    context = dict(version=1, generated=True, rows=rows, characters=characters,
                   asset_manifest="asset-manifest.json", coverage=coverage,
                   total_rows=total_rows, sheet_coverage=sheet_coverage, mapping_errors=errors,
                   unresolved_reason="No validated loader/dialogue-graph binding; CSV order or speaker alone does not establish a scene.")
    write_json(out / "scene-context.json", context)
    return context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        help="the tree with translation/ and extracted_assets/ "
                             "(default: this checkout); with --root, the C tree, "
                             "disc and PC table are read there too")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.root:
        root = decomp = pc = args.root.resolve()
    else:
        import sys
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / "tools"))
        from repo_paths import DECOMP, PC
        decomp = DECOMP
        if PC is None:
            parser.error("the DATE scene context needs the PC port's file/LBA "
                         "table (pc/src/file_lba_table.c): check out toki1-pc "
                         "next to this repository or set TOKI_PC_DIR")
        pc = PC
    out = (args.out or root / "extracted_assets/reviewer").resolve()
    if not out.is_relative_to(root / "extracted_assets"):
        parser.error("Generated output must be below the repository's extracted_assets directory")
    out.mkdir(parents=True, exist_ok=True)
    art = extract_art(root, out, args.force, decomp)
    context = build_context(root, out, art, decomp, pc)
    summary = dict(assets=art["counts"], extraction_failures=len(art["failures"]), date_sheets=context["coverage"], mapping_errors=len(context["mapping_errors"]), total_rows=context["total_rows"],
                   dialogue_linked=sum(row["dialogue_linked"] for row in context["sheet_coverage"]), background_linked=sum(row["background_linked"] for row in context["sheet_coverage"]), character_reference=sum(row["character_reference"] for row in context["sheet_coverage"]))
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 1 if art["failures"] or context["mapping_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
