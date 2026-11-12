#!/usr/bin/env python3
"""Tests for the English patch's rename-proofing: tools/patch/patch_symbols.py
(ledger resolution), tools/patch/sync_patch_symbols.py (rewrites the patch
side to the ledger's current names) and the build's resolver
(build_patched.SymbolPins) and compose_check's coverage, on a throw-away
tree with a hand-made ledger.

    python3 tools/patch/test_sync_patch_symbols.py [-v]
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import patch_symbols as PS  # noqa: E402
import sync_patch_symbols as SPS  # noqa: E402

LEDGER = {
    "symbols": {
        # a data name renamed once: old_state -> serifu_state
        "0x8012B1C4": {"name": "serifu_state", "kind": "data", "landed": True,
                       "history": [{"name": "old_state", "kind": "data",
                                    "landed": True, "date": "2026-10-01"},
                                   "a free-text note"]},
        # landed, still spelled D_8012B1F8 in the patch C
        "0x8012B1F8": {"name": "msg_wait", "kind": "data", "landed": True},
        # a function whose landing was reverted (the address is func_ again)
        "0x80043338": {"name": "func_80043338", "kind": "func", "landed": False,
                       "history": [{"name": "konami_command_step",
                                    "kind": "func", "landed": True}]},
        "0x80081398": {"name": "msg_str_disp", "kind": "func", "landed": True},
        # retail load_string renamed; the patch DEFINES its own load_string
        "0x8004F690": {"name": "kanji_load", "kind": "func", "landed": True,
                       "history": [{"name": "load_string", "kind": "func",
                                    "landed": True}]},
        "0x800B48B0": {"name": "bios_strncat", "kind": "func", "landed": True,
                       "history": [{"name": "strncat", "kind": "func",
                                    "landed": True}]},
        "0x800B5000": {"name": "Gs_old_free", "kind": "func", "landed": True},
        # an unlanded proposal: its name is not current
        "0x800B6000": {"name": "maybe_name", "kind": "data", "landed": False},
        "TEL:0x80132274": {"name": "tel_yoshio_intro", "kind": "func",
                           "landed": True, "scope": "TEL"},
        "TEL:0x80132FCC": {"name": "tel_yoshio_menu", "kind": "func",
                           "landed": True, "scope": "TEL",
                           "history": [{"name": "tel_menu", "landed": True}]},
    }
}

C_SRC = """/* old_state is the dialogue state (comment: renamed too) */
extern s32 old_state;
extern s32 D_8012B1F8;
extern void konami_command_step(void);
static const char *pt_msg = "old_state stays in a string } {";
static const char pt_ch = '}';

void load_string(void)
{
    if (pt_ch == '{') {
        old_state = 1;
    }
    D_8012B1F8 = 2;
    konami_command_step();
}
"""

PROFILE = {
    "name": "t",
    "main": {
        "module": {
            "sources": ["src/patch/main/a.c"],
            "hooks": [
                {"function": "load_string", "addr": "0x8004F690", "target": "load_string"},
                {"function": "func_80081398", "addr": "0x80081398", "target": "pt_x"},
            ],
        },
        "callsites": [{"at": "0x80069AA8", "expect": "strncat", "target": "pt_z"}],
    },
    "overlays": {
        "TEL": {"hooks": [{"function": "func_80132274", "addr": "0x80132274",
                           "target": "pt_y", "note": "func_80132274 in a note"}]},
    },
}

COMPOSITIONS = {
    "note": "src/overlay/TEL/func_80132274.c is mentioned in prose",
    "compositions": [{"id": "TEL/hello", "src": "src/overlay/TEL/func_80132274.c",
                      "pieces": []}],
    "waive": {"src/overlay/TEL/tel_menu.c": "the dial menu",
              "src/overlay/TEL/gone_function.c": "no such function"},
}


def write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def make_tree(root: Path, map_symbols=None):
    write(root, "config/symbol_names.json", json.dumps(LEDGER, indent=1))
    write(root, "src/patch/main/a.c", C_SRC)
    write(root, "config/patch/english.json", json.dumps(PROFILE, indent=2) + "\n")
    write(root, "config/patch/compositions.json", json.dumps(COMPOSITIONS, indent=1))
    write(root, "config/patch/symbols.json",
          json.dumps({"symbols": map_symbols or {}, "pins": {}}, indent=2) + "\n")
    write(root, "src/overlay/TEL/tel_yoshio_intro.c", "void tel_yoshio_intro(void) {}\n")
    write(root, "src/overlay/TEL/tel_yoshio_menu.c", "void tel_yoshio_menu(void) {}\n")


def run_sync(root: Path, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SPS.main(list(args) + ["--root", str(root)])
    return rc, buf.getvalue()


class TreeCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        make_tree(self.root)

    def tearDown(self):
        self._td.cleanup()

    def read(self, rel):
        return (self.root / rel).read_text()


class TestLedger(TreeCase):
    def L(self):
        return PS.Ledger(self.root / "config/symbol_names.json",
                         self.root / "config/patch/symbols.json")

    def test_resolution_kinds(self):
        L = self.L()
        self.assertEqual(L.resolve("D_8012B1C4").status, "address-form")
        self.assertEqual(L.resolve("D_8012B1C4").addr, 0x8012B1C4)
        r = L.resolve("serifu_state")
        self.assertEqual((r.status, r.addr), ("current", 0x8012B1C4))
        self.assertEqual(L.resolve("maybe_name").status, "unknown")
        self.assertEqual(L.resolve("tel_yoshio_intro", "TEL").addr, 0x80132274)
        self.assertEqual(L.resolve("tel_yoshio_intro").status, "unknown")   # not main

    def test_renamed_message_names_old_address_new(self):
        r = self.L().resolve("old_state")
        self.assertEqual((r.status, r.addr, r.name), ("renamed", 0x8012B1C4, "serifu_state"))
        msg = r.message()
        for part in ("old_state", "0x8012B1C4", "serifu_state", "sync_patch_symbols.py --apply"):
            self.assertIn(part, msg)

    def test_reverted_landing(self):
        r = self.L().resolve("konami_command_step")
        self.assertEqual((r.status, r.name), ("reverted", "func_80043338"))
        self.assertIn("0x80043338", r.message())

    def test_paths(self):
        L = self.L()
        self.assertEqual(L.current_path("src/overlay/TEL/func_80132274.c"),
                         "src/overlay/TEL/tel_yoshio_intro.c")
        self.assertEqual(L.current_path("src/overlay/TEL/tel_menu.c"),
                         "src/overlay/TEL/tel_yoshio_menu.c")
        self.assertIsNone(L.current_path("src/overlay/TEL/gone_function.c"))

    def test_head_absorbed_window(self):
        write(self.root, "config/overlay/TEL.sym",
              "0x8013226C:256:tel_yoshio_intro\n0x80132FCC:64:tel_yoshio_menu\n")
        L = self.L()
        self.assertEqual(L.func_at(0x8013226C, "TEL"), 0x80132274)   # the head
        self.assertEqual(L.func_at(0x80132274, "TEL"), 0x80132274)
        self.assertIsNone(L.func_at(0x80140000, "TEL"))
        self.assertIsNone(L.func_at(0x8013226C, "main"))

    def test_pin_needs_a_reason(self):
        write(self.root, "config/patch/symbols.json", json.dumps(
            {"symbols": {}, "pins": {"bare": {"addr": "0x800B7000"},
                                     "why": {"addr": "0x800B7004", "reason": "x"}}}))
        L = self.L()
        self.assertEqual(L.resolve("bare").status, "unknown")
        self.assertEqual((L.resolve("why").status, L.resolve("why").addr),
                         ("pinned", 0x800B7004))


class TestSync(TreeCase):
    def test_check_and_dry_run_write_nothing(self):
        before = {p: p.read_text() for p in self.root.rglob("*") if p.is_file()}
        rc, out = run_sync(self.root, "--check")
        self.assertEqual(rc, 1, out)
        rc, out = run_sync(self.root, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(before, {p: p.read_text() for p in self.root.rglob("*") if p.is_file()})

    def test_apply_rewrites_and_is_idempotent(self):
        rc, out = run_sync(self.root, "--apply")
        self.assertEqual(rc, 0, out)
        c = self.read("src/patch/main/a.c")
        self.assertIn("extern s32 serifu_state;", c)
        self.assertIn("serifu_state = 1;", c)
        self.assertIn("/* serifu_state is the dialogue state", c)
        self.assertIn('"old_state stays in a string } {"', c)    # literals untouched
        self.assertIn("func_80043338();", c)                    # reverted landing
        self.assertIn("D_8012B1F8 = 2;", c)                     # address-form kept
        self.assertIn("void load_string(void)", c)              # the patch's own
        prof = json.loads(self.read("config/patch/english.json"))
        hooks = prof["main"]["module"]["hooks"]
        self.assertEqual(hooks[0], {"function": "kanji_load", "addr": "0x8004F690",
                                    "target": "load_string"})
        self.assertEqual(hooks[1]["function"], "msg_str_disp")
        self.assertEqual(prof["main"]["callsites"][0]["expect"], "bios_strncat")
        tel = prof["overlays"]["TEL"]["hooks"][0]
        self.assertEqual(tel["function"], "tel_yoshio_intro")
        self.assertEqual(tel["note"], "func_80132274 in a note")   # prose kept
        comp = json.loads(self.read("config/patch/compositions.json"))
        self.assertEqual(comp["compositions"][0]["src"], "src/overlay/TEL/tel_yoshio_intro.c")
        self.assertEqual(list(comp["waive"]), ["src/overlay/TEL/tel_yoshio_menu.c",
                                               "src/overlay/TEL/gone_function.c"])
        self.assertIn("func_80132274.c is mentioned in prose", comp["note"])
        m = json.loads(self.read("config/patch/symbols.json"))
        self.assertEqual(m["symbols"]["serifu_state"]["addr"], "0x8012B1C4")
        self.assertNotIn("old_state", m["symbols"])
        self.assertNotIn("load_string", m["symbols"])           # defined by the patch
        snapshot = {p: p.read_text() for p in self.root.rglob("*") if p.is_file()}
        rc, out = run_sync(self.root, "--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("0 change(s)", out)
        self.assertEqual(snapshot, {p: p.read_text() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(run_sync(self.root, "--check")[0], 0)

    def test_json_formatting_kept(self):
        run_sync(self.root, "--apply")
        text = self.read("config/patch/english.json")
        self.assertEqual(text, json.dumps(json.loads(text), indent=2) + "\n")

    def test_name_addresses_opt_in(self):
        rc, out = run_sync(self.root, "--apply", "--name-addresses")
        self.assertEqual(rc, 0, out)
        self.assertIn("msg_wait = 2;", self.read("src/patch/main/a.c"))

    def test_moved_name_refused(self):
        make_tree(self.root, {"serifu_state": {"addr": "0x8012B1C0", "kind": "data"}})
        rc, out = run_sync(self.root, "--apply")
        self.assertEqual(rc, 2, out)
        self.assertIn("moved", out)
        self.assertIn("old_state", self.read("src/patch/main/a.c"))   # nothing written

    def test_hook_without_target_refused(self):
        prof = json.loads(json.dumps(PROFILE))
        del prof["main"]["module"]["hooks"][0]["target"]
        write(self.root, "config/patch/english.json", json.dumps(prof, indent=2))
        rc, out = run_sync(self.root, "--check")
        self.assertEqual(rc, 2, out)
        self.assertIn('explicit "target"', out)

    def test_rename_onto_a_patch_definition_refused(self):
        write(self.root, "src/patch/main/b.c", "s32 serifu_state;\n")
        rc, out = run_sync(self.root, "--check")
        self.assertEqual(rc, 2, out)
        self.assertIn("the patch itself defines", out)


class TestDefinedNames(unittest.TestCase):
    def test_definitions_not_declarations(self):
        code = SPS.strip_c(
            "extern s32 a;\nextern void f(void);\nvoid g(int x);\n"
            "static u8 tbl[4] = { 1, 2 };\ns32 b, c[2];\n"
            "struct S { int q; };\n"
            "void h(void)\n{\n    char k = '}';\n    if (k) { a = 1; }\n}\n"
            "static const char *s = \"//}\";\n")
        d = SPS.defined_names(code)
        self.assertTrue({"tbl", "b", "c", "h", "s"} <= d, d)
        self.assertFalse({"a", "f", "g", "q", "k"} & d, d)


class TestBuildResolver(TreeCase):
    def pins(self):
        import build_patched
        return build_patched.SymbolPins(self.root / "config/patch/symbols.json",
                                        ledger_path=self.root / "config/symbol_names.json")

    def test_current_and_address_form_resolve(self):
        p = self.pins()
        self.assertEqual(p.resolve("serifu_state"), 0x8012B1C4)
        self.assertEqual(p.resolve("D_8012B1F8"), 0x8012B1F8)
        p.fail_if_missing("t")

    def test_former_name_fails_clearly(self):
        p = self.pins()
        self.assertIsNone(p.resolve("old_state"))
        with self.assertRaises(SystemExit) as cm:
            p.fail_if_missing("module")
        msg = str(cm.exception)
        for part in ("old_state", "0x8012B1C4", "serifu_state", "sync_patch_symbols.py"):
            self.assertIn(part, msg)

    def test_moved_name_fails(self):
        make_tree(self.root, {"serifu_state": {"addr": "0x8012B1C0", "kind": "data"}})
        p = self.pins()
        self.assertIsNone(p.resolve("serifu_state"))
        with self.assertRaises(SystemExit) as cm:
            p.fail_if_missing("module")
        self.assertIn("MOVED", str(cm.exception))


class TestComposeCoverage(TreeCase):
    def test_renamed_file_is_an_error_not_missing_plus_stale(self):
        import compose_check
        write(self.root, "src/overlay/TEL/tel_yoshio_intro.c",
              "void tel_yoshio_intro(void) { strcat(a, b); }\n")
        old_root, old_dec, old_l = compose_check.ROOT, compose_check.DECOMP, PS._LEDGER
        compose_check.ROOT = compose_check.DECOMP = self.root
        PS._LEDGER = PS.Ledger(self.root / "config/symbol_names.json",
                               self.root / "config/patch/symbols.json")
        try:
            spec = json.loads(self.read("config/patch/compositions.json"))
            missing, stale, renamed = compose_check.coverage(spec)
            self.assertEqual(missing, [])
            self.assertEqual(stale, ["src/overlay/TEL/gone_function.c"])
            self.assertEqual(sorted(r[:2] for r in renamed),
                             [("src/overlay/TEL/func_80132274.c", "src/overlay/TEL/tel_yoshio_intro.c"),
                              ("src/overlay/TEL/tel_menu.c", "src/overlay/TEL/tel_yoshio_menu.c")])
            self.assertIn("TEL:0x80132274", [r[2] for r in renamed])
            run_sync(self.root, "--apply")
            spec = json.loads(self.read("config/patch/compositions.json"))
            self.assertEqual(compose_check.coverage(spec)[2], [])
        finally:
            compose_check.ROOT, compose_check.DECOMP, PS._LEDGER = old_root, old_dec, old_l


if __name__ == "__main__":
    unittest.main()
