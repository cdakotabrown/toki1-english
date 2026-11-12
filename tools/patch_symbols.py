#!/usr/bin/env python3
"""patch_symbols.py - rename-proof name resolution for the English patch.

The symbol-naming track keeps renaming main and overlay symbols
(`D_8012B1C4` -> `serifu_state`, `func_801478F8` -> `etc_week_rank_disp`,
and occasionally one landed name -> a better one).  Its landers rewrite the
tokens they know about, but the patch side (src/patch/, config/patch/) also
names symbols and C files.  This module is the ONE place where the patch
tools turn such a name into an address, and it does so through the naming
ledger, config/symbol_names.json, so a rename can never silently change
what the patch links against:

  address-form   func_/D_/jtbl_ + 8 hex digits: the address is the name
                 (valid forever, whatever the ledger later calls it)
  current        a LANDED ledger name -> its record's address
  renamed        a name the ledger used to give an address (a landed
                 `history` entry) -> an ERROR that prints the old name, the
                 address and the current name, and the remedy
                 (tools/patch/sync_patch_symbols.py --apply)
  pinned         a name the ledger has never known, kept in
                 config/patch/symbols.json "pins" WITH a written reason
  unknown        anything else -> an ERROR

C files are named after the function they hold, so a path
src/main/matched/<name>.c / src/overlay/<OV>/<name>.c resolves the same way
(`path_key`, `current_path`).

The ledger's scopes: main records are keyed "0xADDR", overlay records
"<OV>:0xADDR" (`scope` = the overlay name).  Overlay lookups try the
overlay's own names first, then main's.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import DECOMP                                  # noqa: E402
# the naming ledger and the .sym maps are the decomp's (toki1-decomp)
LEDGER = DECOMP / "config" / "symbol_names.json"
PINS = PATCH_CONFIG / "symbols.json"
SYNC_HINT = "python3 tools/patch/sync_patch_symbols.py --apply"

ADDR_NAME_RE = re.compile(r"^(?:func|D|jtbl)_([0-9A-Fa-f]{8})$")
MAIN_PATH_RE = re.compile(r"^src/main/matched/([A-Za-z_]\w*)\.c$")
OV_PATH_RE = re.compile(r"^src/overlay/([A-Z0-9_]+)/([A-Za-z_]\w*)\.c$")


def address_form(name: str):
    m = ADDR_NAME_RE.match(name)
    return int(m.group(1), 16) if m else None


def addr_name(kind: str, addr: int) -> str:
    return f"{'func' if kind == 'func' else 'D'}_{addr:08X}"


class Resolution:
    """what a name means: `status` is one of address-form, current, renamed,
    reverted, pinned, unknown; `addr` and `name` (the current spelling) are
    set for everything but unknown."""

    def __init__(self, query, status, addr=None, name=None, scope="main",
                 why=""):
        self.query, self.status, self.addr = query, status, addr
        self.name, self.scope, self.why = name, scope, why

    @property
    def ok(self):
        return self.status in ("address-form", "current", "pinned")

    def message(self):
        where = "" if self.scope == "main" else f" ({self.scope})"
        if self.status == "renamed":
            return (f"`{self.query}`{where} no longer exists: 0x{self.addr:08X} is "
                    f"now named `{self.name}` in config/symbol_names.json "
                    f"({self.why}); run `{SYNC_HINT}`")
        if self.status == "reverted":
            return (f"`{self.query}`{where} no longer exists: its landing at "
                    f"0x{self.addr:08X} was reverted, the address is "
                    f"`{self.name}` again; run `{SYNC_HINT}`")
        if self.status == "unknown":
            return (f"`{self.query}`{where} is not an address-form name, not a "
                    f"landed name in config/symbol_names.json, not a former "
                    f"one and not pinned (with a reason) in "
                    f"config/patch/symbols.json")
        return f"`{self.query}` = 0x{self.addr:08X} ({self.status})"


class Ledger:
    """the naming ledger, indexed for the patch tools"""

    def __init__(self, path: Path = LEDGER, pins_path: Path = PINS):
        self.root = Path(path).resolve().parents[1]
        doc = json.loads(Path(path).read_text())
        self.records = {}           # (scope, addr) -> record
        self.current = {}           # scope -> {landed name: addr}
        self.former = {}            # scope -> {old landed name: [(addr, date)]}
        for key, rec in doc.get("symbols", {}).items():
            scope, _, a = key.rpartition(":")
            scope = scope or "main"
            addr = int(a, 16)
            self.records[(scope, addr)] = rec
            if rec.get("landed") and rec.get("name"):
                self.current.setdefault(scope, {})[rec["name"]] = addr
            for h in rec.get("history") or []:
                if isinstance(h, dict) and h.get("landed") and h.get("name") \
                        and h["name"] != rec.get("name"):
                    self.former.setdefault(scope, {}).setdefault(
                        h["name"], []).append((addr, h.get("date", "")))
        self.pins = {}
        pp = Path(pins_path)
        if pp.exists():
            self.pins = json.loads(pp.read_text()).get("pins", {})

    # -- by address ---------------------------------------------------------
    def name_at(self, addr: int, scope: str = "main", kind: str = None):
        """the current spelling of an address: its landed name, else the
        address-form name (kind from the record, else `kind`, else data)"""
        rec = self.records.get((scope, addr))
        if rec is not None and rec.get("landed") and rec.get("name"):
            return rec["name"]
        k = (rec or {}).get("kind") or kind or "data"
        return addr_name(k, addr)

    def landed_at(self, addr: int, scope: str = "main"):
        rec = self.records.get((scope, addr))
        if rec is not None and rec.get("landed") and rec.get("name"):
            return rec["name"]
        return None

    def sym_window(self, ov: str, addr: int):
        """(start, size) of the config/overlay/<OV>.sym window containing
        `addr` (windows may start before the prologue over an absorbed
        cross-prologue head), or None"""
        p = self.root / "config" / "overlay" / f"{ov}.sym"
        if not p.exists():
            return None
        for line in p.read_text().splitlines():
            parts = line.strip().split(":")
            if len(parts) >= 3 and parts[0].lower().startswith("0x"):
                try:
                    start, size = int(parts[0], 16), int(parts[1])
                except ValueError:
                    continue
                if start <= addr < start + size:
                    return start, size
        return None

    def func_at(self, addr: int, scope: str = "main"):
        """the ledger key address of the function a hook at `addr` patches:
        `addr` itself when a record starts there, else (overlays) the record
        inside the .sym window that contains `addr` (the prologue key of a
        head-absorbed window), else None"""
        if (scope, addr) in self.records:
            return addr
        if scope == "main":
            return None
        win = self.sym_window(scope, addr)
        if win is None:
            return None
        inside = sorted(a for (sc, a) in self.records
                        if sc == scope and win[0] <= a < win[0] + win[1])
        return inside[0] if inside else None

    # -- by name ------------------------------------------------------------
    def resolve(self, name: str, scope: str = "main") -> Resolution:
        scopes = [scope, "main"] if scope != "main" else ["main"]
        a = address_form(name)
        if a is not None:
            return Resolution(name, "address-form", a, name, scope)
        for sc in scopes:
            if name in self.current.get(sc, {}):
                return Resolution(name, "current", self.current[sc][name],
                                  name, sc)
        for sc in scopes:
            hits = self.former.get(sc, {}).get(name)
            if hits:
                addr = sorted(hits)[0][0]
                rec = self.records[(sc, addr)]
                cur = self.name_at(addr, sc)
                if rec.get("landed"):
                    return Resolution(name, "renamed", addr, cur, sc,
                                      "a former name of that record")
                return Resolution(name, "reverted", addr, cur, sc)
        pin = self.pins.get(name)
        if pin is not None:
            if not str(pin.get("reason", "")).strip():
                return Resolution(name, "unknown", scope=scope)
            return Resolution(name, "pinned", int(pin["addr"], 16), name,
                              scope, pin["reason"])
        return Resolution(name, "unknown", scope=scope)

    # -- C file paths -------------------------------------------------------
    def path_key(self, rel: str):
        """(scope, addr, Resolution) of a src/main/matched/<name>.c or
        src/overlay/<OV>/<name>.c path, or None when the path is not one"""
        m = MAIN_PATH_RE.match(rel)
        if m:
            r = self.resolve(m.group(1), "main")
            return ("main", r.addr, r) if r.addr is not None else ("main", None, r)
        m = OV_PATH_RE.match(rel)
        if m:
            ov, fn = m.groups()
            r = self.resolve(fn, ov)
            return (ov, r.addr, r) if r.addr is not None else (ov, None, r)
        return None

    def current_path(self, rel: str):
        """the path the function of `rel` lives in today (its current
        name's file), or None when it cannot be resolved"""
        k = self.path_key(rel)
        if k is None or k[1] is None:
            return None
        scope, addr, r = k
        name = self.name_at(addr, r.scope, "func")
        if scope == "main":
            return f"src/main/matched/{name}.c"
        return f"src/overlay/{scope}/{name}.c"


_LEDGER = None


def ledger() -> Ledger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = Ledger()
    return _LEDGER


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="+", help="NAME, OV:NAME or a C file path")
    a = ap.parse_args()
    L = ledger()
    bad = 0
    for q in a.names:
        if q.endswith(".c"):
            cur = L.current_path(q)
            print(f"{q} -> {cur}")
            bad += cur is None
            continue
        sc, _, nm = q.rpartition(":")
        r = L.resolve(nm, sc or "main")
        print(r.message())
        bad += not r.ok
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
