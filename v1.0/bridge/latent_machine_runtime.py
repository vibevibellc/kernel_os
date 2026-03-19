#!/usr/bin/env python3
from __future__ import annotations

import atexit
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from live_patch_persistence import _parse_listing, parse_peek_observation


ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.getenv("LATENT_MACHINE_STATE_DIR", str(ROOT / "vm" / "latent-machine")))
MODEL_PATH = STATE_DIR / "machine_model.json"
RUNTIME_LOG_PATH = STATE_DIR / "runtime_state.jsonl"
OBSERVATION_LOG_PATH = STATE_DIR / "observations.jsonl"
TURN_LOG_PATH = STATE_DIR / "turns.jsonl"
TRAINER_STATUS_PATH = STATE_DIR / "trainer_status.json"
STAGE2_SOURCE_PATH = ROOT / "boot" / "stage2.asm"
DEFAULT_NASM = os.getenv("NASM_BIN", "nasm")
HEX_OFFSET_PATTERN = re.compile(r"0x([0-9a-fA-F]{1,8})")
HEX_BYTE_PATTERN = re.compile(r"\b([0-9A-Fa-f]{2})\b")
WORD_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_-]{2,}")
COMMAND_PATTERN = re.compile(r"^/(peekpage|peek|stream|patch)\b.*$")
MAX_RECENT_RECORDS = 64
MAX_SNIPPETS = 512
MAX_ADVISORY_LINES = 4
DEFAULT_CPU_DUTY_CYCLE = 0.2
DEFAULT_GPU_DUTY_CYCLE = 0.2
DEFAULT_CYCLE_SECONDS = 1.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_duty_cycle(value: float, default: float = 0.2) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def compact_text(text: str, limit: int = 220) -> str:
    compact = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def extract_keywords(text: str) -> set[str]:
    return {match.group(0).lower() for match in WORD_PATTERN.finditer(text or "")}


def extract_offsets(text: str) -> set[int]:
    return {int(match.group(1), 16) for match in HEX_OFFSET_PATTERN.finditer(text or "")}


def extract_hex_bytes(text: str) -> set[str]:
    return {match.group(1).upper() for match in HEX_BYTE_PATTERN.finditer(text or "")}


def command_kind(text: str) -> str:
    match = COMMAND_PATTERN.match((text or "").strip())
    if not match:
        return ""
    return match.group(1)


def recommend_command_kind(machine_brief: str, conversation_text: str) -> str:
    combined = " ".join((machine_brief or "", conversation_text or "")).lower()
    if not combined:
        return "/peek"
    if any(term in combined for term in ("bios", "video mode", "register", "port ", "port-", "hardware", "live probe")):
        return "/stream"
    if any(term in combined for term in ("patch", "edit", "modify", "change", "fix", "rewrite")):
        if "peek 0x" in combined:
            return "/patch"
        return "/peek"
    if any(term in combined for term in ("page walk", "walk memory", "peekpage")):
        return "/peekpage"
    return "/peek"


def score_text_match(*, keywords: set[str], haystack: str) -> int:
    if not keywords or not haystack:
        return 0
    lowered = haystack.lower()
    return sum(3 for keyword in keywords if keyword in lowered)


class LatentMachineRuntime:
    def __init__(
        self,
        *,
        repo_root: Path = ROOT,
        state_dir: Path = STATE_DIR,
        enabled: bool | None = None,
        autostart: bool = True,
    ) -> None:
        self.repo_root = repo_root
        self.state_dir = state_dir
        self.enabled = (os.getenv("LATENT_MACHINE_ENABLED", "1") == "1") if enabled is None else bool(enabled)
        self.cpu_duty_cycle = clamp_duty_cycle(
            os.getenv("LATENT_MACHINE_CPU_DUTY_CYCLE", str(DEFAULT_CPU_DUTY_CYCLE)),
            DEFAULT_CPU_DUTY_CYCLE,
        )
        self.gpu_duty_cycle = clamp_duty_cycle(
            os.getenv("LATENT_MACHINE_GPU_DUTY_CYCLE", str(DEFAULT_GPU_DUTY_CYCLE)),
            DEFAULT_GPU_DUTY_CYCLE,
        )
        self.cycle_seconds = max(
            0.25,
            float(os.getenv("LATENT_MACHINE_CYCLE_SECONDS", str(DEFAULT_CYCLE_SECONDS))),
        )
        self.nasm_bin = os.getenv("NASM_BIN", DEFAULT_NASM)
        self.external_train_command = os.getenv("LATENT_MACHINE_EXTERNAL_TRAIN_COMMAND", "").strip()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.runtime_state = "busy"
        self.last_runtime_transition_at = utc_now()
        self.model_snapshot: dict = self._load_model_snapshot()
        self.last_revision = ""
        self.external_process: subprocess.Popen | None = None
        self.external_process_stopped = False
        self.worker: threading.Thread | None = None
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._write_status("initialized")
        if self.enabled and autostart:
            self.worker = threading.Thread(target=self._training_loop, name="latent-machine-runtime", daemon=True)
            self.worker.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=2.0)
        self._stop_external_process()
        self._write_status("stopped")

    def note_runtime_state(self, state: str) -> dict:
        normalized = (state or "").strip().lower()
        if normalized not in {"latent", "busy"}:
            raise ValueError(f"unsupported runtime state '{state}'")

        transition = False
        with self.lock:
            if self.runtime_state != normalized:
                self.runtime_state = normalized
                self.last_runtime_transition_at = utc_now()
                transition = True

        payload = {
            "ts": utc_now(),
            "state": normalized,
            "transition": transition,
        }
        self._append_jsonl(RUNTIME_LOG_PATH, payload)
        if normalized != "latent":
            self._pause_external_process()
        self._write_status("runtime-state")
        return {
            "state": normalized,
            "transition": transition,
            "duty_cycle_cpu": self.cpu_duty_cycle,
            "duty_cycle_gpu": self.gpu_duty_cycle,
        }

    def note_observation(
        self,
        *,
        session: str,
        kind: str,
        origin: str,
        observation: str,
    ) -> None:
        payload = {
            "ts": utc_now(),
            "session": compact_text(session, 64),
            "kind": compact_text(kind, 32),
            "origin": compact_text(origin, 160),
            "observation": compact_text(observation, 320),
        }
        self._append_jsonl(OBSERVATION_LOG_PATH, payload)

    def note_model_turn(
        self,
        *,
        session: str,
        user_messages: list[dict],
        response: str,
        generation: str = "",
    ) -> None:
        joined_prompt = "\n".join(
            compact_text(str(message.get("content", "")), 320)
            for message in user_messages
            if message.get("role") == "user"
        )
        payload = {
            "ts": utc_now(),
            "session": compact_text(session, 64),
            "generation": compact_text(generation, 24),
            "prompt": joined_prompt,
            "response": compact_text(response, 320),
            "command_kind": command_kind(response),
        }
        self._append_jsonl(TURN_LOG_PATH, payload)

    def advisory_for(
        self,
        *,
        machine_brief: str,
        conversation: list[dict],
        generation: str = "",
    ) -> str:
        snapshot = self._get_model_snapshot()
        if not snapshot:
            return ""

        conversation_tail = "\n".join(
            compact_text(str(message.get("content", "")), 240)
            for message in conversation[-8:]
        )
        keywords = extract_keywords(machine_brief) | extract_keywords(conversation_tail)
        offsets = extract_offsets(machine_brief) | extract_offsets(conversation_tail)
        byte_tokens = extract_hex_bytes(machine_brief) | extract_hex_bytes(conversation_tail)
        recommended = recommend_command_kind(machine_brief, conversation_tail)

        scored_snippets = []
        for snippet in snapshot.get("snippets", []):
            score = 0
            if snippet.get("offset") in offsets:
                score += 100
            score += score_text_match(
                keywords=keywords,
                haystack=" ".join(
                    (
                        str(snippet.get("source_path", "")),
                        str(snippet.get("line_text", "")),
                    )
                ),
            )
            if byte_tokens:
                snippet_bytes = set(str(snippet.get("bytes", "")).split())
                score += sum(2 for token in byte_tokens if token in snippet_bytes)
            if score > 0:
                scored_snippets.append((score, snippet))
        scored_snippets.sort(key=lambda item: item[0], reverse=True)

        scored_examples = []
        for example in snapshot.get("command_examples", []):
            score = score_text_match(
                keywords=keywords,
                haystack=" ".join(
                    (
                        str(example.get("prompt", "")),
                        str(example.get("response", "")),
                    )
                ),
            )
            if example.get("command_kind") == recommended.lstrip("/"):
                score += 6
            if score > 0:
                scored_examples.append((score, example))
        scored_examples.sort(key=lambda item: item[0], reverse=True)

        scored_observations = []
        for observation in snapshot.get("observation_examples", []):
            score = score_text_match(
                keywords=keywords,
                haystack=" ".join(
                    (
                        str(observation.get("origin", "")),
                        str(observation.get("observation", "")),
                    )
                ),
            )
            if offsets:
                try:
                    observed_offset, _ = parse_peek_observation(str(observation.get("observation", "")))
                except ValueError:
                    observed_offset = -1
                if observed_offset in offsets:
                    score += 80
            if score > 0:
                scored_observations.append((score, observation))
        scored_observations.sort(key=lambda item: item[0], reverse=True)

        lines = [
            (
                "Local machine-code advisor: "
                f"recommended={recommended} epoch={snapshot.get('epoch', 0)} "
                f"cpu={int(self.cpu_duty_cycle * 100)}% gpu={int(self.gpu_duty_cycle * 100)}%"
            )
        ]
        if generation:
            lines.append(f"Kernel generation: {generation}")
        if scored_snippets:
            snippet = scored_snippets[0][1]
            lines.append(
                "Code hit: "
                f"offset=0x{int(snippet['offset']):04X} "
                f"{snippet['source_path']}:{snippet['line_number']} "
                f"bytes={snippet['bytes']}"
            )
        if scored_observations:
            observation = scored_observations[0][1]
            lines.append(
                "Observation hit: "
                f"{observation.get('origin', '')} -> {observation.get('observation', '')}"
            )
        if scored_examples:
            example = scored_examples[0][1]
            lines.append(
                "Similar accepted turn: "
                f"{example.get('response', '')} "
                f"(prompt={example.get('prompt', '')})"
            )
        return "\n".join(lines[:MAX_ADVISORY_LINES])

    def status(self) -> dict:
        snapshot = self._get_model_snapshot()
        with self.lock:
            runtime_state = self.runtime_state
            last_transition = self.last_runtime_transition_at
            external_pid = self.external_process.pid if self.external_process and self.external_process.poll() is None else 0
        return {
            "enabled": self.enabled,
            "runtime_state": runtime_state,
            "last_runtime_transition_at": last_transition,
            "epoch": snapshot.get("epoch", 0) if snapshot else 0,
            "reinforcement_passes": snapshot.get("reinforcement_passes", 0) if snapshot else 0,
            "entry_count": snapshot.get("entry_count", 0) if snapshot else 0,
            "cpu_duty_cycle": self.cpu_duty_cycle,
            "gpu_duty_cycle": self.gpu_duty_cycle,
            "external_trainer_pid": external_pid,
            "external_trainer_command": self.external_train_command,
            "model_path": str(MODEL_PATH),
        }

    def _training_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                runtime_state = self.runtime_state
            if runtime_state != "latent":
                self.stop_event.wait(0.1)
                continue

            active_window = self.cycle_seconds * min(self.cpu_duty_cycle, self.gpu_duty_cycle)
            cycle_started = time.monotonic()
            if active_window > 0:
                deadline = cycle_started + active_window
                if self.external_train_command:
                    self._refresh_snapshot()
                    self._resume_external_process()
                    self._sleep_until(deadline)
                    self._pause_external_process()
                else:
                    while time.monotonic() < deadline and not self.stop_event.is_set():
                        with self.lock:
                            if self.runtime_state != "latent":
                                break
                        self._refresh_snapshot()
                        break
            cycle_elapsed = time.monotonic() - cycle_started
            rest_window = max(0.0, self.cycle_seconds - cycle_elapsed)
            if rest_window > 0:
                self.stop_event.wait(rest_window)

    def _refresh_snapshot(self) -> None:
        source_revision = self._source_revision()
        current = self._get_model_snapshot()
        if current and current.get("source_revision") == source_revision:
            refreshed = dict(current)
            refreshed["epoch"] = int(refreshed.get("epoch", 0)) + 1
            refreshed["reinforcement_passes"] = int(refreshed.get("reinforcement_passes", 0)) + 1
            refreshed["updated_at"] = utc_now()
            self._set_model_snapshot(refreshed)
            return

        snapshot = self._build_snapshot(source_revision)
        self._set_model_snapshot(snapshot)

    def _build_snapshot(self, source_revision: str) -> dict:
        entries = self._assemble_listing_entries()
        source_lines: dict[Path, list[str]] = {}
        snippets = []
        for entry in entries[:MAX_SNIPPETS]:
            lines = source_lines.setdefault(
                entry.source_path,
                entry.source_path.read_text(encoding="utf-8").splitlines(),
            )
            line_text = lines[entry.line_number - 1] if 0 < entry.line_number <= len(lines) else ""
            snippets.append(
                {
                    "offset": int(entry.offset),
                    "source_path": entry.source_path.resolve().relative_to(self.repo_root.resolve()).as_posix(),
                    "line_number": int(entry.line_number),
                    "bytes": " ".join(f"{value:02X}" for value in entry.data[:16]),
                    "line_text": compact_text(line_text, 180),
                }
            )

        observation_examples = self._load_jsonl_tail(OBSERVATION_LOG_PATH, MAX_RECENT_RECORDS)
        command_examples = self._load_jsonl_tail(TURN_LOG_PATH, MAX_RECENT_RECORDS)
        current = self._get_model_snapshot()
        epoch = int(current.get("epoch", 0)) + 1 if current else 1
        reinforcement = int(current.get("reinforcement_passes", 0)) + 1 if current else 1

        return {
            "updated_at": utc_now(),
            "source_revision": source_revision,
            "epoch": epoch,
            "reinforcement_passes": reinforcement,
            "entry_count": len(entries),
            "snippets": snippets,
            "observation_examples": observation_examples,
            "command_examples": command_examples,
        }

    def _assemble_listing_entries(self):
        with tempfile.TemporaryDirectory(prefix="latent-machine-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            listing_path = temp_dir / "stage2.lst"
            bin_path = temp_dir / "stage2.bin"
            subprocess.run(
                [self.nasm_bin, "-I", ".", "-f", "bin", "-l", str(listing_path), "-o", str(bin_path), str(STAGE2_SOURCE_PATH)],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            return _parse_listing(listing_path, self.repo_root, STAGE2_SOURCE_PATH.resolve())

    def _source_revision(self) -> str:
        parts = []
        for path in sorted((self.repo_root / "boot").rglob("*.asm")):
            stat = path.stat()
            parts.append(f"{path.relative_to(self.repo_root)}:{int(stat.st_mtime_ns)}:{stat.st_size}")
        for extra_path in (OBSERVATION_LOG_PATH, TURN_LOG_PATH):
            if extra_path.exists():
                stat = extra_path.stat()
                parts.append(f"{extra_path.name}:{int(stat.st_mtime_ns)}:{stat.st_size}")
        return "|".join(parts)

    def _load_model_snapshot(self) -> dict:
        if not MODEL_PATH.exists():
            return {}
        try:
            return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _get_model_snapshot(self) -> dict:
        with self.lock:
            return dict(self.model_snapshot)

    def _set_model_snapshot(self, snapshot: dict) -> None:
        with self.lock:
            self.model_snapshot = dict(snapshot)
        MODEL_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        self._write_status("snapshot")

    def _append_jsonl(self, path: Path, payload: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _load_jsonl_tail(self, path: Path, limit: int) -> list[dict]:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        records = []
        for raw_line in lines[-limit:]:
            try:
                parsed = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    def _write_status(self, reason: str) -> None:
        TRAINER_STATUS_PATH.write_text(
            json.dumps(
                {
                    "ts": utc_now(),
                    "reason": reason,
                    **self.status(),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _sleep_until(self, deadline: float) -> None:
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.stop_event.wait(min(0.05, remaining))

    def _ensure_external_process(self) -> None:
        if not self.external_train_command:
            return
        if self.external_process and self.external_process.poll() is None:
            return
        self.external_process = subprocess.Popen(
            self.external_train_command if isinstance(self.external_train_command, str) else shlex.split(self.external_train_command),
            cwd=self.repo_root,
            shell=isinstance(self.external_train_command, str),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.external_process_stopped = False

    def _pause_external_process(self) -> None:
        process = self.external_process
        if process is None or process.poll() is not None or self.external_process_stopped:
            return
        try:
            os.killpg(process.pid, signal.SIGSTOP)
            self.external_process_stopped = True
        except OSError:
            self.external_process = None
            self.external_process_stopped = False

    def _resume_external_process(self) -> None:
        self._ensure_external_process()
        process = self.external_process
        if process is None or process.poll() is not None:
            return
        if self.external_process_stopped:
            try:
                os.killpg(process.pid, signal.SIGCONT)
                self.external_process_stopped = False
            except OSError:
                self.external_process = None
                self.external_process_stopped = False

    def _stop_external_process(self) -> None:
        process = self.external_process
        if process is None:
            return
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.external_process = None
        self.external_process_stopped = False


LATENT_MACHINE_RUNTIME = LatentMachineRuntime()
atexit.register(LATENT_MACHINE_RUNTIME.close)
