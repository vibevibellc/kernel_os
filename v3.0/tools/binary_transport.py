#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
from pathlib import Path


DEFAULT_SOCKET = Path(__file__).resolve().parents[1] / "vm" / "bridge_control.sock"


def parse_int_value(value: str) -> int:
    return int(value, 0)


def connect_control_socket(path: str) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(path)
    except FileNotFoundError as exc:
        raise RuntimeError(f"control socket not found: {path}") from exc
    except ConnectionRefusedError as exc:
        raise RuntimeError(f"control socket refused connection: {path}") from exc
    return client


def request_lines(socket_path: str, payload: dict[str, object]) -> list[dict[str, object]]:
    with connect_control_socket(socket_path) as client:
        client.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        reader = client.makefile("r", encoding="utf-8", errors="replace")
        responses: list[dict[str, object]] = []
        for raw_line in reader:
            line = raw_line.strip()
            if not line:
                continue
            responses.append(json.loads(line))
        return responses


def request_single(socket_path: str, payload: dict[str, object]) -> dict[str, object]:
    responses = request_lines(socket_path, payload)
    if not responses:
        raise RuntimeError("bridge returned no response")
    if len(responses) != 1:
        raise RuntimeError(f"expected one response line, got {len(responses)}")
    return responses[0]


def decode_payload(response: dict[str, object]) -> bytes:
    if "data_hex" in response:
        return bytes.fromhex(str(response["data_hex"]))
    if "data_b64" in response:
        return base64.b64decode(str(response["data_b64"]), validate=True)
    return b""


def fail_if_error(response: dict[str, object]) -> None:
    if response.get("ok"):
        return
    message = str(response.get("error") or "bridge error")
    raise RuntimeError(message)


def print_json(response: dict[str, object]) -> None:
    print(json.dumps(response, indent=2, sort_keys=True))


def load_write_bytes(args: argparse.Namespace) -> bytes:
    if getattr(args, "input", None) and getattr(args, "hex", None):
        raise RuntimeError("use either --input or --hex")
    if getattr(args, "input", None):
        return Path(args.input).read_bytes()
    hex_text = (getattr(args, "hex", None) or "").replace(" ", "")
    if not hex_text:
        raise RuntimeError("missing --input or --hex")
    return bytes.fromhex(hex_text)


def command_info(args: argparse.Namespace) -> int:
    response = request_single(args.socket, {"action": "info"})
    fail_if_error(response)
    print_json(response)
    return 0


def command_exec(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "command",
            "command": " ".join(args.command).strip(),
            "timeout_seconds": args.timeout_seconds,
        },
    )
    fail_if_error(response)
    lines = response.get("lines")
    if isinstance(lines, list):
        for line in lines:
            print(str(line))
    return 0


def command_read(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "read",
            "offset": args.offset,
            "length": args.length,
            "encoding": args.encoding,
        },
    )
    fail_if_error(response)
    data = decode_payload(response)
    if args.output:
        Path(args.output).write_bytes(data)
        print(f"wrote {len(data)} bytes to {args.output}")
        return 0
    if args.encoding == "hex":
        print(f"0x{args.offset:04X}: {data.hex().upper()}")
    else:
        print(str(response.get("data_b64") or ""))
    return 0


def command_write(args: argparse.Namespace) -> int:
    data = load_write_bytes(args)

    payload: dict[str, object] = {
        "action": "write",
        "offset": args.offset,
        "persist": args.persist,
        "verify": args.verify,
        "data_hex": data.hex().upper(),
    }
    response = request_single(args.socket, payload)
    fail_if_error(response)
    print(
        f"wrote {response.get('bytes_written', 0)} bytes at 0x{args.offset:04X} "
        f"sha256={response.get('sha256', '')}"
    )
    if response.get("persisted"):
        print("persisted")
    if response.get("verified"):
        print("verified")
    return 0


def command_persist(args: argparse.Namespace) -> int:
    response = request_single(args.socket, {"action": "persist"})
    fail_if_error(response)
    lines = response.get("lines")
    if isinstance(lines, list):
        for line in lines:
            print(str(line))
    return 0


def command_stream(args: argparse.Namespace) -> int:
    responses = request_lines(
        args.socket,
        {
            "action": "stream",
            "offset": args.offset,
            "length": args.length,
            "encoding": args.encoding,
            "interval_ms": args.interval_ms,
            "iterations": args.count,
        },
    )
    for response in responses:
        fail_if_error(response)
        frame_type = str(response.get("type") or "")
        if frame_type == "stream_start":
            print(
                f"stream start offset=0x{int(response.get('offset', 0)):04X} "
                f"length={response.get('length', 0)} interval_ms={response.get('interval_ms', 0)}"
            )
            continue
        if frame_type == "stream_chunk":
            sequence = int(response.get("sequence", 0))
            sha256 = str(response.get("sha256") or "")
            if args.encoding == "hex":
                payload = str(response.get("data_hex") or "")
            else:
                payload = str(response.get("data_b64") or "")
            print(f"{sequence}: {sha256} {payload}")
            continue
        if frame_type == "stream_end":
            print(f"stream end count={response.get('count', 0)}")
    return 0


def command_shadow_info(args: argparse.Namespace) -> int:
    response = request_single(args.socket, {"action": "shadow_info"})
    fail_if_error(response)
    print_json(response)
    return 0


def command_shadow_init(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "shadow_init",
            "source": args.source,
        },
    )
    fail_if_error(response)
    print_json(response)
    return 0


def command_shadow_read(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "shadow_read",
            "offset": args.offset,
            "length": args.length,
            "encoding": args.encoding,
        },
    )
    fail_if_error(response)
    data = decode_payload(response)
    if args.output:
        Path(args.output).write_bytes(data)
        print(f"wrote {len(data)} bytes to {args.output}")
        return 0
    if args.encoding == "hex":
        print(f"0x{args.offset:04X}: {data.hex().upper()}")
    else:
        print(str(response.get("data_b64") or ""))
    return 0


def command_shadow_write(args: argparse.Namespace) -> int:
    data = load_write_bytes(args)
    response = request_single(
        args.socket,
        {
            "action": "shadow_write",
            "offset": args.offset,
            "data_hex": data.hex().upper(),
        },
    )
    fail_if_error(response)
    print(
        f"shadow wrote {response.get('bytes_written', 0)} bytes at 0x{args.offset:04X} "
        f"sha256={response.get('sha256', '')}"
    )
    return 0


def command_shadow_diff(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "shadow_diff",
            "base": args.base,
            "limit_spans": args.limit_spans,
        },
    )
    fail_if_error(response)
    print_json(response)
    return 0


def command_shadow_promote(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "shadow_promote",
            "persist": args.persist,
            "verify": args.verify,
        },
    )
    fail_if_error(response)
    print_json(response)
    return 0


def command_rollback_live(args: argparse.Namespace) -> int:
    response = request_single(
        args.socket,
        {
            "action": "rollback_live",
            "persist": args.persist,
            "verify": args.verify,
        },
    )
    fail_if_error(response)
    print_json(response)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    info = subparsers.add_parser("info")
    info.set_defaults(func=command_info)

    exec_parser = subparsers.add_parser("command")
    exec_parser.add_argument("command", nargs="+")
    exec_parser.add_argument("--timeout-seconds", type=float, default=10.0)
    exec_parser.set_defaults(func=command_exec)

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("--offset", required=True, type=parse_int_value)
    read_parser.add_argument("--length", required=True, type=parse_int_value)
    read_parser.add_argument("--encoding", choices=("hex", "base64"), default="hex")
    read_parser.add_argument("--output")
    read_parser.set_defaults(func=command_read)

    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--offset", required=True, type=parse_int_value)
    write_parser.add_argument("--input")
    write_parser.add_argument("--hex")
    write_parser.add_argument("--persist", action="store_true")
    write_parser.add_argument("--verify", action="store_true")
    write_parser.set_defaults(func=command_write)

    persist_parser = subparsers.add_parser("persist")
    persist_parser.set_defaults(func=command_persist)

    stream_parser = subparsers.add_parser("stream")
    stream_parser.add_argument("--offset", required=True, type=parse_int_value)
    stream_parser.add_argument("--length", required=True, type=parse_int_value)
    stream_parser.add_argument("--encoding", choices=("hex", "base64"), default="hex")
    stream_parser.add_argument("--interval-ms", type=int, default=1000)
    stream_parser.add_argument("--count", type=int, default=0)
    stream_parser.set_defaults(func=command_stream)

    shadow_info = subparsers.add_parser("shadow-info")
    shadow_info.set_defaults(func=command_shadow_info)

    shadow_init = subparsers.add_parser("shadow-init")
    shadow_init.add_argument("--source", choices=("canonical", "live"), default="canonical")
    shadow_init.set_defaults(func=command_shadow_init)

    shadow_read = subparsers.add_parser("shadow-read")
    shadow_read.add_argument("--offset", required=True, type=parse_int_value)
    shadow_read.add_argument("--length", required=True, type=parse_int_value)
    shadow_read.add_argument("--encoding", choices=("hex", "base64"), default="hex")
    shadow_read.add_argument("--output")
    shadow_read.set_defaults(func=command_shadow_read)

    shadow_write = subparsers.add_parser("shadow-write")
    shadow_write.add_argument("--offset", required=True, type=parse_int_value)
    shadow_write.add_argument("--input")
    shadow_write.add_argument("--hex")
    shadow_write.set_defaults(func=command_shadow_write)

    shadow_diff = subparsers.add_parser("shadow-diff")
    shadow_diff.add_argument("--base", choices=("canonical", "live"), default="canonical")
    shadow_diff.add_argument("--limit-spans", type=int, default=64)
    shadow_diff.set_defaults(func=command_shadow_diff)

    shadow_promote = subparsers.add_parser("shadow-promote")
    shadow_promote.add_argument("--persist", action="store_true")
    shadow_promote.add_argument("--verify", action="store_true", default=True)
    shadow_promote.add_argument("--no-verify", action="store_false", dest="verify")
    shadow_promote.set_defaults(func=command_shadow_promote)

    rollback_live = subparsers.add_parser("rollback-live")
    rollback_live.add_argument("--persist", action="store_true")
    rollback_live.add_argument("--verify", action="store_true", default=True)
    rollback_live.add_argument("--no-verify", action="store_false", dest="verify")
    rollback_live.set_defaults(func=command_rollback_live)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
