#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PATCH_SUCCESS_PATTERN = re.compile(r"^patch applied\b", re.IGNORECASE)
PATCH_COMMAND_PATTERN = re.compile(
    r"^/patch\s+(?P<offset>(?:0x)?[0-9A-Fa-f]{1,4})(?P<byte_block>(?:\s+(?:0x)?[0-9A-Fa-f]{1,2}){1,512})\s*$"
)
PEEK_OBSERVATION_PATTERN = re.compile(
    r"^peek\s+0x(?P<offset>[0-9A-Fa-f]{1,8}):\s+(?P<byte_block>[0-9A-Fa-f]{2}(?:\s+[0-9A-Fa-f]{2})*)\s*$"
)
LISTING_INCLUDE_PATTERN = re.compile(r'^\s*\d+\s+%include\s+"([^"]+)"\s*$')
LISTING_CODE_PATTERN = re.compile(
    r"^\s*(?P<line>\d+)\s+(?P<offset>[0-9A-Fa-f]{8})\s+(?P<listing>\S+)\s+<\d+>\s*(?P<source>.*)$"
)
HEX_BYTE_PATTERN = re.compile(r"[0-9A-Fa-f]{2}")
DATA_DIRECTIVE_PATTERN = re.compile(
    r"^(?:(?:[^\s]+\s+)?(?:times\b.+?\s+)?)?(?:db|dw|dd|dq|dt)\b",
    re.IGNORECASE,
)


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


def parse_peek_observation(observation: str) -> tuple[int, list[int]]:
    match = PEEK_OBSERVATION_PATTERN.fullmatch(observation.strip())
    if not match:
        raise ValueError(f"invalid peek observation: {observation!r}")

    offset = int(match.group("offset"), 16)
    byte_tokens = match.group("byte_block").split()
    return offset, [int(token, 16) for token in byte_tokens]


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


def _comment_free_source(line: str) -> str:
    return line.rstrip("\n").split(";", 1)[0].strip()


def _source_line_kind(line: str) -> str:
    comment_free = _comment_free_source(line)
    if not comment_free:
        return "blank"

    label_match = re.match(r"^([^\s:]+):\s*(.*)$", comment_free)
    if label_match:
        comment_free = label_match.group(2).strip()
        if not comment_free:
            return "label"

    return "data" if DATA_DIRECTIVE_PATTERN.match(comment_free) else "code"


def _looks_like_text_patch(patch_bytes: list[int]) -> bool:
    if len(patch_bytes) < 4:
        return False

    printable = 0
    for value in patch_bytes:
        if value in (0x00, 0x09, 0x0A, 0x0D):
            printable += 1
            continue
        if 0x20 <= value <= 0x7E:
            printable += 1
            continue
        return False
    return printable > 0


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
    if _looks_like_text_patch(patch_bytes):
        suspicious_locations: list[str] = []
        for source_path, line_updates in touched_files.items():
            lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
            for line_number in sorted(line_updates):
                if _source_line_kind(lines[line_number - 1]) != "data":
                    suspicious_locations.append(f"{source_path}:{line_number}")
        if suspicious_locations:
            joined = ", ".join(suspicious_locations)
            raise ValueError(
                "refusing to persist text-like patch bytes onto non-data source lines at "
                f"{joined}; verify the runtime offset before persisting"
            )

    for source_path, line_updates in touched_files.items():
        lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
        for line_number, line_bytes in sorted(line_updates.items()):
            lines[line_number - 1] = _db_line(lines[line_number - 1], line_bytes)
        source_path.write_text("".join(lines), encoding="utf-8")
        changed_paths.append(source_path)

    return changed_paths


def _slice_verified_bytes(
    verification_observation: str,
    *,
    patch_offset: int,
    patch_size: int,
) -> list[int]:
    verification_offset, verification_bytes = parse_peek_observation(verification_observation)
    verification_end = verification_offset + len(verification_bytes)
    patch_end = patch_offset + patch_size
    if verification_offset > patch_offset or verification_end < patch_end:
        raise ValueError(
            "verified pre-patch peek does not cover the live patch range; "
            "verify the exact offset before persisting"
        )

    start = patch_offset - verification_offset
    end = start + patch_size
    return verification_bytes[start:end]


def select_patch_verification(command: str, observations: list[dict]) -> dict | None:
    patch_offset, patch_bytes = parse_patch_command(command)
    patch_end = patch_offset + len(patch_bytes)

    for candidate in reversed(observations):
        try:
            verification_offset, verification_bytes = parse_peek_observation(str(candidate.get("observation", "")))
        except ValueError:
            continue

        verification_end = verification_offset + len(verification_bytes)
        if verification_offset <= patch_offset and verification_end >= patch_end:
            return candidate
    return None


def _require_patch_verification(
    command: str,
    verification: dict | None,
    *,
    assembled_stage2_path: Path,
) -> None:
    if verification is None:
        raise ValueError(
            "refusing to persist live patch without a verified pre-patch /peek or /peekpage covering the same bytes"
        )

    patch_offset, patch_bytes = parse_patch_command(command)
    verified_bytes = _slice_verified_bytes(
        str(verification.get("observation", "")),
        patch_offset=patch_offset,
        patch_size=len(patch_bytes),
    )
    assembled = assembled_stage2_path.read_bytes()
    patch_end = patch_offset + len(patch_bytes)
    if patch_end > len(assembled):
        raise ValueError("verified patch range overruns the assembled stage2 image")

    current_bytes = list(assembled[patch_offset:patch_end])
    if current_bytes != verified_bytes:
        origin = str(verification.get("origin", "")).strip()
        source = origin or "peek observation"
        raise ValueError(
            "verified pre-patch bytes do not match the current assembled stage2 image for this range; "
            f"stale verification from {source}"
        )


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
    verification: dict | None = None,
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
        _require_patch_verification(command, verification, assembled_stage2_path=bin_path)
        entries = _parse_listing(listing_path, root, stage2_src.resolve())

    changed_paths = _apply_source_patch(entries, offset, patch_bytes)
    _patch_binary(stage2_bin, offset, patch_bytes)
    _patch_binary(disk_image, offset, patch_bytes, base_offset=512)
    return changed_paths
