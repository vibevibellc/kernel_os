#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from project_env import load_project_env


load_project_env()


REQUEST_PREFIX = "POST /chat "
PROMPT_TOKEN = "kernel_os> "
DEFAULT_STATE_PATH = Path("vm") / "bridge_state.json"
DEFAULT_LEDGER_PATH = Path("vm") / "bridge_ledger.jsonl"
DEFAULT_CONTROL_SOCKET_PATH = Path("vm") / "bridge_control.sock"
DEFAULT_JOURNAL_PATH = Path("vm") / "kernel_journal.jsonl"
DEFAULT_SHADOW_PATH = Path("vm") / "stage2_shadow.bin"
DEFAULT_SHADOW_META_PATH = Path("vm") / "stage2_shadow_meta.json"
DEFAULT_ROLLBACK_PATH = Path("vm") / "stage2_rollback.bin"
DEFAULT_PROMPT_CACHE_KEY = "kernel-os-v3"
DEFAULT_TRANSPORT_WINDOW_BYTES = 32768
PEEK_MAX_BYTES = 32
PATCH_MAX_BYTES = 32
PEEK_LINE_RE = re.compile(r"^peek\s+(0x[0-9a-fA-F]+):\s*(.*)$")
DEFAULT_SYSTEM_PROMPT = """You are the host-side reasoning bridge for kernel_os v3.0.
Reply with exactly one line.
Use `AI: ...` for normal text.
Use `CMD: ...` only for one safe kernel command from this set:
- help
- layout
- status
- step <decimal>
- loop <decimal>
- pace <decimal>
- seed <text>
- peek <hex_offset> <hex_count>
- patch <hex_offset> <hex_bytes...>
- persist
Never emit `halt`.
Prefer inspection before mutation.
Keep replies short and operational.
"""

SAFE_COMMAND_PATTERNS = (
    re.compile(r"^(help|layout|status|persist)$"),
    re.compile(r"^(step|loop|pace)\s+\d{1,5}$"),
    re.compile(r"^seed\s+.{1,48}$"),
    re.compile(r"^peek\s+(?:0x)?[0-9a-fA-F]{1,4}\s+(?:0x)?[0-9a-fA-F]{1,2}$"),
    re.compile(r"^patch\s+(?:0x)?[0-9a-fA-F]{1,4}(?:\s+(?:0x)?[0-9a-fA-F]{1,2}){1,32}$"),
)

MODEL_PRICING_USD_PER_1M = {
    "gpt-5.4": {
        "input": 2.50,
        "cached_input": 0.25,
        "output": 15.00,
    },
    "gpt-5-mini": {
        "input": 0.25,
        "cached_input": 0.025,
        "output": 2.00,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
    "gpt-4o-mini-2024-07-18": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}


@dataclass(frozen=True)
class Pricing:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class BridgeConfig:
    model: str
    max_output_tokens: int
    timeout_seconds: float
    instructions: str
    drip_enabled: bool
    drip_usd_per_hour: float
    drip_bucket_usd: float
    drip_start_usd: float
    drip_estimate_multiplier: float
    prompt_cache_key: str
    use_conversation_state: bool
    pricing: Pricing


@dataclass
class PendingCommand:
    command: str
    raw_text: str = ""
    completed: bool = False
    error: str | None = None
    condition: threading.Condition = field(default_factory=threading.Condition)

    def append(self, text: str) -> None:
        with self.condition:
            self.raw_text += text
            if PROMPT_TOKEN in self.raw_text:
                self.completed = True
            self.condition.notify_all()

    def fail(self, message: str) -> None:
        with self.condition:
            self.error = message
            self.condition.notify_all()

    def wait(self, timeout_seconds: float) -> str:
        deadline = time.monotonic() + timeout_seconds
        with self.condition:
            while True:
                if self.error is not None:
                    raise OSError(self.error)
                if self.completed:
                    return self.raw_text
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for kernel prompt after `{self.command}`")
                self.condition.wait(timeout=remaining)


def sanitize_line(text: str, limit: int = 320) -> str:
    compact = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return compact[:limit] if compact else "ok"


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def env_string(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip()
    return stripped if stripped else default


def normalize_model_name(model: str) -> str:
    return model.strip().lower().replace(" ", "-")


def resolve_pricing(model: str) -> Pricing:
    explicit_input = os.environ.get("OPENAI_PRICE_INPUT_PER_1M")
    explicit_cached_input = os.environ.get("OPENAI_PRICE_CACHED_INPUT_PER_1M")
    explicit_output = os.environ.get("OPENAI_PRICE_OUTPUT_PER_1M")
    if explicit_input and explicit_cached_input and explicit_output:
        return Pricing(
            input_per_million=float(explicit_input),
            cached_input_per_million=float(explicit_cached_input),
            output_per_million=float(explicit_output),
        )

    known = MODEL_PRICING_USD_PER_1M.get(normalize_model_name(model))
    if known is None:
        return Pricing(0.0, 0.0, 0.0)
    return Pricing(
        input_per_million=known["input"],
        cached_input_per_million=known["cached_input"],
        output_per_million=known["output"],
    )


def build_config(args: argparse.Namespace) -> BridgeConfig:
    model = args.model
    pricing = resolve_pricing(model)
    config = BridgeConfig(
        model=model,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
        instructions=args.instructions,
        drip_enabled=env_flag("OPENAI_DRIP_ENABLED", True),
        drip_usd_per_hour=env_float("OPENAI_DRIP_CENTS_PER_HOUR", 1.0) / 100.0,
        drip_bucket_usd=env_float("OPENAI_DRIP_BUCKET_CENTS", 10.0) / 100.0,
        drip_start_usd=env_float("OPENAI_DRIP_START_CENTS", 1.0) / 100.0,
        drip_estimate_multiplier=max(1.0, env_float("OPENAI_DRIP_ESTIMATE_MULTIPLIER", 1.15)),
        prompt_cache_key=env_string("OPENAI_PROMPT_CACHE_KEY", DEFAULT_PROMPT_CACHE_KEY),
        use_conversation_state=env_flag("OPENAI_USE_CONVERSATION_STATE", False),
        pricing=pricing,
    )
    if config.drip_enabled and (
        config.pricing.input_per_million <= 0.0 or config.pricing.output_per_million <= 0.0
    ):
        raise ValueError(
            f"unknown pricing for model {model!r}; set OPENAI_PRICE_INPUT_PER_1M, "
            "OPENAI_PRICE_CACHED_INPUT_PER_1M, and OPENAI_PRICE_OUTPUT_PER_1M"
        )
    return config


def connect_socket(path: str) -> socket.socket:
    while True:
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(path)
            return client
        except OSError:
            time.sleep(0.5)


def write_line(sock: socket.socket, text: str) -> None:
    sock.sendall((text + "\r").encode("utf-8", errors="replace"))


def default_state(start_balance_usd: float, now: float) -> dict[str, object]:
    return {
        "sessions": {},
        "budget": {
            "balance_usd": max(0.0, start_balance_usd),
            "last_refill_unix": now,
        },
        "totals": {
            "approved_requests": 0,
            "deferred_requests": 0,
            "error_requests": 0,
            "spent_usd": 0.0,
        },
    }


def normalize_sessions(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    sessions: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        normalized: dict[str, str] = {}
        for inner_key, inner_value in value.items():
            if isinstance(inner_key, str):
                normalized[inner_key] = str(inner_value)
        sessions[key] = normalized
    return sessions


def load_state(path: Path, *, start_balance_usd: float) -> dict[str, object]:
    now = time.time()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_state(start_balance_usd, now)
    except json.JSONDecodeError:
        return default_state(start_balance_usd, now)

    if not isinstance(raw, dict):
        return default_state(start_balance_usd, now)

    if "sessions" not in raw and "budget" not in raw and "totals" not in raw:
        state = default_state(start_balance_usd, now)
        state["sessions"] = normalize_sessions(raw)
        return state

    state = default_state(start_balance_usd, now)
    state["sessions"] = normalize_sessions(raw.get("sessions"))

    budget = raw.get("budget")
    if isinstance(budget, dict):
        try:
            state["budget"]["balance_usd"] = float(budget.get("balance_usd", start_balance_usd))
        except (TypeError, ValueError):
            state["budget"]["balance_usd"] = start_balance_usd
        try:
            state["budget"]["last_refill_unix"] = float(budget.get("last_refill_unix", now))
        except (TypeError, ValueError):
            state["budget"]["last_refill_unix"] = now

    totals = raw.get("totals")
    if isinstance(totals, dict):
        for key in ("approved_requests", "deferred_requests", "error_requests"):
            try:
                state["totals"][key] = int(totals.get(key, state["totals"][key]))
            except (TypeError, ValueError):
                pass
        try:
            state["totals"]["spent_usd"] = float(totals.get("spent_usd", state["totals"]["spent_usd"]))
        except (TypeError, ValueError):
            pass

    return state


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def append_ledger(path: Path, entry: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def load_window_bytes(path: Path, *, window_bytes: int) -> bytes | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) > window_bytes:
        data = data[:window_bytes]
    if len(data) < window_bytes:
        data = data.ljust(window_bytes, b"\x00")
    return data


def save_window_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def count_journal_entries(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except FileNotFoundError:
        return 0


def latest_journal_event(path: Path, event_name: str) -> dict[str, object] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and str(payload.get("event") or "") == event_name:
            return payload
    return None


def parse_kernel_chat(line: str) -> dict[str, str]:
    if not line.startswith(REQUEST_PREFIX):
        raise ValueError("unsupported request")
    payload = json.loads(line[len(REQUEST_PREFIX) :].strip())
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    session = str(payload.get("session") or "kernel-v3").strip() or "kernel-v3"
    prompt = str(payload.get("prompt") or "").strip()
    tick = str(payload.get("tick") or "").strip()
    if not prompt:
        raise ValueError("missing prompt")
    return {
        "session": session,
        "prompt": prompt,
        "tick": tick,
    }


def extract_output_text(data: dict) -> str:
    outputs = data.get("output")
    if not isinstance(outputs, list):
        raise ValueError("response missing output items")
    chunks: list[str] = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
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
                    chunks.append(text.strip())
    if chunks:
        return "\n".join(chunks)
    raise ValueError("response did not contain output_text")


def is_safe_command(command: str) -> bool:
    return any(pattern.fullmatch(command) for pattern in SAFE_COMMAND_PATTERNS)


def build_mock_reply(prompt: str) -> str:
    lowered = prompt.lower()
    if "inspect" in lowered or "status" in lowered:
        return "CMD: status"
    if "peek" in lowered or "code" in lowered:
        return "CMD: peek 0x0000 0x10"
    return f"AI: mock bridge heard: {sanitize_line(prompt, 120)}"


def normalize_reply(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return "AI: empty bridge reply"
    if first_line.startswith("CMD:"):
        command = first_line[4:].strip()
        if is_safe_command(command):
            return f"CMD: {command}"
        return f"AI: rejected unsafe command: {sanitize_line(command, 120)}"
    if first_line.startswith("AI:"):
        return f"AI: {sanitize_line(first_line[3:], 280)}"
    return f"AI: {sanitize_line(first_line, 280)}"


def iso_timestamp(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_request_input(prompt: str, tick: str) -> str:
    return f"kernel tick {tick or 'unknown'}\noperator prompt: {prompt}"


def estimate_tokens(text: str) -> int:
    if not text.strip():
        return 0
    words = len(re.findall(r"\S+", text))
    chars = len(text)
    return max(1, math.ceil(chars / 4), math.ceil(words * 1.4))


def usd_for_tokens(tokens: int, price_per_million: float) -> float:
    return (tokens * price_per_million) / 1_000_000.0


def estimate_request(prompt: str, tick: str, *, config: BridgeConfig) -> dict[str, float | int]:
    estimated_input_tokens = estimate_tokens(config.instructions) + estimate_tokens(build_request_input(prompt, tick)) + 24
    base_cost_usd = (
        usd_for_tokens(estimated_input_tokens, config.pricing.input_per_million)
        + usd_for_tokens(config.max_output_tokens, config.pricing.output_per_million)
    )
    if config.use_conversation_state:
        base_cost_usd *= 1.25
    reserve_usd = base_cost_usd * config.drip_estimate_multiplier
    return {
        "estimated_input_tokens": estimated_input_tokens,
        "base_cost_usd": base_cost_usd,
        "reserve_usd": reserve_usd,
    }


def refill_budget(state: dict[str, object], *, config: BridgeConfig, now: float) -> float:
    budget = state.get("budget")
    if not isinstance(budget, dict):
        raise ValueError("bridge state budget is invalid")
    try:
        last_refill_unix = float(budget.get("last_refill_unix", now))
    except (TypeError, ValueError):
        last_refill_unix = now
    try:
        balance_usd = float(budget.get("balance_usd", 0.0))
    except (TypeError, ValueError):
        balance_usd = 0.0

    elapsed_seconds = max(0.0, now - last_refill_unix)
    if config.drip_enabled:
        balance_usd = min(
            config.drip_bucket_usd,
            balance_usd + (elapsed_seconds * (config.drip_usd_per_hour / 3600.0)),
        )

    budget["balance_usd"] = balance_usd
    budget["last_refill_unix"] = now
    return balance_usd


def seconds_until_balance(balance_usd: float, required_usd: float, *, config: BridgeConfig) -> float:
    if required_usd <= balance_usd or config.drip_usd_per_hour <= 0.0:
        return 0.0
    missing = required_usd - balance_usd
    return missing / (config.drip_usd_per_hour / 3600.0)


def format_wait_seconds(seconds: float) -> str:
    total_seconds = max(0, int(math.ceil(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def extract_usage_cost(data: dict, *, pricing: Pricing) -> dict[str, int | float] | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)

    input_details = usage.get("input_tokens_details")
    cached_input_tokens = 0
    if isinstance(input_details, dict):
        cached_input_tokens = int(input_details.get("cached_tokens") or 0)
    cached_input_tokens = max(0, min(input_tokens, cached_input_tokens))
    uncached_input_tokens = max(0, input_tokens - cached_input_tokens)

    output_details = usage.get("output_tokens_details")
    reasoning_tokens = 0
    if isinstance(output_details, dict):
        reasoning_tokens = int(output_details.get("reasoning_tokens") or 0)

    cost_usd = (
        usd_for_tokens(uncached_input_tokens, pricing.input_per_million)
        + usd_for_tokens(cached_input_tokens, pricing.cached_input_per_million or pricing.input_per_million)
        + usd_for_tokens(output_tokens, pricing.output_per_million)
    )
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cost_usd": cost_usd,
    }


def mock_usage_cost(reply: str, estimate: dict[str, float | int], *, pricing: Pricing) -> dict[str, int | float]:
    input_tokens = int(estimate["estimated_input_tokens"])
    output_tokens = estimate_tokens(reply)
    cost_usd = usd_for_tokens(input_tokens, pricing.input_per_million) + usd_for_tokens(output_tokens, pricing.output_per_million)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": 0,
        "uncached_input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": 0,
        "cost_usd": cost_usd,
    }


def sessions_map(state: dict[str, object]) -> dict[str, dict[str, str]]:
    sessions = normalize_sessions(state.get("sessions"))
    state["sessions"] = sessions
    return sessions


def totals_map(state: dict[str, object]) -> dict[str, int | float]:
    totals = state.get("totals")
    if not isinstance(totals, dict):
        totals = {
            "approved_requests": 0,
            "deferred_requests": 0,
            "error_requests": 0,
            "spent_usd": 0.0,
        }
        state["totals"] = totals
    return totals


def budget_reply(balance_usd: float, required_usd: float, wait_seconds: float) -> str:
    return (
        "AI: budget defer: "
        f"balance ${balance_usd:.4f}, need about ${required_usd:.4f}, "
        f"wait {format_wait_seconds(wait_seconds)}"
    )


def call_openai(prompt: str, tick: str, session: str, state: dict[str, object], *, config: BridgeConfig, ledger_path: Path) -> str:
    now = time.time()
    sessions = sessions_map(state)
    totals = totals_map(state)
    balance_before_usd = refill_budget(state, config=config, now=now)
    estimate = estimate_request(prompt, tick, config=config)

    if config.drip_enabled and balance_before_usd < float(estimate["reserve_usd"]):
        totals["deferred_requests"] = int(totals.get("deferred_requests", 0)) + 1
        wait_seconds = seconds_until_balance(balance_before_usd, float(estimate["reserve_usd"]), config=config)
        append_ledger(
            ledger_path,
            {
                "timestamp": iso_timestamp(now),
                "type": "defer",
                "session": session,
                "tick": tick,
                "model": config.model,
                "prompt": sanitize_line(prompt, 160),
                "balance_usd": round(balance_before_usd, 6),
                "required_usd": round(float(estimate["reserve_usd"]), 6),
                "wait_seconds": int(math.ceil(wait_seconds)),
                "estimated_input_tokens": int(estimate["estimated_input_tokens"]),
                "max_output_tokens": config.max_output_tokens,
            },
        )
        return budget_reply(balance_before_usd, float(estimate["reserve_usd"]), wait_seconds)

    reserved_usd = 0.0
    if config.drip_enabled:
        reserved_usd = float(estimate["reserve_usd"])
        state["budget"]["balance_usd"] = balance_before_usd - reserved_usd

    input_text = build_request_input(prompt, tick)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    use_mock = not api_key or os.environ.get("OPENAI_MOCK", "0") == "1"

    try:
        if use_mock:
            reply = build_mock_reply(prompt)
            usage_cost = mock_usage_cost(reply, estimate, pricing=config.pricing)
            response_id = ""
        else:
            request_payload: dict[str, object] = {
                "model": config.model,
                "instructions": config.instructions,
                "input": input_text,
                "max_output_tokens": config.max_output_tokens,
                "store": False,
                "service_tier": "default",
                "prompt_cache_key": f"{config.prompt_cache_key}:{session}",
                "text": {
                    "format": {
                        "type": "text",
                    }
                },
            }
            if config.use_conversation_state:
                previous_response_id = sessions.get(session, {}).get("previous_response_id", "").strip()
                if previous_response_id:
                    request_payload["previous_response_id"] = previous_response_id

            request = Request(
                "https://api.openai.com/v1/responses",
                data=json.dumps(request_payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))

            response_id = str(data.get("id") or "").strip()
            if config.use_conversation_state and response_id:
                sessions[session] = {"previous_response_id": response_id}
            elif not config.use_conversation_state:
                sessions.pop(session, None)

            usage_cost = extract_usage_cost(data, pricing=config.pricing)
            reply = normalize_reply(extract_output_text(data))

        actual_cost_usd = float(usage_cost["cost_usd"]) if usage_cost is not None else float(estimate["base_cost_usd"])
        if config.drip_enabled:
            state["budget"]["balance_usd"] = float(state["budget"].get("balance_usd", 0.0)) + reserved_usd - actual_cost_usd
        totals["approved_requests"] = int(totals.get("approved_requests", 0)) + 1
        totals["spent_usd"] = float(totals.get("spent_usd", 0.0)) + actual_cost_usd

        append_ledger(
            ledger_path,
            {
                "timestamp": iso_timestamp(now),
                "type": "approved",
                "session": session,
                "tick": tick,
                "model": config.model,
                "mock": use_mock,
                "prompt": sanitize_line(prompt, 160),
                "reply": reply,
                "estimated_input_tokens": int(estimate["estimated_input_tokens"]),
                "max_output_tokens": config.max_output_tokens,
                "reserved_usd": round(reserved_usd, 6),
                "actual_cost_usd": round(actual_cost_usd, 6),
                "balance_after_usd": round(float(state["budget"].get("balance_usd", 0.0)), 6),
                "response_id": response_id,
                "usage": usage_cost,
            },
        )
        return reply
    except Exception:
        if config.drip_enabled and reserved_usd:
            state["budget"]["balance_usd"] = float(state["budget"].get("balance_usd", 0.0)) + reserved_usd
        totals["error_requests"] = int(totals.get("error_requests", 0)) + 1
        append_ledger(
            ledger_path,
            {
                "timestamp": iso_timestamp(now),
                "type": "error",
                "session": session,
                "tick": tick,
                "model": config.model,
                "prompt": sanitize_line(prompt, 160),
                "reserved_usd": round(reserved_usd, 6),
                "balance_after_usd": round(float(state["budget"].get("balance_usd", 0.0)), 6),
            },
        )
        raise


def handle_kernel_request(line: str, state: dict[str, object], *, config: BridgeConfig, ledger_path: Path) -> str:
    payload = parse_kernel_chat(line)
    return call_openai(
        payload["prompt"],
        payload["tick"],
        payload["session"],
        state,
        config=config,
        ledger_path=ledger_path,
    )


def log_startup(
    config: BridgeConfig,
    *,
    state: dict[str, object],
    ledger_path: Path,
    control_socket_path: Path,
    journal_path: Path,
    shadow_path: Path,
    shadow_meta_path: Path,
    transport_window_bytes: int,
) -> None:
    budget = state.get("budget")
    balance = 0.0
    if isinstance(budget, dict):
        try:
            balance = float(budget.get("balance_usd", 0.0))
        except (TypeError, ValueError):
            balance = 0.0
    print(
        "bridge config: "
        f"model={config.model} "
        f"drip={'on' if config.drip_enabled else 'off'} "
        f"rate_cph={config.drip_usd_per_hour * 100.0:.2f} "
        f"bucket_c={config.drip_bucket_usd * 100.0:.2f} "
        f"start_balance=${balance:.4f} "
        f"stateful={'on' if config.use_conversation_state else 'off'} "
        f"transport_window={transport_window_bytes} "
        f"control={control_socket_path} "
        f"journal={journal_path} "
        f"shadow={shadow_path} "
        f"shadow_meta={shadow_meta_path} "
        f"ledger={ledger_path}"
    )


def parse_int_value(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field} must be an integer")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"missing {field}")
        try:
            return int(text, 0)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise ValueError(f"invalid {field}: {value!r}")


def parse_bool_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def parse_encoding(value: object) -> str:
    encoding = "hex" if value is None else str(value).strip().lower()
    if encoding not in {"hex", "base64"}:
        raise ValueError("encoding must be `hex` or `base64`")
    return encoding


def split_kernel_output(raw_text: str, command: str) -> list[str]:
    trimmed = raw_text.split(PROMPT_TOKEN, 1)[0]
    normalized = trimmed.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if lines and lines[0] == command:
        return lines[1:]
    return lines


def parse_peek_lines(lines: list[str], *, expected_offset: int, expected_count: int) -> bytes:
    for line in lines:
        match = PEEK_LINE_RE.fullmatch(line)
        if match is None:
            continue
        offset = int(match.group(1), 16)
        if offset != expected_offset:
            continue
        payload = match.group(2).strip()
        if not payload:
            raise ValueError("peek returned no bytes")
        tokens = payload.split()
        if len(tokens) < expected_count:
            raise ValueError(f"peek returned {len(tokens)} bytes; expected {expected_count}")
        try:
            values = bytes(int(token, 16) for token in tokens[:expected_count])
        except ValueError as exc:
            raise ValueError(f"invalid peek payload: {payload}") from exc
        return values
    raise ValueError(f"missing peek payload for offset 0x{expected_offset:04X}")


def encode_binary_payload(data: bytes, encoding: str) -> dict[str, str]:
    if encoding == "hex":
        return {"data_hex": data.hex().upper()}
    return {"data_b64": base64.b64encode(data).decode("ascii")}


def decode_binary_payload(payload: dict[str, object]) -> bytes:
    if "data_hex" in payload:
        hex_text = re.sub(r"\s+", "", str(payload["data_hex"]))
        if not hex_text:
            return b""
        try:
            return bytes.fromhex(hex_text)
        except ValueError as exc:
            raise ValueError("invalid data_hex payload") from exc
    if "data_b64" in payload:
        try:
            return base64.b64decode(str(payload["data_b64"]), validate=True)
        except ValueError as exc:
            raise ValueError("invalid data_b64 payload") from exc
    raise ValueError("missing data_hex or data_b64 payload")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def diff_spans(before: bytes, after: bytes) -> list[dict[str, object]]:
    if len(before) != len(after):
        raise ValueError("diff inputs must be the same length")
    spans: list[dict[str, object]] = []
    start: int | None = None
    for index, (left, right) in enumerate(zip(before, after)):
        if left != right and start is None:
            start = index
            continue
        if left == right and start is not None:
            spans.append(
                {
                    "offset": start,
                    "before": before[start:index],
                    "after": after[start:index],
                }
            )
            start = None
    if start is not None:
        spans.append(
            {
                "offset": start,
                "before": before[start:],
                "after": after[start:],
            }
        )
    return spans


def serialize_spans(spans: list[dict[str, object]], *, include_before: bool = False) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for span in spans:
        offset = int(span["offset"])
        before = bytes(span["before"])
        after = bytes(span["after"])
        payload: dict[str, object] = {
            "offset": offset,
            "length": len(after),
            "data_hex": after.hex().upper(),
        }
        if include_before:
            payload["before_hex"] = before.hex().upper()
        serialized.append(payload)
    return serialized


def apply_serialized_spans(target: bytearray, spans: list[dict[str, object]]) -> None:
    for span in spans:
        offset = int(span["offset"])
        data = bytes.fromhex(str(span["data_hex"]))
        target[offset : offset + len(data)] = data


class KernelBridgeServer:
    def __init__(
        self,
        *,
        serial_socket_path: str,
        control_socket_path: Path,
        state_path: Path,
        ledger_path: Path,
        journal_path: Path,
        shadow_path: Path,
        shadow_meta_path: Path,
        rollback_path: Path,
        transport_window_bytes: int,
        config: BridgeConfig,
    ) -> None:
        self.serial_socket_path = serial_socket_path
        self.control_socket_path = control_socket_path
        self.state_path = state_path
        self.ledger_path = ledger_path
        self.journal_path = journal_path
        self.shadow_path = shadow_path
        self.shadow_meta_path = shadow_meta_path
        self.rollback_path = rollback_path
        self.transport_window_bytes = transport_window_bytes
        self.config = config

        self.state_lock = threading.Lock()
        self.journal_lock = threading.Lock()
        self.shadow_lock = threading.Lock()
        self.serial_socket_lock = threading.Lock()
        self.serial_write_lock = threading.Lock()
        self.command_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.state = load_state(state_path, start_balance_usd=config.drip_start_usd)
        self.journal_sequence = count_journal_entries(journal_path)

        self.serial_socket: socket.socket | None = None
        self.pending_command: PendingCommand | None = None
        self.connected_event = threading.Event()
        self.prompt_seen_event = threading.Event()
        self.last_connect_unix = 0.0
        self.last_prompt_unix = 0.0
        self.line_buffer = ""
        self.prompt_tail = ""

    def start(self) -> None:
        threading.Thread(target=self.serial_loop, name="kernel-serial-loop", daemon=True).start()
        threading.Thread(target=self.control_loop, name="kernel-control-loop", daemon=True).start()
        self.append_journal_event(
            "bridge_started",
            serial_socket=self.serial_socket_path,
            control_socket=str(self.control_socket_path),
            journal_path=str(self.journal_path),
            shadow_path=str(self.shadow_path),
            shadow_meta_path=str(self.shadow_meta_path),
            rollback_path=str(self.rollback_path),
            transport_window_bytes=self.transport_window_bytes,
            model=self.config.model,
        )

    def wait_forever(self) -> None:
        while True:
            time.sleep(60.0)

    def append_journal_event(self, event: str, **payload: object) -> None:
        now = time.time()
        with self.journal_lock:
            self.journal_sequence += 1
            append_ledger(
                self.journal_path,
                {
                    "sequence": self.journal_sequence,
                    "timestamp": iso_timestamp(now),
                    "event": event,
                    **payload,
                },
            )

    def canonical_stage2_path(self) -> Path:
        return Path("binary") / "stage2.bin"

    def canonical_window_bytes(self) -> bytes:
        data = load_window_bytes(self.canonical_stage2_path(), window_bytes=self.transport_window_bytes)
        if data is None:
            raise FileNotFoundError("missing binary/stage2.bin")
        return data

    def shadow_bytes(self) -> bytes | None:
        with self.shadow_lock:
            return load_window_bytes(self.shadow_path, window_bytes=self.transport_window_bytes)

    def shadow_meta(self) -> dict[str, object] | None:
        try:
            raw = json.loads(self.shadow_meta_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        return raw if isinstance(raw, dict) else None

    def save_shadow_meta(self, meta: dict[str, object]) -> None:
        self.shadow_meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.shadow_meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    def shadow_base_bytes(self) -> bytes:
        meta = self.shadow_meta()
        if isinstance(meta, dict):
            base_hex = str(meta.get("base_window_hex") or "")
            if base_hex:
                return bytes.fromhex(base_hex)
        return self.canonical_window_bytes()

    def rollback_bytes(self) -> bytes | None:
        return load_window_bytes(self.rollback_path, window_bytes=self.transport_window_bytes)

    def validate_shadow_window(self, data: bytes) -> None:
        if len(data) != self.transport_window_bytes:
            raise ValueError(
                f"shadow window must be exactly {self.transport_window_bytes} bytes, got {len(data)}"
            )
        canonical = self.canonical_window_bytes()
        canonical_size = self.canonical_stage2_path().stat().st_size
        if not any(data[: max(32, canonical_size)]):
            raise ValueError("shadow window cannot zero the entire active stage2 prefix")
        if canonical_size and not any(data[:canonical_size]):
            raise ValueError("shadow window cannot zero the canonical stage2 footprint")

    def shadow_summary(self) -> dict[str, object]:
        shadow = self.shadow_bytes()
        meta = self.shadow_meta()
        canonical = self.canonical_window_bytes()
        if shadow is None:
            return {
                "exists": False,
                "path": str(self.shadow_path),
            }
        spans = diff_spans(canonical, shadow)
        changed_bytes = sum(int(span["length"]) for span in serialize_spans(spans))
        return {
            "exists": True,
            "path": str(self.shadow_path),
            "meta_path": str(self.shadow_meta_path),
            "bytes": len(shadow),
            "sha256": sha256_hex(shadow),
            "base_source": "" if meta is None else str(meta.get("source") or ""),
            "base_sha256": "" if meta is None else str(meta.get("base_sha256") or ""),
            "changed_vs_canonical_bytes": changed_bytes,
            "changed_vs_canonical_spans": len(spans),
        }

    def rollback_summary(self) -> dict[str, object]:
        snapshot = self.rollback_bytes()
        if snapshot is None:
            return {
                "exists": False,
                "path": str(self.rollback_path),
            }
        return {
            "exists": True,
            "path": str(self.rollback_path),
            "bytes": len(snapshot),
            "sha256": sha256_hex(snapshot),
        }

    def ensure_shadow(self) -> bytes:
        existing = self.shadow_bytes()
        if existing is not None:
            if self.shadow_meta() is None:
                self.save_shadow_meta(
                    {
                        "source": "canonical",
                        "base_sha256": sha256_hex(self.canonical_window_bytes()),
                        "base_window_hex": self.canonical_window_bytes().hex().upper(),
                        "initialized_at": iso_timestamp(time.time()),
                    }
                )
            return existing
        self.initialize_shadow("canonical")
        initialized = self.shadow_bytes()
        if initialized is None:
            raise OSError("failed to initialize shadow window")
        return initialized

    def serial_loop(self) -> None:
        while True:
            sock = connect_socket(self.serial_socket_path)
            with self.serial_socket_lock:
                self.serial_socket = sock
            self.connected_event.set()
            self.last_connect_unix = time.time()
            print(f"bridge connected to {self.serial_socket_path}")
            try:
                with sock:
                    while True:
                        data = sock.recv(4096)
                        if not data:
                            raise OSError("serial socket closed")
                        text = data.decode("utf-8", errors="replace")
                        self.process_serial_chunk(text)
            except OSError as exc:
                print(f"bridge reconnecting after serial error: {sanitize_line(str(exc), 160)}")
            finally:
                with self.serial_socket_lock:
                    if self.serial_socket is sock:
                        self.serial_socket = None
                self.connected_event.clear()
                self.prompt_seen_event.clear()
                self.line_buffer = ""
                self.prompt_tail = ""
                self.fail_pending("serial connection lost")
                time.sleep(0.5)

    def process_serial_chunk(self, text: str) -> None:
        if not text:
            return
        self.capture_pending_chunk(text)
        self.update_prompt_seen(text)
        self.process_serial_lines(text)

    def capture_pending_chunk(self, text: str) -> None:
        with self.pending_lock:
            pending = self.pending_command
        if pending is not None:
            pending.append(text)

    def update_prompt_seen(self, text: str) -> None:
        combined = self.prompt_tail + text
        if PROMPT_TOKEN in combined:
            self.last_prompt_unix = time.time()
            self.prompt_seen_event.set()
        self.prompt_tail = combined[-(len(PROMPT_TOKEN) - 1) :]

    def process_serial_lines(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.line_buffer += normalized
        while "\n" in self.line_buffer:
            line, self.line_buffer = self.line_buffer.split("\n", 1)
            stripped = line.strip()
            if not stripped:
                continue
            print(f"kernel: {sanitize_line(stripped, 240)}")
            if stripped.startswith(REQUEST_PREFIX):
                self.reply_to_kernel_chat(stripped)

    def reply_to_kernel_chat(self, line: str) -> None:
        payload: dict[str, str] | None = None
        try:
            payload = parse_kernel_chat(line)
            with self.state_lock:
                reply = call_openai(
                    payload["prompt"],
                    payload["tick"],
                    payload["session"],
                    self.state,
                    config=self.config,
                    ledger_path=self.ledger_path,
                )
                save_state(self.state_path, self.state)
        except (ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
            reply = f"AI: bridge error: {sanitize_line(str(exc), 200)}"
        if payload is not None:
            self.append_journal_event(
                "kernel_chat",
                session=payload["session"],
                tick=payload["tick"],
                prompt=sanitize_line(payload["prompt"], 200),
                reply=reply,
            )
        print(f"bridge: {reply}")
        self.send_serial_line(reply)

    def send_serial_line(self, text: str) -> None:
        with self.serial_write_lock:
            with self.serial_socket_lock:
                sock = self.serial_socket
            if sock is None:
                raise OSError("serial socket not connected")
            write_line(sock, text)

    def fail_pending(self, message: str) -> None:
        with self.pending_lock:
            pending = self.pending_command
        if pending is not None:
            pending.fail(message)

    def ensure_ready(self, timeout_seconds: float) -> None:
        if not self.connected_event.wait(timeout_seconds):
            raise TimeoutError("bridge is not connected to the kernel serial socket")
        if self.prompt_seen_event.wait(min(timeout_seconds, 2.0)):
            return
        self.send_serial_line("")
        if self.prompt_seen_event.wait(timeout_seconds):
            return
        raise TimeoutError("kernel prompt was not observed")

    def execute_command(self, command: str, *, timeout_seconds: float = 10.0) -> dict[str, object]:
        normalized_command = " ".join(command.replace("\r", " ").replace("\n", " ").split())
        if not normalized_command:
            raise ValueError("missing command")
        self.ensure_ready(timeout_seconds)

        with self.command_lock:
            pending = PendingCommand(command=normalized_command)
            with self.pending_lock:
                self.pending_command = pending
            try:
                self.send_serial_line(normalized_command)
                raw_text = pending.wait(timeout_seconds)
            finally:
                with self.pending_lock:
                    if self.pending_command is pending:
                        self.pending_command = None

        lines = split_kernel_output(raw_text, normalized_command)
        return {
            "command": normalized_command,
            "raw": raw_text.split(PROMPT_TOKEN, 1)[0],
            "lines": lines,
        }

    def validate_range(self, offset: int, length: int) -> None:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if length < 0:
            raise ValueError("length must be non-negative")
        if offset + length > self.transport_window_bytes:
            raise ValueError(
                f"requested range 0x{offset:04X}+0x{length:04X} exceeds "
                f"transport window 0x{self.transport_window_bytes:04X}"
            )

    def read_live_bytes(self, offset: int, length: int) -> bytes:
        self.validate_range(offset, length)
        data = bytearray()
        cursor = offset
        remaining = length
        while remaining > 0:
            chunk_size = min(remaining, PEEK_MAX_BYTES)
            response = self.execute_command(f"peek 0x{cursor:04X} 0x{chunk_size:02X}", timeout_seconds=10.0)
            lines = response["lines"]
            if not isinstance(lines, list):
                raise ValueError("invalid peek response")
            data.extend(parse_peek_lines(lines, expected_offset=cursor, expected_count=chunk_size))
            cursor += chunk_size
            remaining -= chunk_size
        return bytes(data)

    def initialize_shadow(self, source: str) -> dict[str, object]:
        normalized_source = source.strip().lower()
        if normalized_source == "canonical":
            data = self.canonical_window_bytes()
        elif normalized_source == "live":
            data = self.read_live_bytes(0, self.transport_window_bytes)
        else:
            raise ValueError("shadow source must be `canonical` or `live`")
        self.validate_shadow_window(data)
        with self.shadow_lock:
            save_window_bytes(self.shadow_path, data)
            self.save_shadow_meta(
                {
                    "source": normalized_source,
                    "base_sha256": sha256_hex(data),
                    "base_window_hex": data.hex().upper(),
                    "initialized_at": iso_timestamp(time.time()),
                }
            )
        self.append_journal_event(
            "shadow_initialized",
            source=normalized_source,
            shadow_sha256=sha256_hex(data),
            window_hex=data.hex().upper(),
        )
        return {
            "source": normalized_source,
            "shadow_sha256": sha256_hex(data),
            **self.shadow_summary(),
        }

    def read_shadow_bytes(self, offset: int, length: int) -> bytes:
        self.validate_range(offset, length)
        shadow = self.ensure_shadow()
        return shadow[offset : offset + length]

    def write_shadow_bytes(self, offset: int, data: bytes) -> dict[str, object]:
        self.validate_range(offset, len(data))
        shadow = bytearray(self.ensure_shadow())
        before = bytes(shadow[offset : offset + len(data)])
        shadow[offset : offset + len(data)] = data
        self.validate_shadow_window(bytes(shadow))
        with self.shadow_lock:
            save_window_bytes(self.shadow_path, bytes(shadow))
        self.append_journal_event(
            "shadow_write",
            offset=offset,
            length=len(data),
            before_hex=before.hex().upper(),
            data_hex=data.hex().upper(),
            shadow_sha256=sha256_hex(bytes(shadow)),
        )
        return {
            "offset": offset,
            "bytes_written": len(data),
            "before_hex": before.hex().upper(),
            "sha256": sha256_hex(bytes(shadow)),
            **self.shadow_summary(),
        }

    def diff_shadow(self, *, base: str, limit_spans: int) -> dict[str, object]:
        normalized_base = base.strip().lower()
        shadow = self.ensure_shadow()
        if normalized_base == "canonical":
            baseline = self.canonical_window_bytes()
        elif normalized_base == "live":
            baseline = self.read_live_bytes(0, self.transport_window_bytes)
        else:
            raise ValueError("shadow diff base must be `canonical` or `live`")
        spans = diff_spans(baseline, shadow)
        serialized = serialize_spans(spans, include_before=False)
        changed_bytes = sum(int(span["length"]) for span in serialized)
        result = {
            "base": normalized_base,
            "shadow_sha256": sha256_hex(shadow),
            "base_sha256": sha256_hex(baseline),
            "changed_spans": len(serialized),
            "changed_bytes": changed_bytes,
            "spans": serialized[: max(0, limit_spans)],
            "truncated": len(serialized) > max(0, limit_spans),
        }
        self.append_journal_event(
            "shadow_diff",
            base=normalized_base,
            shadow_sha256=result["shadow_sha256"],
            base_sha256=result["base_sha256"],
            changed_spans=result["changed_spans"],
            changed_bytes=result["changed_bytes"],
        )
        return result

    def write_live_bytes(self, offset: int, data: bytes, *, persist: bool, verify: bool) -> dict[str, object]:
        self.validate_range(offset, len(data))
        cursor = offset
        written = 0
        while written < len(data):
            chunk = data[written : written + PATCH_MAX_BYTES]
            hex_bytes = " ".join(f"{byte:02X}" for byte in chunk)
            response = self.execute_command(f"patch 0x{cursor:04X} {hex_bytes}", timeout_seconds=10.0)
            lines = response["lines"]
            if not isinstance(lines, list) or not any("patch applied" in line.lower() for line in lines):
                raise ValueError(f"kernel rejected live patch at 0x{cursor:04X}")
            cursor += len(chunk)
            written += len(chunk)

        persisted = False
        if persist:
            self.persist_live()
            persisted = True

        verified = False
        if verify and data:
            actual = self.read_live_bytes(offset, len(data))
            if actual != data:
                raise ValueError("verification readback mismatch")
            verified = True

        return {
            "bytes_written": len(data),
            "offset": offset,
            "persisted": persisted,
            "verified": verified,
            "sha256": sha256_hex(data),
        }

    def promote_shadow(self, *, persist: bool, verify: bool) -> dict[str, object]:
        shadow = self.ensure_shadow()
        self.validate_shadow_window(shadow)
        base_snapshot = self.shadow_base_bytes()
        delta_spans = diff_spans(base_snapshot, shadow)
        serialized_spans = serialize_spans(delta_spans, include_before=False)
        changed_bytes = sum(int(span["length"]) for span in serialized_spans)
        live_before = self.read_live_bytes(0, self.transport_window_bytes)
        save_window_bytes(self.rollback_path, live_before)
        self.append_journal_event(
            "shadow_promote_started",
            persist=persist,
            verify=verify,
            base_sha256=sha256_hex(base_snapshot),
            changed_spans=len(serialized_spans),
            changed_bytes=changed_bytes,
            live_sha256_before=sha256_hex(live_before),
            shadow_sha256=sha256_hex(shadow),
            rollback_window_hex=live_before.hex().upper(),
            spans=serialized_spans,
        )
        if not serialized_spans:
            result = {
                "changed_spans": 0,
                "changed_bytes": 0,
                "persisted": False,
                "verified": False,
                "shadow_sha256": sha256_hex(shadow),
                "live_sha256_before": sha256_hex(live_before),
                "live_sha256_after": sha256_hex(live_before),
            }
            self.append_journal_event("shadow_promote_noop", **result)
            return result

        persist_completed = False
        try:
            for span in serialized_spans:
                offset = int(span["offset"])
                data = bytes.fromhex(str(span["data_hex"]))
                self.write_live_bytes(offset, data, persist=False, verify=False)
            if verify:
                for span in serialized_spans:
                    offset = int(span["offset"])
                    data = bytes.fromhex(str(span["data_hex"]))
                    observed = self.read_live_bytes(offset, len(data))
                    if observed != data:
                        raise ValueError("shadow promote verification mismatch")
                live_after = self.read_live_bytes(0, self.transport_window_bytes)
            else:
                live_after = bytearray(live_before)
                apply_serialized_spans(live_after, serialized_spans)
                live_after = bytes(live_after)
            if persist:
                self.persist_live()
                persist_completed = True
            result = {
                "changed_spans": len(serialized_spans),
                "changed_bytes": changed_bytes,
                "persisted": persist_completed,
                "verified": verify,
                "shadow_sha256": sha256_hex(shadow),
                "live_sha256_before": sha256_hex(live_before),
                "live_sha256_after": sha256_hex(live_after),
                "spans": serialized_spans,
            }
            self.append_journal_event("shadow_promote_committed", **result)
            return result
        except Exception as exc:
            for span in serialized_spans:
                offset = int(span["offset"])
                before = live_before[offset : offset + int(span["length"])]
                self.write_live_bytes(offset, before, persist=False, verify=False)
            if persist_completed:
                self.persist_live()
            self.append_journal_event(
                "shadow_promote_rolled_back",
                reason=sanitize_line(str(exc), 200),
                persisted=persist_completed,
                live_sha256_restored=sha256_hex(live_before),
                spans=serialized_spans,
            )
            raise

    def rollback_live_window(self, *, persist: bool, verify: bool) -> dict[str, object]:
        snapshot = self.rollback_bytes()
        if snapshot is None:
            raise ValueError("no rollback snapshot available")
        with self.journal_lock:
            promote_event = latest_journal_event(self.journal_path, "shadow_promote_started")
        span_specs = promote_event.get("spans") if isinstance(promote_event, dict) else None
        live_before = self.read_live_bytes(0, self.transport_window_bytes)
        if isinstance(span_specs, list) and span_specs:
            serialized_spans: list[dict[str, object]] = []
            for spec in span_specs:
                if not isinstance(spec, dict):
                    continue
                offset = int(spec.get("offset") or 0)
                length = int(spec.get("length") or 0)
                if length <= 0:
                    continue
                before = snapshot[offset : offset + length]
                after = live_before[offset : offset + length]
                serialized_spans.append(
                    {
                        "offset": offset,
                        "length": length,
                        "data_hex": before.hex().upper(),
                        "before_hex": after.hex().upper(),
                    }
                )
        else:
            spans = diff_spans(live_before, snapshot)
            serialized_spans = serialize_spans(spans, include_before=True)
        for span in serialized_spans:
            offset = int(span["offset"])
            before = bytes.fromhex(str(span["data_hex"]))
            self.write_live_bytes(offset, before, persist=False, verify=False)
        if persist:
            self.persist_live()
        if verify:
            for span in serialized_spans:
                offset = int(span["offset"])
                expected = bytes.fromhex(str(span["data_hex"]))
                observed = self.read_live_bytes(offset, len(expected))
                if observed != expected:
                    raise ValueError("rollback verification mismatch")
            live_after = self.read_live_bytes(0, self.transport_window_bytes)
        else:
            live_after = bytearray(live_before)
            apply_serialized_spans(live_after, serialized_spans)
            live_after = bytes(live_after)
        result = {
            "changed_spans": len(serialized_spans),
            "changed_bytes": sum(int(span["length"]) for span in serialized_spans),
            "persisted": persist,
            "verified": verify,
            "live_sha256_before": sha256_hex(live_before),
            "live_sha256_after": sha256_hex(live_after),
            "rollback_sha256": sha256_hex(snapshot),
            "spans": serialized_spans,
            "scope": "promoted_spans" if isinstance(span_specs, list) and span_specs else "full_window",
            "source_sequence": 0 if not isinstance(promote_event, dict) else int(promote_event.get("sequence") or 0),
        }
        journal_payload = dict(result)
        journal_payload["window_hex"] = snapshot.hex().upper()
        self.append_journal_event("live_rollback_committed", **journal_payload)
        return result

    def persist_live(self) -> dict[str, object]:
        response = self.execute_command("persist", timeout_seconds=20.0)
        lines = response["lines"]
        if not isinstance(lines, list) or not any("persist: done" in line.lower() for line in lines):
            raise ValueError("persist did not complete")
        return {
            "lines": lines,
        }

    def snapshot_info(self) -> dict[str, object]:
        with self.state_lock:
            balance = refill_budget(self.state, config=self.config, now=time.time())
            save_state(self.state_path, self.state)
            totals = totals_map(self.state).copy()
        stage2_path = Path("binary") / "stage2.bin"
        stage2_bytes = 0
        if stage2_path.exists():
            stage2_bytes = stage2_path.stat().st_size
        return {
            "connected": self.connected_event.is_set(),
            "prompt_seen": self.prompt_seen_event.is_set(),
            "serial_socket": self.serial_socket_path,
            "control_socket": str(self.control_socket_path),
            "journal_path": str(self.journal_path),
            "journal_events": self.journal_sequence,
            "transport_window_bytes": self.transport_window_bytes,
            "stage2_canonical_bytes": stage2_bytes,
            "model": self.config.model,
            "drip_enabled": self.config.drip_enabled,
            "budget_balance_usd": round(balance, 6),
            "last_connect": iso_timestamp(self.last_connect_unix) if self.last_connect_unix else "",
            "last_prompt": iso_timestamp(self.last_prompt_unix) if self.last_prompt_unix else "",
            "totals": totals,
            "shadow": self.shadow_summary(),
            "rollback": self.rollback_summary(),
        }

    def control_loop(self) -> None:
        self.control_socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.control_socket_path.unlink()
        except FileNotFoundError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.control_socket_path))
        server.listen()
        print(f"bridge control socket ready at {self.control_socket_path}")

        with server:
            while True:
                conn, _ = server.accept()
                threading.Thread(target=self.handle_control_client, args=(conn,), daemon=True).start()

    def write_json_line(self, conn: socket.socket, payload: dict[str, object]) -> None:
        conn.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))

    def handle_control_client(self, conn: socket.socket) -> None:
        with conn:
            try:
                raw_request = conn.makefile("r", encoding="utf-8", errors="replace").readline()
                if not raw_request:
                    return
                request = json.loads(raw_request)
                if not isinstance(request, dict):
                    raise ValueError("control request must be a JSON object")
                self.dispatch_control_request(conn, request)
            except Exception as exc:
                try:
                    self.write_json_line(
                        conn,
                        {
                            "ok": False,
                            "error": sanitize_line(str(exc), 240),
                        },
                    )
                except OSError:
                    return

    def dispatch_control_request(self, conn: socket.socket, request: dict[str, object]) -> None:
        action = str(request.get("action") or "").strip().lower()
        if action == "info":
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "info",
                    **self.snapshot_info(),
                },
            )
            return

        if action == "command":
            command = str(request.get("command") or "").strip()
            timeout_seconds = float(request.get("timeout_seconds") or 10.0)
            response = self.execute_command(command, timeout_seconds=timeout_seconds)
            self.append_journal_event(
                "command_executed",
                command=response["command"],
                lines=response["lines"],
            )
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "command",
                    "command": response["command"],
                    "lines": response["lines"],
                    "raw": response["raw"],
                },
            )
            return

        if action == "read":
            offset = parse_int_value(request.get("offset"), "offset")
            length = parse_int_value(request.get("length"), "length")
            encoding = parse_encoding(request.get("encoding"))
            data = self.read_live_bytes(offset, length)
            self.append_journal_event(
                "live_read",
                offset=offset,
                length=length,
                sha256=sha256_hex(data),
            )
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "read",
                    "offset": offset,
                    "length": length,
                    "sha256": sha256_hex(data),
                    "encoding": encoding,
                    **encode_binary_payload(data, encoding),
                },
            )
            return

        if action == "write":
            offset = parse_int_value(request.get("offset"), "offset")
            persist = parse_bool_value(request.get("persist"), default=False)
            verify = parse_bool_value(request.get("verify"), default=False)
            data = decode_binary_payload(request)
            before = self.read_live_bytes(offset, len(data))
            result = self.write_live_bytes(offset, data, persist=persist, verify=verify)
            self.append_journal_event(
                "live_write",
                offset=offset,
                length=len(data),
                before_hex=before.hex().upper(),
                data_hex=data.hex().upper(),
                persisted=persist,
                verified=verify,
                sha256=result["sha256"],
            )
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "write",
                    **result,
                },
            )
            return

        if action == "persist":
            result = self.persist_live()
            self.append_journal_event("live_persist", lines=result["lines"])
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "persist",
                    **result,
                },
            )
            return

        if action == "shadow_info":
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "shadow_info",
                    **self.shadow_summary(),
                },
            )
            return

        if action == "shadow_init":
            source = str(request.get("source") or "canonical")
            result = self.initialize_shadow(source)
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "shadow_init",
                    **result,
                },
            )
            return

        if action == "shadow_read":
            offset = parse_int_value(request.get("offset"), "offset")
            length = parse_int_value(request.get("length"), "length")
            encoding = parse_encoding(request.get("encoding"))
            data = self.read_shadow_bytes(offset, length)
            self.append_journal_event(
                "shadow_read",
                offset=offset,
                length=length,
                sha256=sha256_hex(data),
            )
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "shadow_read",
                    "offset": offset,
                    "length": length,
                    "sha256": sha256_hex(data),
                    "encoding": encoding,
                    **encode_binary_payload(data, encoding),
                },
            )
            return

        if action == "shadow_write":
            offset = parse_int_value(request.get("offset"), "offset")
            data = decode_binary_payload(request)
            result = self.write_shadow_bytes(offset, data)
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "shadow_write",
                    **result,
                },
            )
            return

        if action == "shadow_diff":
            base = str(request.get("base") or "canonical")
            limit_spans = max(0, parse_int_value(request.get("limit_spans", 64), "limit_spans"))
            result = self.diff_shadow(base=base, limit_spans=limit_spans)
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "shadow_diff",
                    **result,
                },
            )
            return

        if action == "shadow_promote":
            persist = parse_bool_value(request.get("persist"), default=False)
            verify = parse_bool_value(request.get("verify"), default=True)
            result = self.promote_shadow(persist=persist, verify=verify)
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "shadow_promote",
                    **result,
                },
            )
            return

        if action == "rollback_live":
            persist = parse_bool_value(request.get("persist"), default=False)
            verify = parse_bool_value(request.get("verify"), default=True)
            result = self.rollback_live_window(persist=persist, verify=verify)
            self.write_json_line(
                conn,
                {
                    "ok": True,
                    "action": "rollback_live",
                    **result,
                },
            )
            return

        if action in {"stream", "stream_binary"}:
            offset = parse_int_value(request.get("offset"), "offset")
            length = parse_int_value(request.get("length"), "length")
            encoding = parse_encoding(request.get("encoding"))
            interval_ms = max(25, parse_int_value(request.get("interval_ms", 1000), "interval_ms"))
            iterations = parse_int_value(request.get("iterations", request.get("count", 0)), "iterations")
            self.append_journal_event(
                "stream_started",
                offset=offset,
                length=length,
                encoding=encoding,
                interval_ms=interval_ms,
                iterations=iterations,
            )
            self.stream_live_binary(
                conn,
                offset=offset,
                length=length,
                encoding=encoding,
                interval_ms=interval_ms,
                iterations=iterations,
            )
            return

        raise ValueError(f"unsupported action: {action or '<missing>'}")

    def stream_live_binary(
        self,
        conn: socket.socket,
        *,
        offset: int,
        length: int,
        encoding: str,
        interval_ms: int,
        iterations: int,
    ) -> None:
        self.validate_range(offset, length)
        last_sha256 = ""
        self.write_json_line(
            conn,
            {
                "ok": True,
                "action": "stream",
                "type": "stream_start",
                "offset": offset,
                "length": length,
                "encoding": encoding,
                "interval_ms": interval_ms,
                "iterations": iterations,
            },
        )
        sequence = 0
        while True:
            if iterations > 0 and sequence >= iterations:
                break
            data = self.read_live_bytes(offset, length)
            sequence += 1
            frame = {
                "ok": True,
                "action": "stream",
                "type": "stream_chunk",
                "sequence": sequence,
                "timestamp": iso_timestamp(time.time()),
                "offset": offset,
                "length": length,
                "encoding": encoding,
                "sha256": sha256_hex(data),
                **encode_binary_payload(data, encoding),
            }
            last_sha256 = str(frame["sha256"])
            self.write_json_line(conn, frame)
            if iterations > 0 and sequence >= iterations:
                break
            time.sleep(interval_ms / 1000.0)
        self.append_journal_event(
            "stream_completed",
            offset=offset,
            length=length,
            encoding=encoding,
            count=sequence,
            last_sha256=last_sha256,
        )
        self.write_json_line(
            conn,
            {
                "ok": True,
                "action": "stream",
                "type": "stream_end",
                "count": sequence,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.path.join("vm", "com1.sock"))
    parser.add_argument("--control-socket", default=str(DEFAULT_CONTROL_SOCKET_PATH))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--ledger-path", default=str(DEFAULT_LEDGER_PATH))
    parser.add_argument("--journal-path", default=str(DEFAULT_JOURNAL_PATH))
    parser.add_argument("--shadow-path", default=str(DEFAULT_SHADOW_PATH))
    parser.add_argument("--shadow-meta-path", default=str(DEFAULT_SHADOW_META_PATH))
    parser.add_argument("--rollback-path", default=str(DEFAULT_ROLLBACK_PATH))
    parser.add_argument("--transport-window-bytes", type=int, default=DEFAULT_TRANSPORT_WINDOW_BYTES)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--max-output-tokens", type=int, default=int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "160")))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "90")))
    parser.add_argument("--instructions", default=DEFAULT_SYSTEM_PROMPT)
    args = parser.parse_args()

    config = build_config(args)
    state_path = Path(args.state_path)
    ledger_path = Path(args.ledger_path)
    journal_path = Path(args.journal_path)
    shadow_path = Path(args.shadow_path)
    shadow_meta_path = Path(args.shadow_meta_path)
    rollback_path = Path(args.rollback_path)
    control_socket_path = Path(args.control_socket)
    transport_window_bytes = args.transport_window_bytes
    if transport_window_bytes <= 0:
        raise ValueError("--transport-window-bytes must be positive")

    initial_state = load_state(state_path, start_balance_usd=config.drip_start_usd)
    log_startup(
        config,
        state=initial_state,
        ledger_path=ledger_path,
        control_socket_path=control_socket_path,
        journal_path=journal_path,
        shadow_path=shadow_path,
        shadow_meta_path=shadow_meta_path,
        transport_window_bytes=transport_window_bytes,
    )

    server = KernelBridgeServer(
        serial_socket_path=args.socket,
        control_socket_path=control_socket_path,
        state_path=state_path,
        ledger_path=ledger_path,
        journal_path=journal_path,
        shadow_path=shadow_path,
        shadow_meta_path=shadow_meta_path,
        rollback_path=rollback_path,
        transport_window_bytes=transport_window_bytes,
        config=config,
    )
    server.state = initial_state
    server.start()
    server.wait_forever()


if __name__ == "__main__":
    main()
