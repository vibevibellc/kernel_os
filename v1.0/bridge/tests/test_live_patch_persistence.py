#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from live_patch_persistence import (
        ListingEntry,
        _require_patch_verification,
        _apply_source_patch,
        _parse_listing,
        parse_peek_observation,
        parse_patch_command,
        patch_succeeded,
        select_patch_verification,
    )
except ModuleNotFoundError:
    from bridge.live_patch_persistence import (
        ListingEntry,
        _require_patch_verification,
        _apply_source_patch,
        _parse_listing,
        parse_peek_observation,
        parse_patch_command,
        patch_succeeded,
        select_patch_verification,
    )


class PatchParsingTests(unittest.TestCase):
    def test_parses_patch_command(self) -> None:
        offset, patch_bytes = parse_patch_command("/patch 0007 90 90")
        self.assertEqual(offset, 0x0007)
        self.assertEqual(patch_bytes, [0x90, 0x90])

    def test_parses_peek_observation(self) -> None:
        offset, peek_bytes = parse_peek_observation("peek 0x1B3C: 61 77 61 6B 65")
        self.assertEqual(offset, 0x1B3C)
        self.assertEqual(peek_bytes, [0x61, 0x77, 0x61, 0x6B, 0x65])

    def test_detects_success_observation(self) -> None:
        self.assertTrue(patch_succeeded("patch applied. beautiful chaos achieved."))
        self.assertFalse(patch_succeeded("patch aborted by human."))


class VerificationSelectionTests(unittest.TestCase):
    def test_selects_latest_covering_peek_for_patch(self) -> None:
        latest_covering = {"origin": "/peekpage 1000 0001", "observation": "peek 0x1B00: " + "AA " * 60 + "72 65 61 64 79"}
        verification = select_patch_verification(
            "/patch 1B3C 61 77 61 6B 65",
            [
                {"origin": "/peek 1B30 04", "observation": "peek 0x1B30: 00 01 02 03"},
                {"origin": "/peek 1B3C 05", "observation": "peek 0x1B3C: 72 65 61 64 79"},
                latest_covering,
            ],
        )

        self.assertEqual(verification, latest_covering)

    def test_returns_none_when_no_peek_covers_patch(self) -> None:
        verification = select_patch_verification(
            "/patch 1B3C 61 77 61 6B 65",
            [{"origin": "/peek 1B30 04", "observation": "peek 0x1B30: 00 01 02 03"}],
        )

        self.assertIsNone(verification)

    def test_requires_verified_bytes_to_match_current_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            assembled = Path(temp_dir_name) / "stage2.bin"
            assembled.write_bytes(bytes([0x72, 0x65, 0x61, 0x64, 0x79]))

            _require_patch_verification(
                "/patch 0000 61 77 61 6B 65",
                {"origin": "/peek 0000 05", "observation": "peek 0x0000: 72 65 61 64 79"},
                assembled_stage2_path=assembled,
            )

            with self.assertRaisesRegex(ValueError, "without a verified pre-patch /peek"):
                _require_patch_verification(
                    "/patch 0000 61 77 61 6B 65",
                    None,
                    assembled_stage2_path=assembled,
                )

            with self.assertRaisesRegex(ValueError, "stale verification"):
                _require_patch_verification(
                    "/patch 0000 61 77 61 6B 65",
                    {"origin": "/peek 0000 05", "observation": "peek 0x0000: 00 00 00 00 00"},
                    assembled_stage2_path=assembled,
                )


class ListingParseTests(unittest.TestCase):
    def test_tracks_current_include_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            (root / "boot" / "stage2").mkdir(parents=True)
            top_source = root / "boot" / "stage2.asm"
            top_source.write_text('%include "boot/stage2/01_entry_io.asm"\n', encoding="utf-8")
            listing = root / "stage2.lst"
            listing.write_text(
                "\n".join(
                    [
                        '     1                                  %include "boot/stage2/01_entry_io.asm"',
                        "     1                              <1> start:",
                        "     2 00000000 31C0                <1>     xor ax, ax",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            entries = _parse_listing(listing, root, top_source.resolve())

        self.assertEqual(
            entries,
            [
                ListingEntry(
                    source_path=(root / "boot" / "stage2" / "01_entry_io.asm").resolve(),
                    line_number=2,
                    offset=0,
                    data=(0x31, 0xC0),
                )
            ],
        )

    def test_merges_multi_chunk_listing_rows_for_one_source_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            (root / "boot" / "stage2").mkdir(parents=True)
            top_source = root / "boot" / "stage2.asm"
            top_source.write_text('%include "boot/stage2/04_commands_messages.asm"\n', encoding="utf-8")
            listing = root / "stage2.lst"
            listing.write_text(
                "\n".join(
                    [
                        '     1                                  %include "boot/stage2/04_commands_messages.asm"',
                        "    25 00001B24 7374616765323A2063- <1> msg_banner db \"stage2: command monitor ready\", 13, 10, 0",
                        "    25 00001B2D 6F6D6D616E64206D6F- <1>",
                        "    25 00001B36 6E69746F7220726561- <1>",
                        "    25 00001B3F 64790D0A00          <1>",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            entries = _parse_listing(listing, root, top_source.resolve())

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].offset, 0x1B24)
        self.assertEqual(len(entries[0].data), 32)
        self.assertEqual(entries[0].data[:4], (0x73, 0x74, 0x61, 0x67))


class SourceRewriteTests(unittest.TestCase):
    def test_rewrites_instruction_and_data_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            source = root / "boot" / "stage2" / "01_entry_io.asm"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "start:",
                        "    xor ax, ax",
                        "msg_banner db 0x41, 0x42",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            entries = [
                ListingEntry(source, 2, 0x0000, (0x31, 0xC0)),
                ListingEntry(source, 3, 0x0002, (0x41, 0x42)),
            ]

            changed = _apply_source_patch(entries, 0x0000, [0x90, 0x90, 0x43, 0x44])

            self.assertEqual(changed, [source])
            self.assertEqual(
                source.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "start:",
                        "    db 0x90, 0x90",
                        "msg_banner db 0x43, 0x44",
                        "",
                    ]
                ),
            )

    def test_rejects_text_like_patch_on_instruction_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            source = root / "boot" / "stage2" / "03_programs.asm"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "push si",
                        "    call parse_hex_byte",
                        "    jc .hex_fail",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            entries = [
                ListingEntry(source, 2, 0x1B3C, (0xE8, 0xAA, 0xBB)),
                ListingEntry(source, 3, 0x1B3F, (0x72, 0x05)),
            ]

            with self.assertRaisesRegex(ValueError, "verify the runtime offset before persisting"):
                _apply_source_patch(entries, 0x1B3C, [0x61, 0x77, 0x61, 0x6B, 0x65])

    def test_allows_text_like_patch_on_data_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            source = root / "boot" / "stage2" / "04_commands_messages.asm"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        'msg_banner db "stage2: command monitor ready", 13, 10, 0',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            entries = [
                ListingEntry(
                    source,
                    1,
                    0x2083,
                    (
                        0x73,
                        0x74,
                        0x61,
                        0x67,
                        0x65,
                        0x32,
                        0x3A,
                        0x20,
                        0x63,
                        0x6F,
                        0x6D,
                        0x6D,
                        0x61,
                        0x6E,
                        0x64,
                        0x20,
                        0x6D,
                        0x6F,
                        0x6E,
                        0x69,
                        0x74,
                        0x6F,
                        0x72,
                        0x20,
                        0x72,
                        0x65,
                        0x61,
                        0x64,
                        0x79,
                        0x0D,
                        0x0A,
                        0x00,
                    ),
                )
            ]

            changed = _apply_source_patch(entries, 0x209B, [0x61, 0x77, 0x61, 0x6B, 0x65])

            self.assertEqual(changed, [source])
            self.assertIn("0x61, 0x77, 0x61, 0x6B, 0x65", source.read_text(encoding="utf-8"))

    def test_rewrites_spanning_multiple_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            source = root / "boot" / "stage2" / "01_entry_io.asm"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "start:",
                        "    xor ax, ax",
                        "loop: mov ds, ax",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            entries = [
                ListingEntry(source, 2, 0x0000, (0x31, 0xC0)),
                ListingEntry(source, 3, 0x0002, (0x8E, 0xD8)),
            ]

            _apply_source_patch(entries, 0x0001, [0xAA, 0xBB, 0xCC])

            self.assertEqual(
                source.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "start:",
                        "    db 0x31, 0xAA",
                        "loop: db 0xBB, 0xCC",
                        "",
                    ]
                ),
            )

    def test_rewrites_full_multi_chunk_data_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            source = root / "boot" / "stage2" / "04_commands_messages.asm"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        'msg_banner db "stage2: command monitor ready", 13, 10, 0',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            entries = [
                ListingEntry(
                    source,
                    1,
                    0x1B24,
                    (
                        0x73,
                        0x74,
                        0x61,
                        0x67,
                        0x65,
                        0x32,
                        0x3A,
                        0x20,
                        0x63,
                        0x6F,
                        0x6D,
                        0x6D,
                        0x61,
                        0x6E,
                        0x64,
                        0x20,
                        0x6D,
                        0x6F,
                        0x6E,
                        0x69,
                        0x74,
                        0x6F,
                        0x72,
                        0x20,
                        0x72,
                        0x65,
                        0x61,
                        0x64,
                        0x79,
                        0x0D,
                        0x0A,
                        0x00,
                    ),
                )
            ]

            _apply_source_patch(entries, 0x1B24, [0x53])

            self.assertEqual(
                source.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "msg_banner db 0x53, 0x74, 0x61, 0x67, 0x65, 0x32, 0x3A, 0x20, 0x63, 0x6F, 0x6D, 0x6D, 0x61, 0x6E, 0x64, 0x20, 0x6D, 0x6F, 0x6E, 0x69, 0x74, 0x6F, 0x72, 0x20, 0x72, 0x65, 0x61, 0x64, 0x79, 0x0D, 0x0A, 0x00",
                        "",
                    ]
                ),
            )


if __name__ == "__main__":
    unittest.main()
