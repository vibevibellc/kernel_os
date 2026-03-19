#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def load_hex(path: Path) -> bytes:
    chunks: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0]
        filtered = "".join(ch for ch in line if ch not in " \t\r\n")
        if filtered:
            chunks.append(filtered)
    payload = "".join(chunks)
    if len(payload) % 2 != 0:
        raise ValueError(f"{path} contains an odd number of hex digits")
    try:
        return bytes.fromhex(payload)
    except ValueError as exc:
        raise ValueError(f"{path} contains invalid hexadecimal text") from exc


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: hex_to_bin.py <input.hex> <output.bin>", file=sys.stderr)
        return 1
    input_path = Path(argv[1])
    output_path = Path(argv[2])
    data = load_hex(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
