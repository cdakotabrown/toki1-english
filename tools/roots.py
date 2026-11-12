"""Where the English patch finds its files, and the files it does not own.

The English patch (toki1-english) reads, but never writes, the decompiled
tree (toki1-decomp): the C sources, include/, the symbol ledger and .sym
maps, the IDO toolchain, the clean main/EXN builds under its build/, and
the disc inputs its setup extracted (disks/, assets/).  It may also use a
few PC-port tools (toki1-pc, optional).  docs/REPO-SPLIT-PLAN.md is the
contract; tools/repo_paths.py resolves the roots.  In the monorepo all
three roots are the repository root and nothing changes.

The English files themselves have two layouts: the monorepo's
(translation/localization/sheets, src/patch/main, config/patch, ...) and
the flat public one (sheets/, patch/, config/, ...; tools/repo_paths.py
ENGLISH_LAYOUT).  Code names them by the monorepo path; locate() maps it
to the layout this checkout has.

    from roots import ROOT, DECOMP, PC, locate, rel
    ROOT    this checkout (the English files, build/patch)
    PUBLIC  True in a published toki1-english checkout (the flat layout)
    DECOMP  toki1-decomp (always present)
    PC      toki1-pc, or None
    locate("assets/extracted_iso/CDROM/X.BIN")  -> the file in the part
            that owns that repository path; an English path is mapped to
            this checkout's layout ("translation/localization/sheets" ->
            ROOT/"sheets" in the public layout)
    rel(path)  a report-friendly spelling: relative to ROOT when inside it,
            else relative to DECOMP / PC prefixed with that root's name
    pc_path("tools/x.py", what)  the PC file, or exit saying why

    SHEETS, GUIDE, CONTAINERS, ART, PATCH_SRC, PATCH_CONFIG, TOOLS_PATCH,
    TOOLS_TRANSLATION, REVIEWER, WORK   the English locations, as Paths

Importing this module also puts the English tool directories on sys.path
(tools/patch and tools/translation here; tools/ in the public layout), so a
tool imports its siblings by module name in either layout.
"""
import os
import sys
from pathlib import Path


def _find_root():
    here = Path(__file__).resolve().parent
    for d in (here, *here.parents):
        if (d / "tools" / "repo_paths.py").is_file():
            return d
    raise SystemExit(f"{__file__}: no tools/repo_paths.py above it")


ROOT = _find_root()
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
from repo_paths import DECOMP, PC, english_layout, english_rel  # noqa: E402

PUBLIC = english_layout(ROOT) == "public"

# repository paths owned by the English patch; everything else a patch tool
# names by a repository-relative path belongs to toki1-decomp (the disc
# inputs live there too: disks/, assets/)
ENGLISH_PREFIXES = ("translation/", "tools/patch/", "tools/translation/",
                    "config/patch/", "src/patch/", "docs/translation/",
                    "docs/learnings/patch-",
                    "docs/archive/source-comments/src__patch__",
                    "build/patch/", "build/patch")
# the public spellings no other part uses (tools/repo_paths.py logical_path)
PUBLIC_PREFIXES = ("sheets/", "guide/", "art/", "patch/", "work/")
PC_PREFIXES = ("pc/", "src/main/pc-port/")
# decomp-owned paths, disc inputs and the decomp's clean builds; any other
# build/ path is this checkout's own output
DECOMP_PREFIXES = ("disks/", "assets/", "extracted_assets/", "src/",
                   "include/", "config/", "asm/", "tools/", "docs/",
                   "wiki/",
                   "build/SLPS_000.65.clean", "build/overlay/")
_ENGLISH_DIRS = ("translation", "tools/patch", "tools/translation",
                 "config/patch", "src/patch", "docs/translation")


def locate(rel_path) -> Path:
    """The file a repository-relative path names, in the part that owns it.
    Absolute paths are returned unchanged."""
    p = Path(rel_path)
    if p.is_absolute():
        return p
    s = p.as_posix()
    if s.startswith(PC_PREFIXES):
        return (PC if PC is not None else ROOT) / p
    if s.startswith(PUBLIC_PREFIXES) or s + "/" in PUBLIC_PREFIXES:
        return ROOT / english_rel(s, ROOT)
    if s.startswith(ENGLISH_PREFIXES) or s in _ENGLISH_DIRS \
            or not s.startswith(DECOMP_PREFIXES):
        return ROOT / english_rel(s, ROOT)
    if PUBLIC and s.startswith(("config/", "tools/", "docs/")) and (ROOT / p).exists():
        # a public spelling (config/english.json): toki1-english's own
        # config/, tools/ and docs/ share no file name with toki1-decomp's
        # (export_split.py --check), so a file that is here is this one
        return ROOT / p
    return DECOMP / p


def rel(path) -> str:
    """`path` for a report: ROOT-relative inside this checkout (the monorepo
    spelling), otherwise relative to the part it lives in, prefixed with
    that checkout's directory name."""
    p = Path(path)
    if not p.is_absolute():
        return str(p)
    for base, tag in ((ROOT, None), (DECOMP, DECOMP.name),
                      (PC, PC.name if PC is not None else None)):
        if base is None:
            continue
        try:
            r = p.relative_to(base)
        except ValueError:
            continue
        return str(r) if tag is None else f"../{tag}/{r}"
    return str(p)


def pc_path(rel_path: str, what: str = "this tool") -> Path:
    """A file of the PC port, or exit saying why it is unavailable."""
    if PC is None:
        sys.exit(f"{what} needs the PC port (toki1-pc, for {rel_path}): check "
                 f"it out next to this repository or set TOKI_PC_DIR")
    p = PC / rel_path
    if not p.exists():
        sys.exit(f"{what}: {p} does not exist")
    return p


class _NoRefEmu:
    """Stand-in for pc/tools/refemu.py when there is no PC checkout: the
    host comes from REFEMU_REGTEST only, and explain() says what is missing."""

    @staticmethod
    def regtest():
        return os.environ.get("REFEMU_REGTEST") or str(
            ROOT / "local" / "refemu" / "regtest")

    @staticmethod
    def explain(what="this"):
        return (f"{what} needs the reference emulator's regtest host; no PC "
                f"port checkout (toki1-pc) was found to locate it, and "
                f"REFEMU_REGTEST is not an executable: set it, or check out "
                f"toki1-pc next to this repository (pc/tools/refemu.py, "
                f"docs/pc-port/REFERENCE-EMULATOR.md)")


def refemu():
    """The reference-emulator locator (pc/tools/refemu.py of the PC port),
    or a stand-in that only honours REFEMU_REGTEST when there is no PC
    checkout.  The emulator tools are optional, never part of the build."""
    if PC is None:
        return _NoRefEmu
    tools = PC / "pc" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import refemu as mod
    return mod


SHEETS = locate("translation/localization/sheets")
GUIDE = locate("translation/localization")
CONTAINERS = locate("translation/localization/containers.json")
ART = locate("src/patch/art")
PATCH_SRC = locate("src/patch/main")
PATCH_CONFIG = locate("config/patch")
TOOLS_PATCH = locate("tools/patch")
TOOLS_TRANSLATION = locate("tools/translation")
REVIEWER = locate("translation/reviewer")
WORK = locate("translation/work")

for _d in (TOOLS_TRANSLATION, TOOLS_PATCH):
    if str(_d) not in sys.path:
        sys.path.insert(1, str(_d))


def same_tree() -> bool:
    """True in the monorepo (one checkout holds every part)."""
    return DECOMP == ROOT


__all__ = ["ROOT", "PUBLIC", "DECOMP", "PC", "locate", "rel", "pc_path",
           "refemu", "same_tree", "SHEETS", "GUIDE", "CONTAINERS", "ART",
           "PATCH_SRC", "PATCH_CONFIG", "TOOLS_PATCH", "TOOLS_TRANSLATION",
           "REVIEWER", "WORK"]
