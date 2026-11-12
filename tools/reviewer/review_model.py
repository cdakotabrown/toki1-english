"""Portable CSV review/storage and evidence-based context, without GUI imports."""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile

# D4: the retail Japanese of a row lives in tools/translation/retail_text.py,
# the same module the patch build uses to read the sheets.
# (tools/translation here; tools/ in the public layout, where this is tools/reviewer)
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "tools" / "translation"),
                str(Path(__file__).resolve().parents[2] / "tools")]
import retail_text  # noqa: E402

TOKEN = re.compile(r"\{(br|opt|P|G|p|m|F|Y|S|O|W|A|M)\}")
EDITABLE = {"English", "Notes"}


def script_to_editor(text: str) -> str:
    """Display message breaks; leave name/choice/control tokens intact."""
    return text.replace("{br}", "\n")


def editor_to_script(text: str) -> str:
    """Normalize pasted Windows/Mac newlines into the stored script token."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "{br}")


def japanese_font(families) -> str | None:
    available = {family.casefold(): family for family in families}
    for family in ("Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Noto Sans JP",
                   "Source Han Sans JP", "Hiragino Sans", "Hiragino Kaku Gothic ProN",
                   "IPAexGothic", "IPAGothic", "TakaoGothic", "MS Gothic"):
        if family.casefold() in available:
            return available[family.casefold()]
    return None


class ReviewError(Exception):
    pass


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_safely(path: Path, data: bytes, expected: str | None) -> Path | None:
    """Cooperating-writer lock, conflict detection, backup, atomic publication."""
    path = Path(path)
    lock = path.with_name(path.name + ".review-save.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ReviewError(f"Another save holds {lock}. No data was written.") from exc
    temporary = None
    backup = None
    try:
        os.close(fd)
        current = path.read_bytes() if path.exists() else None
        if (fingerprint(current) if current is not None else None) != expected:
            raise ReviewError("File changed outside the editor. Reopen it before saving; your edits remain in memory.")
        if current == data:
            return None
        if current is not None:
            backups = path.parent / ".review-backups"
            backups.mkdir(exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".bak", dir=backups)
            backup = Path(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(current)
                stream.flush()
                os.fsync(stream.fileno())
        fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Detect edits made during serialization/backup as well.
        latest = path.read_bytes() if path.exists() else None
        if latest != current:
            raise ReviewError("File changed during save; no replacement was made.")
        os.replace(temporary, path)
        return backup
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


@dataclass(frozen=True)
class Issue:
    level: str
    message: str


def audit(row: dict[str, str]) -> list[Issue]:
    """Project token/charset/budget rules, plus per-choice completeness checks."""
    ja, en = row["Japanese"], row["English"]
    issues = []
    if not en.strip():
        issues.append(Issue("error", "English is blank."))
    need = Counter(t for t in TOKEN.findall(ja) if t != "br")
    have = Counter(t for t in TOKEN.findall(en) if t != "br")
    if need != have:
        issues.append(Issue("error", f"Required tokens differ: JP {dict(need)}, EN {dict(have)}."))
    if row.get("Kind") == "choice" and en.strip():
        jp_choices, en_choices = ja.split("{opt}"), en.split("{opt}")
        if len(jp_choices) == len(en_choices):
            for index, (jp_choice, en_choice) in enumerate(zip(jp_choices, en_choices), 1):
                if jp_choice.strip() and not en_choice.strip():
                    issues.append(Issue("error", f"Choice {index} is blank."))
                jp_tokens = Counter(t for t in TOKEN.findall(jp_choice) if t != "br")
                en_tokens = Counter(t for t in TOKEN.findall(en_choice) if t != "br")
                if jp_tokens != en_tokens:
                    issues.append(Issue("error", f"Choice {index} has different name/runtime tokens from Japanese."))
    plain = TOKEN.sub("", en)
    if "{" in plain or "}" in plain:
        issues.append(Issue("error", "Unknown token or unmatched brace."))
    bad = sorted({c for c in plain if not 0x20 <= ord(c) < 0x7F})
    if bad:
        issues.append(Issue("error", f"Non-ASCII characters: {''.join(bad)!r}. Use {{br}} for line breaks."))
    length = encoded_length(en)
    if length > 255:
        issues.append(Issue("error", f"Encoded length {length} exceeds the 255-byte hard limit."))
    try:
        budget = int(row.get("MaxBytes", ""), 0)
    except ValueError:
        issues.append(Issue("warning", "In-place byte budget is unavailable."))
    else:
        if length > budget:
            issues.append(Issue("warning", f"{length} bytes exceeds in-place budget {budget}; relocation is needed."))
    return issues


def encoded_length(text: str) -> int:
    return len(TOKEN.sub("\x01", text))


class Sheet:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        raw = self.path.read_bytes()
        self.original_hash = fingerprint(raw)
        self.encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
        text = raw.decode(self.encoding)
        self.newline = "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        self.columns = reader.fieldnames or []
        if len(set(self.columns)) != len(self.columns):
            raise ReviewError("Duplicate CSV columns.")
        if not {"ID", "English"} <= set(self.columns):
            raise ReviewError("Open an exact localization sheet with ID and English columns. Legacy run-scan CSVs are unsupported.")
        # D4: the sheets carry no Japanese; it is read from the player's disc by
        # File+Offset (retail_text), the same way the extractor produced it.
        self.external_japanese = "Japanese" not in self.columns
        if self.external_japanese and not {"File", "Offset"} <= set(self.columns):
            raise ReviewError("A sheet without a Japanese column needs File and Offset so the Japanese can be read from the disc.")
        self.rows = []
        seen = set()
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ReviewError(f"Malformed CSV record near line {reader.line_num}.")
            if not row["ID"] or row["ID"] in seen:
                raise ReviewError(f"Empty or duplicate ID near line {reader.line_num}.")
            seen.add(row["ID"])
            self.rows.append(row)
        if self.external_japanese:
            retail_text.fill(self.rows)
        self.original = [dict(row) for row in self.rows]

    @property
    def changed(self) -> list[int]:
        return [i for i, row in enumerate(self.rows) if row != self.original[i]]

    def edit(self, index: int, field: str, text: str) -> None:
        if field not in EDITABLE or field not in self.columns:
            raise ReviewError(f"Column {field} is read-only.")
        self.rows[index][field] = text

    def save(self, allow_issues: bool = False) -> Path | None:
        changed = self.changed
        if not changed:
            return None
        for i in changed:
            row, old = self.rows[i], self.original[i]
            if set(row) != set(old) or any(row[k] != old[k] for k in old if k not in EDITABLE):
                raise ReviewError("Read-only columns changed; saving refused.")
            if old.get("Status", "").lower() == "final" and row["English"] != old["English"]:
                if not row.get("Notes", "").strip() or row.get("Notes") == old.get("Notes"):
                    raise ReviewError("A changed final row needs an explanatory note before saving.")
            if not allow_issues and any(issue.level == "error" for issue in audit(row)):
                raise ReviewError("Changed rows have QA errors. Review the warnings before saving.")
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, self.columns, lineterminator=self.newline)
        writer.writeheader()
        # rows may carry an injected 'Japanese' that is not a column (D4)
        writer.writerows([{k: row[k] for k in self.columns} for row in self.rows])
        data = buffer.getvalue().encode(self.encoding)
        backup = replace_safely(self.path, data, self.original_hash)
        self.original_hash = fingerprint(data)
        self.original = [dict(row) for row in self.rows]
        return backup


def read_bible(path: Path) -> list[dict[str, str]]:
    entries = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] not in {"Code", "---"} and not set(cells[0]) <= {"-"}:
            entries.append(dict(zip(("code", "name", "role", "japanese_voice", "english_voice"), cells)))
    return entries


def bible_for(speaker: str, entries: list[dict[str, str]]) -> dict[str, str] | None:
    key = speaker.strip().casefold()
    if key.startswith("player"):
        key = "the player"
    for entry in entries:
        name = entry["name"].split(" (`")[0].casefold()
        if name == key:
            return entry
    if key.startswith("other"):
        return next((e for e in entries if e["code"] == "OT"), None)
    return None


class SceneContext:
    """Exact row IDs -> one or more explicitly supplied scene variants."""
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        raw = self.path.read_bytes() if self.path.exists() else None
        self.original_hash = fingerprint(raw) if raw is not None else None
        self.data = json.loads(raw) if raw else {"version": 1, "rows": {}}
        if not isinstance(self.data, dict) or self.data.get("version") != 1 or not isinstance(self.data.get("rows"), dict):
            raise ReviewError("Context needs version 1 and a rows object.")
        for key, variants in self.data["rows"].items():
            if not isinstance(key, str) or not isinstance(variants, list) or not all(isinstance(v, dict) for v in variants):
                raise ReviewError("Each context row ID must map to a list of scene objects.")
            for variant in variants:
                for field in ("label", "evidence", "screenshot", "background", "sprite", "outfit"):
                    if field in variant and not isinstance(variant[field], str):
                        raise ReviewError(f"Context {field} must be text.")
                position = variant.get("sprite_position", [0, 0])
                if not isinstance(position, list) or len(position) != 2 or any(type(v) is not int or abs(v) > 4096 for v in position):
                    raise ReviewError("sprite_position must contain two bounded integer coordinates.")

    def variants(self, row_id: str) -> list[dict]:
        return self.data["rows"].get(row_id, [])

    def image_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.path.parent / path

    def add(self, row_id: str, variant: dict) -> Path | None:
        if not variant.get("label", "").strip() or not variant.get("evidence", "").strip():
            raise ReviewError("A scene label and evidence/source note are required.")
        # Keep memory unchanged if disk publication fails.
        updated = json.loads(json.dumps(self.data))
        updated["rows"].setdefault(row_id, []).append(variant)
        raw = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        backup = replace_safely(self.path, raw, self.original_hash)
        self.data, self.original_hash = updated, fingerprint(raw)
        return backup


def render_scene(context: SceneContext, variant: dict):
    """Show a capture, or explicitly supplied RGBA layers. Never invent art."""
    from PIL import Image
    if variant.get("screenshot"):
        with Image.open(context.image_path(variant["screenshot"])) as image:
            return image.convert("RGBA")
    if not variant.get("background"):
        raise ReviewError("No screenshot/background mapped for this scene variant.")
    with Image.open(context.image_path(variant["background"])) as image:
        canvas = image.convert("RGBA")
    if variant.get("sprite"):
        with Image.open(context.image_path(variant["sprite"])) as image:
            sprite = image.convert("RGBA")
        canvas.alpha_composite(sprite, tuple(variant.get("sprite_position", [0, 0])))
    return canvas
