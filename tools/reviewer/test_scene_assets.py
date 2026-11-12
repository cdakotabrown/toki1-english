"""Synthetic extraction and dialogue-graph controls; no game data in fixtures."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from scene_assets import (BASE, PACK_SIZE, PAGE_OFFSETS, bs_dimensions,
                          decode_bustup, dialogue_references, extract_art,
                          palette_rgba, pointer_assignments, source_code)


def pack_fixture():
    data = bytearray(PACK_SIZE)
    struct.pack_into("<4h", data, 0, 6, 64, 80, 0)
    cells = [(0, 0, 0, 0x1000, 0, 128, 128),
             (0, 128, 64, 0x1000, 0, 128, 32),
             (112, 0, 80, 0x1000, 0, 16, 16),
             (112, 16, 88, 0x1000, 0, 16, 16),
             (24, 54, 128, 0x1000, 0, 48, 32),
             (40, 78, 131, 0x1000, 0, 16, 16)]
    for i, cell in enumerate(cells):
        struct.pack_into("<7h", data, 8 + i * 14, *cell)
    struct.pack_into("<8I", data, 0x84, *(BASE + offset for offset in PAGE_OFFSETS), BASE, BASE + 0x5C, BASE + 0x70)
    for i, color in enumerate([0, 0x1F, 0x3E0, 0x7C00, 0x3FF, 0x7C1F]):
        struct.pack_into("<H", data, 0xAC + i * 2, color)
    for i, offset in enumerate(PAGE_OFFSETS):
        data[offset:offset + 0x4000] = bytes([i + 1]) * 0x4000
    return data


def dialogue_fixture():
    base = 0x80198000
    data = bytearray(0x60)
    struct.pack_into("<3I", data, 0x20, base, base + 4, base + 8)
    struct.pack_into("<2I", data, 0x40, base + 0x20, base + 0x28)
    data[0x48:0x50] = bytes([1, 3, 255, 0, 2, 255, 0, 0])
    struct.pack_into("<2I", data, 0x50, base + 0x48, base + 0x4C)
    return data, base


class BustupTests(unittest.TestCase):
    def test_five_pages_and_six_expressions_use_bound_palette_and_records(self):
        pages, image, expressions, cells = decode_bustup(pack_fixture())
        self.assertEqual(len(pages), 5)
        self.assertEqual(len(expressions), 6)
        self.assertEqual(image.size, (128, 160))
        self.assertEqual(pages[0].getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(expressions[0].getpixel((24, 54)), (0, 0, 255, 255))
        self.assertEqual(expressions[2].getpixel((24, 54)), (255, 255, 0, 255))
        self.assertEqual(expressions[4].getpixel((24, 54)), (255, 0, 255, 255))
        self.assertEqual(expressions[0].getpixel((0, 0)), (255, 0, 0, 255))

    def test_truncation_wrong_pointers_and_cropped_regions_are_rejected(self):
        with self.assertRaises(ValueError):
            decode_bustup(pack_fixture()[:-1])
        data = pack_fixture()
        struct.pack_into("<I", data, 0x84, BASE + 0x20B0)
        with self.assertRaisesRegex(ValueError, "pointer"):
            decode_bustup(data)
        data = pack_fixture()
        struct.pack_into("<h", data, 8 + 10, 129)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            decode_bustup(data)

    def test_negative_cell_origins_expand_canvas_instead_of_clipping_hair(self):
        data = pack_fixture()
        struct.pack_into("<h", data, 8, -16)
        pages, image, expressions, cells = decode_bustup(data)
        self.assertEqual(image.size, (144, 160))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(expressions[0].getpixel((40, 54)), (0, 0, 255, 255))

    def test_palette_applies_engine_stp_mode_without_guessing_transparency(self):
        words = [0x8000] * 256
        words[241] = 0x1F
        palette = palette_rgba(words)
        self.assertEqual(palette[0], (0, 0, 0, 0))
        self.assertEqual(palette[240], (0, 0, 0, 255))
        self.assertEqual(palette[241], (255, 0, 0, 255))

    def test_hashed_cache_is_idempotent_and_repairs_corrupted_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assets/extracted_iso/CDROM/BUSTUP/XX10.BIN"
            source.parent.mkdir(parents=True)
            source.write_bytes(pack_fixture())
            out = root / "extracted_assets/reviewer"
            report = extract_art(root, out)
            target = out / "characters/XX10/expression-0.png"
            original = target.read_bytes()
            with patch("scene_assets.decode_bustup", side_effect=AssertionError("cache missed")):
                again = extract_art(root, out)
            self.assertEqual(again, report)
            target.write_bytes(b"corrupt")
            repaired = extract_art(root, out)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(repaired["failures"])

    def test_invalid_asset_stays_a_failure_not_an_empty_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assets/extracted_iso/CDROM/BUSTUP/XX10.BIN"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"not an image")
            report = extract_art(root, root / "extracted_assets/reviewer")
            self.assertEqual(report["assets"], [])
            self.assertEqual(len(report["failures"]), 1)

    def test_bs_dimensions_follow_known_mdec_callsite_families(self):
        self.assertEqual(bs_dimensions(Path("BS/C_01_01.BS")), (320, 88))
        self.assertEqual(bs_dimensions(Path("BS/D_01_01.BS")), (320, 160))
        self.assertEqual(bs_dimensions(Path("NAME_ENT/N_01.BS")), (320, 240))


class DialogueTests(unittest.TestCase):
    def test_background_and_character_options_are_independent(self):
        from scene_panel import layer_options
        class Context:
            data = {"characters": {"2": {"options": [dict(label="Seasonal reference", image="portrait.png")]}}}
        bg, sprites = layer_options(Context(), dict(character_id="2", background_options=[dict(label="Place", image="bg.png")]))
        self.assertEqual(bg[0]["image"], "bg.png")
        self.assertEqual(sprites[0]["image"], "portrait.png")
        unknown_bg, sprites = layer_options(Context(), dict(character_id="2"))
        self.assertEqual(unknown_bg, [])
        self.assertEqual(sprites[0]["image"], "portrait.png")

    def test_screenshot_does_not_manufacture_background_or_sprite_layers(self):
        from scene_panel import layer_options
        class Context:
            data = {}
        self.assertEqual(layer_options(Context(), dict(screenshot="capture.png")), ([], []))

    def test_follows_parallel_tables_to_exact_string_offsets_and_sites(self):
        data, base = dialogue_fixture()
        result = dialogue_references(data, base, base + 0x40, base + 0x50, {0, 4, 8})
        self.assertEqual(set(result), {0, 4, 8})
        self.assertEqual(result[4], [dict(group=0, index=1, pointer_site="0x24", command=3)])
        self.assertEqual(result[8][0]["group"], 1)

    def test_does_not_bind_unrecognized_targets_or_neighboring_strings(self):
        data, base = dialogue_fixture()
        result = dialogue_references(data, base, base + 0x40, base + 0x50, {0, 12})
        self.assertEqual(set(result), {0})

    def test_out_of_range_pointer_and_unterminated_kinds_fail_closed(self):
        data, base = dialogue_fixture()
        struct.pack_into("<I", data, 0x50, base - 4)
        with self.assertRaises(ValueError):
            dialogue_references(data, base, base + 0x40, base + 0x50, {0})
        data, base = dialogue_fixture()
        data[0x48:0x50] = b"\x01" * 8
        with self.assertRaisesRegex(ValueError, "terminator|exceeds"):
            dialogue_references(data, base, base + 0x40, base + 0x50, {0})

    def test_source_parser_does_not_read_history_prose_as_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.c"
            path.write_text("/* D_80150000 = (s32)0xDEADBEEF; */\nD_80150000 = (s32)0x80198000;", encoding="utf-8")
            self.assertEqual(pointer_assignments(source_code(path)), {"D_80150000": 0x80198000})


if __name__ == "__main__":
    unittest.main()
