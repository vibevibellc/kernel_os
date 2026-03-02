#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PATCH_SUCCESS_PATTERN = re.compile(r"^patch applied\b", re.IGNORECASE)
PATCH_COMMAND_PATTERN = re.compile(
    r"^/patch\s+(?P<offset>(?:0x)?[0-9A-Fa-f]{1,4})(?P<byte_block>(?:\s+(?:0x)?[0-9A-Fa-f]{1,2}){1,32})\s*$"
)
LISTING_INCLUDE_PATTERN = re.compile(r'^\s*\d+\s+%include\s+"([^"]+)"\s*$')
LISTING_CODE_PATTERN = re.compile(
    r"^\s*(?P<line>\d+)\s+(?P<offset>[0-9A-Fa-f]{8})\s+(?P<listing>\S+)\s+<\d+>\s*(?P<source>.*)$"
)
HEX_BYTE_PATTERN = re.compile(r"[0-9A-Fa-f]{2}")


@dataclass(frozen=True)
class ListingEntry:
    source_path: Path
    line_number: int
    offset: int
    data: tuple[int, ...]


def parse_patch_command(command: str) -> tuple[int, list[int]]:
    match = PATCH_COMMAND_PATTERN.fullmatch(command.strip())
    if not match:
        raise ValueError(f"invalid patch command: {command!r}")

    offset = int(match.group("offset"), 16)
    byte_tokens = match.group("byte_block").split()
    return offset, [int(token, 16) for token in byte_tokens]


def patch_succeeded(observation: str) -> bool:
    return bool(PATCH_SUCCESS_PATTERN.match(observation.strip()))


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_listing(listing_path: Path, repo_root: Path, top_source: Path) -> list[ListingEntry]:
    current_source = top_source
    entries: list[ListingEntry] = []

    for raw_line in listing_path.read_text(encoding="utf-8").splitlines():
        include_match = LISTING_INCLUDE_PATTERN.match(raw_line)
        if include_match:
            current_source = (repo_root / include_match.group(1)).resolve()
            continue

        code_match = LISTING_CODE_PATTERN.match(raw_line)
        if not code_match:
            continue

        data = tuple(int(token, 16) for token in HEX_BYTE_PATTERN.findall(code_match.group("listing")))
        if not data:
            continue

        source_path = current_source
        line_number = int(code_match.group("line"))
        offset = int(code_match.group("offset"), 16)
        entry = ListingEntry(
            source_path=source_path,
            line_number=line_number,
            offset=offset,
            data=data,
        )
        if entries:
            previous = entries[-1]
            if (
                previous.source_path == entry.source_path
                and previous.line_number == entry.line_number
                and previous.offset + len(previous.data) == entry.offset
            ):
                entries[-1] = ListingEntry(
                    source_path=previous.source_path,
                    line_number=previous.line_number,
                    offset=previous.offset,
                    data=previous.data + entry.data,
                )
                continue

        entries.append(entry)

    return entries


def _source_prefix(line: str) -> str:
    content = line.rstrip("\n")
    comment_free = content.split(";", 1)[0].rstrip()
    if not comment_free:
        return re.match(r"\s*", content).group(0)

    leading_ws = re.match(r"\s*", content).group(0)
    if leading_ws:
        return leading_ws

    colon_match = re.match(r"^([^\s:]+:\s*)(.*)$", comment_free)
    if colon_match:
        return colon_match.group(1)

    token_match = re.match(r"^([^\s;]+)(\s+)(.*)$", comment_free)
    if token_match:
        return token_match.group(1) + token_match.group(2)

    return ""


def _db_line(original_line: str, patched_bytes: list[int]) -> str:
    prefix = _source_prefix(original_line)
    byte_text = ", ".join(f"0x{value:02X}" for value in patched_bytes)
    return f"{prefix}db {byte_text}\n"


def _apply_source_patch(
    entries: list[ListingEntry],
    offset: int,
    patch_bytes: list[int],
) -> list[Path]:
    end = offset + len(patch_bytes)
    covered = [False] * len(patch_bytes)
    replacements: dict[tuple[Path, int], list[int]] = {}

    for entry in entries:
        entry_end = entry.offset + len(entry.data)
        if entry.offset >= end or entry_end <= offset:
            continue

        line_bytes = replacements.setdefault((entry.source_path, entry.line_number), list(entry.data))
        overlap_start = max(offset, entry.offset)
        overlap_end = min(end, entry_end)
        for absolute_offset in range(overlap_start, overlap_end):
            patch_index = absolute_offset - offset
            line_index = absolute_offset - entry.offset
            line_bytes[line_index] = patch_bytes[patch_index]
            covered[patch_index] = True

    if not all(covered):
        missing = [index for index, is_covered in enumerate(covered) if not is_covered]
        raise ValueError(f"unable to map patch bytes at relative indexes: {missing}")

    touched_files: dict[Path, dict[int, list[int]]] = {}
    for (source_path, line_number), line_bytes in replacements.items():
        touched_files.setdefault(source_path, {})[line_number] = line_bytes

    changed_paths: list[Path] = []
    for source_path, line_updates in touched_files.items():
        lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
        for line_number, line_bytes in sorted(line_updates.items()):
            lines[line_number - 1] = _db_line(lines[line_number - 1], line_bytes)
        source_path.write_text("".join(lines), encoding="utf-8")
        changed_paths.append(source_path)

    return changed_paths


def _patch_binary(path: Path, offset: int, patch_bytes: list[int], *, base_offset: int = 0) -> None:
    if not path.exists():
        return

    blob = bytearray(path.read_bytes())
    start = base_offset + offset
    end = start + len(patch_bytes)
    if end > len(blob):
        raise ValueError(f"patch overruns {path}")
    blob[start:end] = bytes(patch_bytes)
    path.write_bytes(blob)


def persist_stage2_patch(
    command: str,
    observation: str,
    *,
    repo_root: Path | None = None,
) -> list[Path]:
    if not patch_succeeded(observation):
        return []

    root = repo_root or _repo_root()
    stage2_src = root / "boot" / "stage2.asm"
    stage2_bin = root / "build" / "stage2.bin"
    disk_image = root / "vm" / "os-disk.img"

    offset, patch_bytes = parse_patch_command(command)

    with tempfile.TemporaryDirectory(prefix="stage2-live-patch-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        listing_path = temp_dir / "stage2.lst"
        bin_path = temp_dir / "stage2.bin"
        subprocess.run(
            ["nasm", "-I", ".", "-f", "bin", "-l", str(listing_path), "-o", str(bin_path), str(stage2_src)],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        entries = _parse_listing(listing_path, root, stage2_src.resolve())

    changed_paths = _apply_source_patch(entries, offset, patch_bytes)
    _patch_binary(stage2_bin, offset, patch_bytes)
    _patch_binary(disk_image, offset, patch_bytes, base_offset=512)
    return changed_paths
