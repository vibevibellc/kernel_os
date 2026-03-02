#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VM_DIR = ROOT / "vm"
SOCKET_PATH = VM_DIR / "relay-smoke.sock"
TRANSCRIPT_PATH = VM_DIR / "relay-smoke-transcript.log"
DISK_COPY_PATH = VM_DIR / "relay-smoke-disk.img"
NL = r"\r+\n"


class SmokeFailure(RuntimeError):
    pass


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RelayWebhookHandler(BaseHTTPRequestHandler):
    server: "RelayWebhookServer"

    def log_message(self, _format: str, *args) -> None:
        self.server.append_log("http", " ".join(str(arg) for arg in args))

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        payload = self._read_json()
        self.server.append_request(self.path, payload)

        if self.path == "/chat":
            prompt = str(payload.get("prompt", ""))
            session = str(payload.get("session", "relay-smoke"))
            content = self.server.chat_reply_for_prompt(prompt)
            response = {
                "content": content,
                "kernel_command": "ramlist" if content == "ramlist" else None,
                "session": session,
                "retired": False,
                "retired_reason": "",
                "steps": len(self.server.chat_requests),
            }
            self._write_json(response)
            return

        if self.path == "/host":
            action = str(payload.get("action", ""))
            session = str(payload.get("session", "relay-smoke"))
            if action == "retire-session":
                self._write_json(
                    {
                        "action": action,
                        "session": session,
                        "message": f"retired {session}",
                        "retired": True,
                        "retired_reason": "host-request",
                    }
                )
                return

            self._write_json({"action": action, "message": "ok"})
            return

        self._write_json({"error": f"unknown path {self.path}"}, status=404)


class RelayWebhookServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, RelayWebhookHandler)
        self.chat_requests: list[dict] = []
        self.host_requests: list[dict] = []
        self.logs: list[str] = []

    def append_request(self, path: str, payload: dict) -> None:
        if path == "/chat":
            self.chat_requests.append(payload)
            return
        if path == "/host":
            self.host_requests.append(payload)

    def append_log(self, kind: str, message: str) -> None:
        self.logs.append(f"{kind}: {message}")

    def chat_reply_for_prompt(self, prompt: str) -> str:
        match = re.match(r"^Relay (\d+)/(\d+)( final)?\.", prompt)
        if match:
            index = int(match.group(1))
            total = int(match.group(2))
            if index < total:
                return f"Chunk {index}/{total} stored. Waiting for more."
            return "ramlist"
        return "waiting for more"


class SupervisorRelaySmoke:
    def __init__(self) -> None:
        self.qemu: subprocess.Popen[str] | None = None
        self.supervisor: subprocess.Popen[bytes] | None = None
        self.master_fd: int | None = None
        self.webhook: RelayWebhookServer | None = None
        self.webhook_thread: threading.Thread | None = None
        self.transcript = ""
        self.cursor = 0

    def run(self) -> None:
        self.build_disk()
        self.start_webhook()
        self.start_vm()
        self.start_supervisor()
        try:
            self.expect(r"stage2: command monitor ready", timeout=10)
            self.expect(rf"generation 0x[0-9A-F]{{8}}{NL}kernel_os> ", timeout=10)
            self.scenario_long_prompt_relay()
        finally:
            self.save_transcript()
            self.close()

    def build_disk(self) -> None:
        subprocess.run(["make", "boot"], cwd=ROOT, check=True)
        shutil.copyfile(VM_DIR / "os-disk.img", DISK_COPY_PATH)

    def start_webhook(self) -> None:
        port = find_free_port()
        self.webhook = RelayWebhookServer(("127.0.0.1", port))
        self.webhook_thread = threading.Thread(target=self.webhook.serve_forever, daemon=True)
        self.webhook_thread.start()
        self.webhook_port = port

    def start_vm(self) -> None:
        SOCKET_PATH.unlink(missing_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "DISK_PATH": str(DISK_COPY_PATH),
                "SERIAL_MODE": "socket",
                "SERIAL_WAIT": "on",
                "SERIAL_SOCKET": str(SOCKET_PATH),
            }
        )
        self.qemu = subprocess.Popen(
            ["./run-vm.sh", "-display", "none"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def start_supervisor(self) -> None:
        if self.webhook is None:
            raise SmokeFailure("webhook was not started")
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        self.supervisor = subprocess.Popen(
            [
                sys.executable,
                "bridge/supervise_kernel.py",
                "--socket",
                str(SOCKET_PATH),
                "--webhook",
                f"http://127.0.0.1:{self.webhook_port}",
                "--session",
                "relay-smoke",
            ],
            cwd=ROOT,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            text=False,
        )
        os.close(slave_fd)

    def close(self) -> None:
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        if self.supervisor is not None:
            if self.supervisor.poll() is None:
                self.supervisor.terminate()
                try:
                    self.supervisor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.supervisor.kill()
                    self.supervisor.wait(timeout=5)
            self.supervisor = None

        if self.qemu is not None:
            if self.qemu.poll() is None:
                self.qemu.terminate()
                try:
                    self.qemu.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.qemu.kill()
                    self.qemu.wait(timeout=5)
            self.qemu = None

        if self.webhook is not None:
            self.webhook.shutdown()
            self.webhook.server_close()
            self.webhook = None

        if self.webhook_thread is not None:
            self.webhook_thread.join(timeout=2)
            self.webhook_thread = None

        SOCKET_PATH.unlink(missing_ok=True)
        DISK_COPY_PATH.unlink(missing_ok=True)

    def save_transcript(self) -> None:
        VM_DIR.mkdir(parents=True, exist_ok=True)
        TRANSCRIPT_PATH.write_text(self.transcript, encoding="utf-8")

    def ensure_processes_running(self) -> None:
        if self.qemu is None or self.qemu.poll() is not None:
            stderr = ""
            if self.qemu is not None and self.qemu.stderr is not None:
                stderr = self.qemu.stderr.read()
            raise SmokeFailure(f"qemu exited early: {stderr.strip() or 'no stderr output'}")
        if self.supervisor is None or self.supervisor.poll() is not None:
            raise SmokeFailure("supervisor exited early")

    def log(self, message: str) -> None:
        line = f"[relay-smoke] {message}"
        print(line)
        self.transcript += line + "\n"

    def read_into_transcript(self, timeout: float) -> None:
        if self.master_fd is None:
            raise SmokeFailure("supervisor PTY is not connected")
        end = time.time() + timeout
        while time.time() < end:
            self.ensure_processes_running()
            readable, _, _ = select.select([self.master_fd], [], [], 0.1)
            if self.master_fd not in readable:
                continue
            chunk = os.read(self.master_fd, 4096)
            if not chunk:
                raise SmokeFailure("supervisor PTY closed")
            self.transcript += chunk.decode("utf-8", errors="replace")
            return
        raise SmokeFailure("timed out waiting for relay output")

    def read_available(self, duration: float) -> None:
        if self.master_fd is None:
            raise SmokeFailure("supervisor PTY is not connected")
        end = time.time() + duration
        while time.time() < end:
            self.ensure_processes_running()
            readable, _, _ = select.select([self.master_fd], [], [], 0.05)
            if self.master_fd not in readable:
                continue
            chunk = os.read(self.master_fd, 4096)
            if not chunk:
                raise SmokeFailure("supervisor PTY closed")
            self.transcript += chunk.decode("utf-8", errors="replace")

    def expect(self, pattern: str, timeout: float = 5) -> re.Match[str]:
        regex = re.compile(pattern, re.S)
        deadline = time.time() + timeout
        while time.time() < deadline:
            match = regex.search(self.transcript, self.cursor)
            if match:
                self.cursor = match.end()
                return match
            self.read_into_transcript(0.5)
        raise SmokeFailure(f"timed out waiting for pattern: {pattern}")

    def send(self, text: str, *, label: str) -> None:
        if self.master_fd is None:
            raise SmokeFailure("supervisor PTY is not connected")
        self.log(f"send {label}: {text.encode('utf-8').hex()} {text!r}")
        os.write(self.master_fd, text.encode("utf-8"))

    def send_operator_line(self, text: str) -> None:
        self.send(text + "\r", label="operator")

    def expect_chat_prompt(self) -> None:
        self.expect(
            rf"chat: blank line or exit leaves\. command output may feed back automatically\. /loop continues; /kill-self halts\.{NL}chat> ",
            timeout=5,
        )

    def expect_post(self, route: str, timeout: float = 5) -> dict:
        match = self.expect(rf"POST {re.escape(route)} (\{{.*?\}}){NL}", timeout=timeout)
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise SmokeFailure(f"bad json for {route}: {match.group(1)!r}") from exc

    def scenario_long_prompt_relay(self) -> None:
        self.log("scenario long prompt relay")
        self.send_operator_line("chat")
        self.expect_chat_prompt()

        prompt = (
            "This is a long relay smoke request that must exceed the kernel input line limit so the supervisor "
            "has to split it into several chat turns while preserving meaning across the entire sequence. "
            "Keep every relay chunk in memory and do not act until the final relay chunk arrives. "
            "Once the final chunk arrives, reply with exactly /ramlist and nothing else so the running kernel "
            "enters the renamed RAM list program."
        )
        self.send_operator_line(prompt)

        split_match = self.expect(rf"\[split long chat prompt into ([0-9]+) turns\]{NL}", timeout=5)
        relay_turns = int(split_match.group(1))
        if relay_turns < 2:
            raise SmokeFailure(f"expected relay splitting, got only {relay_turns} turns")

        for index in range(1, relay_turns + 1):
            payload = self.expect_post("/chat", timeout=8)
            payload_prompt = str(payload.get("prompt", ""))
            if len(payload_prompt) > 255:
                raise SmokeFailure(f"relay prompt exceeded kernel limit: {len(payload_prompt)}")
            if index == 1 and payload.get("fresh_chat") is not True:
                raise SmokeFailure(f"first relay turn should be fresh_chat=true: {payload}")
            if index > 1 and payload.get("fresh_chat"):
                raise SmokeFailure(f"relay continuation unexpectedly set fresh_chat on turn {index}: {payload}")
            if index < relay_turns:
                expected_prefix = f"Relay {index}/{relay_turns}."
            else:
                expected_prefix = f"Relay {index}/{relay_turns} final."
            if not payload_prompt.startswith(expected_prefix):
                raise SmokeFailure(f"unexpected relay prompt prefix on turn {index}: {payload_prompt!r}")

        self.expect(rf"AI requested command: ramlist{NL}", timeout=8)
        self.expect(rf"ramlist: push, pop, show, clear, exit{NL}ramlist> ", timeout=5)
        checkpoint = len(self.transcript)
        self.read_available(0.3)
        if "POST /chat " in self.transcript[checkpoint:]:
            raise SmokeFailure("interactive ramlist unexpectedly triggered another chat request")

        self.send_operator_line("exit")
        self.expect(rf"leaving ramlist{NL}chat> ", timeout=5)

        self.send_operator_line("")
        payload = self.expect_post("/host", timeout=5)
        if payload.get("action") != "retire-session":
            raise SmokeFailure(f"expected retire-session on chat exit, got {payload}")

        self.expect(rf"leaving chat{NL}kernel_os> ", timeout=5)

        if self.webhook is None or len(self.webhook.chat_requests) != relay_turns:
            raise SmokeFailure("fake webhook did not record the expected relay chat requests")


def main() -> int:
    smoke = SupervisorRelaySmoke()
    try:
        smoke.run()
    except (OSError, SmokeFailure, subprocess.CalledProcessError) as exc:
        print(f"vm supervisor relay smoke failed: {exc}", file=sys.stderr)
        print(f"transcript saved to {TRANSCRIPT_PATH}", file=sys.stderr)
        return 1

    print("vm supervisor relay smoke passed")
    print(f"transcript saved to {TRANSCRIPT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
