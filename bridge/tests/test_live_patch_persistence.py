#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from live_patch_persistence import (
    ListingEntry,
    _apply_source_patch,
    _parse_listing,
    parse_patch_command,
    patch_succeeded,
)


class PatchParsingTests(unittest.TestCase):
    def test_parses_patch_command(self) -> None:
        offset, patch_bytes = parse_patch_command("/patch 0007 90 90")
        self.assertEqual(offset, 0x0007)
        self.assertEqual(patch_bytes, [0x90, 0x90])

    def test_detects_success_observation(self) -> None:
        self.assertTrue(patch_succeeded("patch applied. beautiful chaos achieved."))
        self.assertFalse(patch_succeeded("patch aborted by human."))


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


if __name__ == "__main__":
    unittest.main()
