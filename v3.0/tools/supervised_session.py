#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
BRIDGE_DIR = ROOT_DIR / "bridge"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

from project_env import load_project_env  # noqa: E402


load_project_env()


DEFAULT_SOCKET = ROOT_DIR / "vm" / "bridge_control.sock"
DEFAULT_REPORT_DIR = ROOT_DIR / "vm"
DEFAULT_BUDGET_USD = 0.05
MODEL_CANDIDATES = ("gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini")
MODEL_PRICING_USD_PER_1M = {
    "gpt-4.1": {
        "input": 3.00,
        "cached_input": 0.75,
        "output": 12.00,
    },
    "gpt-4.1-mini": {
        "input": 0.80,
        "cached_input": 0.20,
        "output": 3.20,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}
SAFE_COMMAND_PATTERNS = (
    re.compile(r"^(status|layout)$"),
    re.compile(r"^pace\s+\d{1,4}$"),
    re.compile(r"^step\s+\d{1,4}$"),
    re.compile(r"^train\s+\d{1,4}$"),
    re.compile(r"^peek\s+0x[0-9A-Fa-f]{1,4}\s+0x[0-9A-Fa-f]{1,2}$"),
    re.compile(r"^seed\s+[ -~]{1,36}$"),
)
SUPERVISOR_INSTRUCTIONS = """You are supervising a live kernel_os v3.0 experiment.
The kernel is unusual:
- stage2 is a live binary window that can be inspected and edited through a host transport layer
- the runtime is recursive and scans RAM plus disk
- stability is more important than novelty
- avoid irreversible or dangerous suggestions

Return a single JSON object with these keys:
- assessment: short string
- command: exactly one safe kernel command
- reason: short string
- expected_signal: short string

Allowed commands:
- status
- layout
- pace <ms> where 50 <= ms <= 500
- step <count> where 1 <= count <= 64
- train <count> where 1 <= count <= 64
- peek 0x0000 0x20
- seed <short ascii text up to 36 chars>

Never suggest patch, persist, loop, halt, chat, or disk writes.
Prefer conservative pacing and bounded work.
Return JSON only.
"""


def iso_timestamp(now: float | None = None) -> str:
    current = time.time() if now is None else now
    return datetime.fromtimestamp(current, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def usd_for_tokens(tokens: int, price_per_million: float) -> float:
    return (tokens * price_per_million) / 1_000_000.0


def extract_output_text(data: dict[str, Any]) -> str:
    outputs = data.get("output")
    if not isinstance(outputs, list):
        raise ValueError("response missing output list")
    chunks: list[str] = []
    for item in outputs:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text)
    if not chunks:
        raise ValueError("response missing output_text")
    return "\n".join(chunks).strip()


def usage_cost(model: str, usage: dict[str, Any]) -> dict[str, Any]:
    pricing = MODEL_PRICING_USD_PER_1M[model]
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    input_details = usage.get("input_tokens_details")
    cached_tokens = 0
    if isinstance(input_details, dict):
        cached_tokens = int(input_details.get("cached_tokens") or 0)
    cached_tokens = max(0, min(cached_tokens, input_tokens))
    uncached_tokens = max(0, input_tokens - cached_tokens)
    cost_usd = (
        usd_for_tokens(uncached_tokens, pricing["input"])
        + usd_for_tokens(cached_tokens, pricing["cached_input"])
        + usd_for_tokens(output_tokens, pricing["output"])
    )
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": uncached_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }


def connect_control_socket(path: str) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(path)
    return client


def control_request(socket_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    with connect_control_socket(socket_path) as client:
        client.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        reader = client.makefile("r", encoding="utf-8", errors="replace")
        raw = reader.readline()
        if not raw:
            raise RuntimeError("bridge control socket returned no response")
        response = json.loads(raw)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "bridge error"))
        return response


def control_command(socket_path: str, command: str) -> list[str]:
    response = control_request(
        socket_path,
        {
            "action": "command",
            "command": command,
            "timeout_seconds": 15.0,
        },
    )
    lines = response.get("lines")
    if not isinstance(lines, list):
        raise RuntimeError(f"invalid command response for {command!r}")
    return [str(line) for line in lines]


def control_read(socket_path: str, *, offset: int, length: int) -> str:
    response = control_request(
        socket_path,
        {
            "action": "read",
            "offset": offset,
            "length": length,
            "encoding": "hex",
        },
    )
    return str(response.get("data_hex") or "")


def sanitize_command(command: str) -> str:
    return " ".join(command.replace("\r", " ").replace("\n", " ").split())


def is_safe_command(command: str) -> bool:
    return any(pattern.fullmatch(command) for pattern in SAFE_COMMAND_PATTERNS)


def collect_snapshot(socket_path: str) -> dict[str, Any]:
    info = control_request(socket_path, {"action": "info"})
    status_lines = control_command(socket_path, "status")
    layout_lines = control_command(socket_path, "layout")
    head_hex = control_read(socket_path, offset=0, length=64)
    return {
        "captured_at": iso_timestamp(),
        "info": info,
        "status": status_lines,
        "layout": layout_lines,
        "stage2_head_hex": head_hex,
    }


def parse_supervisor_json(text: str) -> dict[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"model returned invalid JSON: {text}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("model did not return a JSON object")
    normalized: dict[str, str] = {}
    for key in ("assessment", "command", "reason", "expected_signal"):
        normalized[key] = str(data.get(key) or "").strip()
    if not normalized["command"]:
        raise RuntimeError("model returned an empty command")
    return normalized


def call_openai(
    *,
    api_key: str,
    model: str,
    instructions: str,
    prompt: str,
    max_output_tokens: int,
    prompt_cache_key: str,
    json_output: bool = True,
) -> dict[str, Any]:
    input_text = prompt if not json_output else f"Return a JSON object only.\n\n{prompt}"
    payload = {
        "model": model,
        "instructions": instructions,
        "input": input_text,
        "max_output_tokens": max_output_tokens,
        "store": False,
        "service_tier": "default",
        "prompt_cache_key": prompt_cache_key,
        "text": {
            "format": {
                "type": "json_object" if json_output else "text",
            }
        },
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def probe_model(api_key: str, model: str) -> bool:
    try:
        data = call_openai(
            api_key=api_key,
            model=model,
            instructions="Reply with plain text only.",
            prompt="ping",
            max_output_tokens=32,
            prompt_cache_key="kernel-os-v3:probe",
            json_output=False,
        )
        _ = extract_output_text(data)
        return True
    except HTTPError:
        return False


def choose_model(api_key: str, explicit_model: str | None) -> str:
    if explicit_model:
        if not probe_model(api_key, explicit_model):
            raise RuntimeError(f"model {explicit_model!r} is not accessible")
        return explicit_model
    for candidate in MODEL_CANDIDATES:
        if probe_model(api_key, candidate):
            return candidate
    raise RuntimeError("no accessible supervisor model found")


def build_round_prompt(*, phase: str, snapshot: dict[str, Any], history: list[dict[str, Any]]) -> str:
    phase_rule = {
        "curriculum": "Return a seed command. Focus on stable recursion, inspection, and bounded work.",
        "bounded_work": "Return a step or train command. Keep the count between 4 and 24.",
        "summary": "Return pace 250 or status unless the system clearly needs a different safe pacing.",
    }.get(phase, "Return one safe command.")
    return json.dumps(
        {
            "phase": phase,
            "phase_rule": phase_rule,
            "goal": "increase operational stability and usable functionality without patching code",
            "history": history,
            "snapshot": snapshot,
            "constraints": {
                "no_binary_patches": True,
                "no_disk_persistence": True,
                "supervisor_controls_only": True,
                "prefer_bounded_commands": True,
            },
        },
        indent=2,
        sort_keys=True,
    )


def run_session(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    model = choose_model(api_key, args.model)
    socket_path = args.socket
    budget_usd = args.budget_usd
    spent_usd = 0.0
    model_calls: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    baseline = collect_snapshot(socket_path)
    initial_lines = control_command(socket_path, "pace 250")
    actions.append(
        {
            "timestamp": iso_timestamp(),
            "command": "pace 250",
            "lines": initial_lines,
            "reason": "host stabilization baseline",
        }
    )

    history: list[dict[str, Any]] = [
        {
            "round": 0,
            "assessment": "host stabilized duty cycle",
            "command": "pace 250",
            "reason": "slow the loop before any training work",
            "expected_signal": "lower duty cycle and bounded runtime",
        }
    ]

    round_specs = (
        ("curriculum", 700),
        ("bounded_work", 700),
        ("summary", 500),
    )

    for index, (phase, max_output_tokens) in enumerate(round_specs, start=1):
        if spent_usd >= budget_usd:
            break
        snapshot = collect_snapshot(socket_path)
        prompt = build_round_prompt(phase=phase, snapshot=snapshot, history=history)
        data = call_openai(
            api_key=api_key,
            model=model,
            instructions=SUPERVISOR_INSTRUCTIONS,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            prompt_cache_key=f"kernel-os-v3:supervised:{phase}",
        )
        response_text = extract_output_text(data)
        usage = data.get("usage")
        if not isinstance(usage, dict):
            raise RuntimeError("response missing usage")
        usage_summary = usage_cost(model, usage)
        spent_usd += float(usage_summary["cost_usd"])
        supervisor = parse_supervisor_json(response_text)
        chosen_command = sanitize_command(supervisor["command"])
        if not is_safe_command(chosen_command):
            chosen_command = "status"
            supervisor["reason"] = f"unsafe suggestion replaced by host: {supervisor['reason']}"
            supervisor["expected_signal"] = "current state snapshot without mutation"
        lines = control_command(socket_path, chosen_command)
        record = {
            "round": index,
            "phase": phase,
            "model": model,
            "usage": usage_summary,
            "spent_usd_after_round": spent_usd,
            "assessment": supervisor["assessment"],
            "command": chosen_command,
            "reason": supervisor["reason"],
            "expected_signal": supervisor["expected_signal"],
            "kernel_lines": lines,
        }
        history.append(
            {
                "round": index,
                "assessment": supervisor["assessment"],
                "command": chosen_command,
                "reason": supervisor["reason"],
                "expected_signal": supervisor["expected_signal"],
                "kernel_lines": lines,
            }
        )
        model_calls.append(
            {
                "round": index,
                "phase": phase,
                "response_id": str(data.get("id") or ""),
                "response_text": response_text,
                "usage": usage_summary,
            }
        )
        actions.append(record)

    final_snapshot = collect_snapshot(socket_path)
    return {
        "timestamp": iso_timestamp(),
        "budget_usd": budget_usd,
        "spent_usd": spent_usd,
        "model": model,
        "baseline": baseline,
        "actions": actions,
        "model_calls": model_calls,
        "final_snapshot": final_snapshot,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--model")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    report = run_session(args)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"supervised_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "report_path": str(report_path), "model": report["model"], "spent_usd": report["spent_usd"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
