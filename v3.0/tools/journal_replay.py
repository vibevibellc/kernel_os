#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_JOURNAL = ROOT_DIR / "vm" / "kernel_journal.jsonl"
DEFAULT_STAGE2 = ROOT_DIR / "binary" / "stage2.bin"
DEFAULT_WINDOW_BYTES = 32768


def read_window(path: Path, *, window_bytes: int) -> bytes:
    data = path.read_bytes()
    if len(data) > window_bytes:
        data = data[:window_bytes]
    if len(data) < window_bytes:
        data = data.ljust(window_bytes, b"\x00")
    return data


def load_events(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events: list[dict[str, object]] = []
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        if isinstance(event, dict):
            events.append(event)
    return events


def apply_spans(target: bytearray, spans: list[dict[str, object]]) -> None:
    for span in spans:
        offset = int(span["offset"])
        data = bytes.fromhex(str(span["data_hex"]))
        target[offset : offset + len(data)] = data


def compact_hex_string(value: str, *, keep_chars: int = 32) -> str:
    if len(value) <= keep_chars * 2:
        return value
    digest = hashlib.sha256(bytes.fromhex(value)).hexdigest()
    prefix = value[:keep_chars]
    suffix = value[-keep_chars:]
    return f"{prefix}...{suffix} (hex_len={len(value)} sha256={digest})"


def compact_event(event: dict[str, object]) -> dict[str, object]:
    compacted: dict[str, object] = {}
    for key, value in event.items():
        if isinstance(value, str) and key.endswith("_hex"):
            compacted[key] = compact_hex_string(value)
            continue
        compacted[key] = value
    return compacted


def rebuild_state(
    *,
    canonical: bytes,
    events: list[dict[str, object]],
) -> dict[str, object]:
    live = bytearray(canonical)
    shadow: bytearray | None = None
    rollback: bytearray | None = None
    last_commands: list[str] = []
    mutations: list[dict[str, object]] = []

    for event in events:
        event_type = str(event.get("event") or "")
        if event_type == "command_executed":
            command = str(event.get("command") or "")
            if command:
                last_commands.append(command)
                if len(last_commands) > 12:
                    last_commands = last_commands[-12:]
            continue

        if event_type == "shadow_initialized":
            window_hex = str(event.get("window_hex") or "")
            if window_hex:
                shadow = bytearray(bytes.fromhex(window_hex))
                mutations.append(
                    {
                        "event": event_type,
                        "sequence": event.get("sequence"),
                        "shadow_sha256": event.get("shadow_sha256"),
                    }
                )
            continue

        if event_type == "shadow_write":
            if shadow is None:
                shadow = bytearray(canonical)
            offset = int(event.get("offset") or 0)
            data_hex = str(event.get("data_hex") or "")
            data = bytes.fromhex(data_hex)
            shadow[offset : offset + len(data)] = data
            mutations.append(
                {
                    "event": event_type,
                    "sequence": event.get("sequence"),
                    "offset": offset,
                    "length": len(data),
                }
            )
            continue

        if event_type == "live_write":
            offset = int(event.get("offset") or 0)
            data_hex = str(event.get("data_hex") or "")
            data = bytes.fromhex(data_hex)
            live[offset : offset + len(data)] = data
            mutations.append(
                {
                    "event": event_type,
                    "sequence": event.get("sequence"),
                    "offset": offset,
                    "length": len(data),
                }
            )
            continue

        if event_type == "shadow_promote_started":
            rollback_hex = str(event.get("rollback_window_hex") or "")
            if rollback_hex:
                rollback = bytearray(bytes.fromhex(rollback_hex))
            continue

        if event_type == "shadow_promote_committed":
            spans = event.get("spans")
            if isinstance(spans, list):
                apply_spans(live, [span for span in spans if isinstance(span, dict)])
                mutations.append(
                    {
                        "event": event_type,
                        "sequence": event.get("sequence"),
                        "changed_spans": event.get("changed_spans"),
                        "changed_bytes": event.get("changed_bytes"),
                    }
                )
            continue

        if event_type == "live_rollback_committed":
            window_hex = str(event.get("window_hex") or "")
            if window_hex:
                live = bytearray(bytes.fromhex(window_hex))
            elif rollback is not None:
                live = bytearray(rollback)
            mutations.append(
                {
                    "event": event_type,
                    "sequence": event.get("sequence"),
                    "changed_spans": event.get("changed_spans"),
                    "changed_bytes": event.get("changed_bytes"),
                }
            )
            continue

    return {
        "live_bytes": bytes(live),
        "shadow_bytes": None if shadow is None else bytes(shadow),
        "rollback_bytes": None if rollback is None else bytes(rollback),
        "last_commands": last_commands,
        "mutations": mutations,
    }


def summarize(
    events: list[dict[str, object]],
    rebuilt: dict[str, object],
    *,
    journal_path: Path,
) -> dict[str, object]:
    counts = Counter(str(event.get("event") or "unknown") for event in events)
    live_bytes = bytes(rebuilt["live_bytes"])
    shadow_bytes = rebuilt["shadow_bytes"]
    rollback_bytes = rebuilt["rollback_bytes"]
    return {
        "journal_path": str(journal_path),
        "event_count": len(events),
        "event_counts": dict(sorted(counts.items())),
        "last_sequence": events[-1].get("sequence") if events else 0,
        "last_timestamp": events[-1].get("timestamp") if events else "",
        "last_commands": rebuilt["last_commands"],
        "mutation_count": len(rebuilt["mutations"]),
        "final_live_sha256": hashlib.sha256(live_bytes).hexdigest(),
        "final_shadow_sha256": "" if shadow_bytes is None else hashlib.sha256(bytes(shadow_bytes)).hexdigest(),
        "rollback_sha256": "" if rollback_bytes is None else hashlib.sha256(bytes(rollback_bytes)).hexdigest(),
        "recent_mutations": rebuilt["mutations"][-10:],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    parser.add_argument("--stage2", default=str(DEFAULT_STAGE2))
    parser.add_argument("--window-bytes", type=int, default=DEFAULT_WINDOW_BYTES)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeline", type=int, default=0)
    parser.add_argument("--write-live")
    parser.add_argument("--write-shadow")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    journal_path = Path(args.journal)
    events = load_events(journal_path)
    canonical = read_window(Path(args.stage2), window_bytes=args.window_bytes)
    rebuilt = rebuild_state(canonical=canonical, events=events)
    summary = summarize(events, rebuilt, journal_path=journal_path)

    if args.write_live:
        Path(args.write_live).write_bytes(bytes(rebuilt["live_bytes"]))
    if args.write_shadow and rebuilt["shadow_bytes"] is not None:
        Path(args.write_shadow).write_bytes(bytes(rebuilt["shadow_bytes"]))

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.timeline > 0:
            timeline = [compact_event(event) for event in events[-args.timeline :]]
            print(json.dumps({"timeline": timeline}, indent=2, sort_keys=True))
        return 0

    print(f"journal: {summary['journal_path']}")
    print(f"events: {summary['event_count']} last_sequence={summary['last_sequence']}")
    print(f"live_sha256: {summary['final_live_sha256']}")
    if summary["final_shadow_sha256"]:
        print(f"shadow_sha256: {summary['final_shadow_sha256']}")
    if summary["rollback_sha256"]:
        print(f"rollback_sha256: {summary['rollback_sha256']}")
    if summary["last_commands"]:
        print("last commands:")
        for command in summary["last_commands"]:
            print(f"- {command}")
    if args.timeline > 0:
        print("timeline:")
        for event in events[-args.timeline :]:
            print(json.dumps(compact_event(event), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
