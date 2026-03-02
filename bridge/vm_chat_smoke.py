#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VM_DIR = ROOT / "vm"
SOCKET_PATH = VM_DIR / "chat-smoke.sock"
TRANSCRIPT_PATH = VM_DIR / "chat-smoke-transcript.log"
DISK_COPY_PATH = VM_DIR / "chat-smoke-disk.img"


class SmokeFailure(RuntimeError):
    pass


class VMChatSmoke:
    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.qemu: subprocess.Popen[str] | None = None
        self.transcript = ""
        self.cursor = 0
        self.generation = "0x00000001"

    def run(self) -> None:
        self.build_disk()
        self.start_vm()
        try:
            self.connect_socket()
            self.expect(r"stage2: command monitor ready", timeout=10)
            self.expect(r"generation 0x[0-9A-F]{8}\r\nkernel_os> ", timeout=10)
            generation_match = re.search(r"generation (0x[0-9A-F]{8})", self.transcript)
            if generation_match:
                self.generation = generation_match.group(1)

            self.scenario_chat_context_persistence()
            self.scenario_peekpage()
            self.scenario_edit()
            self.scenario_loop()
            self.scenario_patch()
            self.scenario_stream()
            self.scenario_kill_self()
        finally:
            self.save_transcript()
            self.close()

    def build_disk(self) -> None:
        subprocess.run(["make", "boot"], cwd=ROOT, check=True)
        shutil.copyfile(VM_DIR / "os-disk.img", DISK_COPY_PATH)

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

    def connect_socket(self) -> None:
        for _ in range(80):
            if SOCKET_PATH.exists():
                break
            self.ensure_qemu_running()
            time.sleep(0.1)
        else:
            raise SmokeFailure(f"serial socket {SOCKET_PATH} was not created")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        for _ in range(20):
            try:
                sock.connect(str(SOCKET_PATH))
                sock.setblocking(False)
                self.sock = sock
                return
            except OSError:
                self.ensure_qemu_running()
                time.sleep(0.1)
        raise SmokeFailure(f"failed to connect to {SOCKET_PATH}")

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

        if self.qemu is not None:
            if self.qemu.poll() is None:
                self.qemu.terminate()
                try:
                    self.qemu.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.qemu.kill()
                    self.qemu.wait(timeout=5)
            self.qemu = None

        DISK_COPY_PATH.unlink(missing_ok=True)

    def ensure_qemu_running(self) -> None:
        if self.qemu is None:
            raise SmokeFailure("qemu was not started")
        if self.qemu.poll() is not None:
            stderr = ""
            if self.qemu.stderr is not None:
                stderr = self.qemu.stderr.read()
            raise SmokeFailure(f"qemu exited early: {stderr.strip() or 'no stderr output'}")

    def save_transcript(self) -> None:
        VM_DIR.mkdir(parents=True, exist_ok=True)
        TRANSCRIPT_PATH.write_text(self.transcript, encoding="utf-8")

    def log(self, message: str) -> None:
        line = f"[smoke] {message}"
        print(line)
        self.transcript += line + "\n"

    def read_into_transcript(self, timeout: float) -> None:
        if self.sock is None:
            raise SmokeFailure("socket is not connected")

        end = time.time() + timeout
        while time.time() < end:
            self.ensure_qemu_running()
            readable, _, _ = select.select([self.sock], [], [], 0.1)
            if self.sock not in readable:
                continue
            chunk = self.sock.recv(4096)
            if not chunk:
                raise SmokeFailure("serial socket closed")
            self.transcript += chunk.decode("utf-8", errors="replace")
            return
        raise SmokeFailure("timed out waiting for serial output")

    def read_available(self, duration: float) -> None:
        if self.sock is None:
            raise SmokeFailure("socket is not connected")
        end = time.time() + duration
        while time.time() < end:
            self.ensure_qemu_running()
            readable, _, _ = select.select([self.sock], [], [], 0.05)
            if self.sock not in readable:
                continue
            chunk = self.sock.recv(4096)
            if not chunk:
                raise SmokeFailure("serial socket closed")
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
        if self.sock is None:
            raise SmokeFailure("socket is not connected")
        self.log(f"send {label}: {text.encode('utf-8').hex()} {text!r}")
        self.sock.sendall(text.encode("utf-8"))

    def send_operator_line(self, text: str) -> None:
        self.send(text + "\r", label="operator")

    def send_host_line(self, text: str) -> None:
        self.send(text + "\r", label="host")

    def expect_post(self, route: str, timeout: float = 5) -> dict:
        match = self.expect(rf"POST {re.escape(route)} (\{{.*?\}})\r\n", timeout=timeout)
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise SmokeFailure(f"bad json for {route}: {match.group(1)!r}") from exc

    def enter_chat(self) -> None:
        self.send_operator_line("chat")
        self.expect(
            r"chat: blank line or exit leaves\. command output may feed back automatically\. /loop continues; /kill-self halts\.\r\n",
            timeout=5,
        )
        self.expect(r"chat> ", timeout=5)

    def expect_auto_continue(self, session: str, timeout: float = 5) -> dict:
        self.expect(r"chat: continuing with host using the latest command output\.\.\.\r\n", timeout=timeout)
        payload = self.expect_post("/chat", timeout=timeout)
        if payload.get("session") != session:
            raise SmokeFailure(f"auto-continue changed sessions: expected {session!r}, got {payload}")
        if payload.get("loop") is not True:
            raise SmokeFailure(f"auto-continue payload missing loop=true: {payload}")
        if payload.get("generation") != self.generation:
            raise SmokeFailure(
                f"expected generation {self.generation} in auto-continue payload, got {payload.get('generation')}"
            )
        return payload

    def exit_chat(self) -> None:
        self.send_operator_line("")
        payload = self.expect_post("/host", timeout=5)
        if payload.get("action") != "retire-session":
            raise SmokeFailure(f"expected retire-session on chat exit, got {payload}")
        self.send_host_line("AI: retired")
        self.expect(r"leaving chat\r\nkernel_os> ", timeout=5)

    def start_chat_turn(
        self,
        prompt: str,
        *,
        expect_fresh: bool | None = None,
        expected_session: str | None = None,
        forbid_retire_before_chat: bool = False,
    ) -> dict:
        self.send_operator_line(prompt)
        self.expect(r"waiting for host response\.\.\.\r\n", timeout=5)
        checkpoint = self.cursor
        payload = self.expect_post("/chat", timeout=5)
        segment = self.transcript[checkpoint:self.cursor]
        if forbid_retire_before_chat and 'POST /host {"action":"retire-session"' in segment:
            raise SmokeFailure(f"unexpected retire-session before chat prompt {prompt!r}")
        if payload.get("prompt") != prompt:
            raise SmokeFailure(f"unexpected prompt payload: {payload}")
        if payload.get("generation") != self.generation:
            raise SmokeFailure(
                f"expected generation {self.generation} in chat payload, got {payload.get('generation')}"
            )
        if expect_fresh is not None and bool(payload.get("fresh_chat")) != expect_fresh:
            raise SmokeFailure(f"expected fresh_chat={expect_fresh} for {prompt!r}, got {payload}")
        if expected_session is not None and payload.get("session") != expected_session:
            raise SmokeFailure(f"expected session {expected_session!r}, got {payload}")
        return payload

    def scenario_chat_context_persistence(self) -> None:
        self.log("scenario chat context persistence")
        self.enter_chat()
        first_payload = self.start_chat_turn("peek smoke", expect_fresh=True)
        self.send_host_line("CMD: /peek 0000 10")
        self.expect(r"AI requested command: /peek 0000 10\r\n", timeout=5)
        match = self.expect(r"peek 0x0000: ([0-9A-F]{2}(?: [0-9A-F]{2}){15})\r\n", timeout=5)
        if len(match.group(1).split()) != 16:
            raise SmokeFailure("peek did not return 16 bytes")
        self.expect_auto_continue(first_payload["session"])
        self.send_host_line("AI: initial peek captured")
        self.expect(r"AI: initial peek captured\r\nchat> ", timeout=5)
        second_payload = self.start_chat_turn(
            "make an edit to it",
            expect_fresh=False,
            expected_session=first_payload["session"],
            forbid_retire_before_chat=True,
        )
        if second_payload.get("session") != first_payload.get("session"):
            raise SmokeFailure("chat context did not stay on the same session")
        self.send_host_line("AI: edit context preserved")
        self.expect(r"AI: edit context preserved\r\nchat> ", timeout=5)
        self.exit_chat()

    def scenario_peekpage(self) -> None:
        self.log("scenario peekpage")
        self.enter_chat()
        first_payload = self.start_chat_turn("pagination smoke", expect_fresh=True)
        self.send_host_line("CMD: /peekpage 0000 0000")
        self.expect(r"AI requested command: /peekpage 0000 0000\r\n", timeout=5)
        match = self.expect(r"peek 0x0000: ([0-9A-F]{2}(?: [0-9A-F]{2}){199})\r\n", timeout=8)
        if len(match.group(1).split()) != 200:
            raise SmokeFailure("peekpage did not return a full 0xC8-byte page")
        self.expect_auto_continue(first_payload["session"])
        self.send_host_line("CMD: /peekpage 0000 0001")
        self.expect(r"AI requested command: /peekpage 0000 0001\r\n", timeout=5)
        match = self.expect(r"peek 0x00C8: ([0-9A-F]{2}(?: [0-9A-F]{2}){199})\r\n", timeout=8)
        if len(match.group(1).split()) != 200:
            raise SmokeFailure("second peekpage did not return a full 0xC8-byte page")
        self.expect_auto_continue(first_payload["session"])
        self.send_host_line("CMD: /peekpage 0000 0002")
        self.expect(r"AI requested command: /peekpage 0000 0002\r\n", timeout=5)
        match = self.expect(r"peek 0x0190: ([0-9A-F]{2}(?: [0-9A-F]{2}){199})\r\n", timeout=8)
        if len(match.group(1).split()) != 200:
            raise SmokeFailure("third peekpage did not return a full 0xC8-byte page")
        self.expect_auto_continue(first_payload["session"])
        self.send_host_line("AI: pagination complete")
        self.expect(r"AI: pagination complete\r\nchat> ", timeout=5)
        self.exit_chat()

    def scenario_edit(self) -> None:
        self.log("scenario edit")
        self.enter_chat()
        self.start_chat_turn("edit smoke", expect_fresh=True)
        self.send_host_line("CMD: edit")
        self.expect(r"AI requested command: edit\r\n", timeout=5)
        self.expect(r"editor: type into the scratch buffer, Backspace deletes, Esc returns to the monitor\r\n", timeout=5)
        self.send("hello", label="operator")
        self.expect(r"hello", timeout=3)
        self.send("\x08", label="operator")
        self.expect(r"editor: type into the scratch buffer, Backspace deletes, Esc returns to the monitor\r\nhell", timeout=3)
        self.send("!\rmore", label="operator")
        self.expect(r"!\r\nmore", timeout=3)
        checkpoint = len(self.transcript)
        self.send("\x1b", label="operator")
        self.expect(r"leaving editor\r\nchat> ", timeout=5)
        self.read_available(0.3)
        if "POST /chat " in self.transcript[checkpoint:]:
            raise SmokeFailure("interactive edit unexpectedly auto-continued the chat session")
        self.exit_chat()

    def scenario_loop(self) -> None:
        self.log("scenario loop")
        self.enter_chat()
        first_payload = self.start_chat_turn("loop smoke", expect_fresh=True)
        self.send_host_line("CMD: /loop")
        self.expect(
            r"recursive loop enabled\. the host will keep iterating until claude returns a normal answer\.\r\n",
            timeout=5,
        )
        second_payload = self.expect_auto_continue(first_payload["session"])
        if second_payload.get("session") != first_payload.get("session"):
            raise SmokeFailure("loop did not keep the same session across iterations")
        if second_payload.get("loop") is not True:
            raise SmokeFailure(f"loop iteration payload missing loop=true: {second_payload}")
        self.send_host_line("CMD: /peek 0000 04")
        self.expect(r"AI requested command: /peek 0000 04\r\n", timeout=5)
        self.expect(r"peek 0x0000: FA 31 C0 8E\r\n", timeout=5)
        third_payload = self.expect_auto_continue(first_payload["session"])
        if third_payload.get("session") != first_payload.get("session"):
            raise SmokeFailure("loop session changed after peek")
        if third_payload.get("loop") is not True:
            raise SmokeFailure(f"loop follow-up payload missing loop=true: {third_payload}")
        self.send_host_line(f"AI: loop finished gen={self.generation}")
        self.expect(rf"AI: loop finished gen={re.escape(self.generation)}\r\nchat> ", timeout=5)
        self.exit_chat()

    def scenario_patch(self) -> None:
        self.log("scenario patch")
        self.enter_chat()
        first_payload = self.start_chat_turn("patch smoke", expect_fresh=True)
        self.send_host_line("CMD: /patch 0000 90")
        self.expect(r"AI requested command: /patch 0000 90\r\n", timeout=5)
        self.expect(r"\*\*\* CLAUDE COOKED UP A LIVE CODE PATCH \*\*\*\r\n", timeout=5)
        self.expect(r"patch applied\. beautiful chaos achieved\.\r\n", timeout=5)
        generation_match = self.expect(r"generation advanced to (0x[0-9A-F]{8})\r\n", timeout=5)
        self.generation = generation_match.group(1)
        self.expect_auto_continue(first_payload["session"])
        self.send_host_line("AI: patch verified")
        self.expect(r"AI: patch verified\r\nchat> ", timeout=5)
        chat_payload = self.start_chat_turn(
            "verify patch",
            expect_fresh=False,
            expected_session=first_payload["session"],
            forbid_retire_before_chat=True,
        )
        if chat_payload.get("generation") != self.generation:
            raise SmokeFailure(f"verify turn did not use updated generation {self.generation}")
        self.send_host_line("CMD: /peek 0000 04")
        self.expect(r"AI requested command: /peek 0000 04\r\n", timeout=5)
        self.expect(r"peek 0x0000: 90 31 C0 8E\r\n", timeout=5)
        self.expect_auto_continue(first_payload["session"])
        self.send_host_line("AI: patch bytes confirmed")
        self.expect(r"AI: patch bytes confirmed\r\nchat> ", timeout=5)
        self.exit_chat()

    def scenario_stream(self) -> None:
        self.log("scenario stream")
        self.enter_chat()
        first_payload = self.start_chat_turn("stream smoke", expect_fresh=True)

        self.send_host_line("CMD: /stream B8 00 0F CD 10")
        self.expect(r"AI requested command: /stream B8 00 0F CD 10\r\n", timeout=5)
        self.expect(r"stream ax=0x5003\r\n", timeout=5)
        self.expect_auto_continue(first_payload["session"])

        self.send_host_line("CMD: /stream CD 11")
        self.expect(r"AI requested command: /stream CD 11\r\n", timeout=5)
        self.expect(r"stream ax=0x[0-9A-F]{4}\r\n", timeout=5)
        self.expect_auto_continue(first_payload["session"])

        self.send_host_line("CMD: /stream BA FD 03 EC B4 00")
        self.expect(r"AI requested command: /stream BA FD 03 EC B4 00\r\n", timeout=5)
        self.expect(r"stream ax=0x00[0-9A-F]{2}\r\n", timeout=5)
        self.expect_auto_continue(first_payload["session"])

        self.send_host_line("AI: stream probes complete")
        self.expect(r"AI: stream probes complete\r\nchat> ", timeout=5)
        self.exit_chat()

    def scenario_kill_self(self) -> None:
        self.log("scenario kill-self")
        self.enter_chat()
        self.start_chat_turn("kill-self smoke", expect_fresh=True)
        self.send_host_line("SYS: session retired by /kill-self")
        self.expect(r"SYS: session retired by /kill-self\r\n", timeout=5)
        self.expect(r"halting CPU\r\n", timeout=5)
        checkpoint = len(self.transcript)
        self.read_available(0.5)
        if "kernel_os> " in self.transcript[checkpoint:]:
            raise SmokeFailure("kernel returned to the prompt after /kill-self instead of halting")


def main() -> int:
    smoke = VMChatSmoke()
    try:
        smoke.run()
    except (SmokeFailure, subprocess.CalledProcessError) as exc:
        print(f"vm chat smoke failed: {exc}", file=sys.stderr)
        print(f"transcript saved to {TRANSCRIPT_PATH}", file=sys.stderr)
        return 1

    print("vm chat smoke passed")
    print(f"transcript saved to {TRANSCRIPT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
