#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def encode_hex(data: bytes, width: int = 32) -> str:
    hex_text = data.hex()
    lines = [hex_text[offset : offset + width * 2] for offset in range(0, len(hex_text), width * 2)]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: bin_to_hex.py <input.bin> <output.hex>", file=sys.stderr)
        return 1
    input_path = Path(argv[1])
    output_path = Path(argv[2])
    data = input_path.read_bytes()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encode_hex(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
