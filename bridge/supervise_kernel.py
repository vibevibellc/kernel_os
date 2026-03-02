#!/usr/bin/env python3
import argparse
import json
import os
import re
import selectors
import socket
import sys
import termios
import time
from collections import deque
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from command_protocol import match_pending_observation
from git_sync_debounce import GitSyncDebouncer
from live_patch_persistence import persist_stage2_patch
from project_env import load_project_env


load_project_env()


REQUEST_PREFIX = "POST "
PROMPT_PATTERN = re.compile(r"^(?:kernel_os|chat|calc|url|session|goal|prompt|host action|source session|modifier|offset hex|count hex).*>\s*$")
GIT_SYNC_DEBOUNCE_SECONDS = float(os.getenv("GIT_SYNC_DEBOUNCE_SECONDS", "10.0"))
KERNEL_LINE_LIMIT = int(os.getenv("KERNEL_LINE_LIMIT", "255"))


def sanitize_line(text: str, limit: int = 480) -> str:
    compact = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return compact[:limit] if compact else "ok"


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


def forward_request(webhook: str, route: str, payload: dict) -> dict:
    url = urljoin(webhook.rstrip("/") + "/", route.lstrip("/"))
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def format_bridge_reply(route: str, data: dict) -> str:
    if data.get("retired_reason") == "kill-self":
        return "SYS: session retired by /kill-self"
    if route == "/chat" and data.get("kernel_command"):
        return f"CMD: {sanitize_line(data['kernel_command'], 220)}"
    content = data.get("content") or data.get("message") or data.get("error") or ""
    return f"AI: {sanitize_line(content)}"


def parse_kernel_line(line: str) -> tuple[str, str]:
    if not line.startswith(REQUEST_PREFIX):
        raise ValueError("unsupported request prefix")
    route, body = line[len(REQUEST_PREFIX) :].split(" ", 1)
    return route.strip(), body.strip()


class RawTerminal:
    def __init__(self) -> None:
        self._fd = None
        self._original = None

    def __enter__(self) -> "RawTerminal":
        if not sys.stdin.isatty():
            return self
        self._fd = sys.stdin.fileno()
        self._original = termios.tcgetattr(self._fd)
        raw = termios.tcgetattr(self._fd)
        raw[3] &= ~(termios.ECHO | termios.ICANON)
        raw[6][termios.VMIN] = 1
        raw[6][termios.VTIME] = 0
        termios.tcsetattr(self._fd, termios.TCSADRAIN, raw)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None and self._original is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original)


def print_status(message: str) -> None:
    sys.stdout.write(f"\n[{message}]\n")
    sys.stdout.flush()


def detect_prompt_fragment(text: str) -> str | None:
    stripped = text.rstrip("\r")
    if not stripped:
        return None
    if PROMPT_PATTERN.match(stripped):
        return stripped
    return None


def _fit_text_to_capacities(text: str, capacities: list[int]) -> list[str] | None:
    words = text.split()
    if not words:
        return [""]

    chunks: list[str] = []
    word_index = 0
    for capacity in capacities:
        if word_index >= len(words):
            break
        if capacity <= 0:
            return None

        current = words[word_index]
        if len(current) > capacity:
            return None
        word_index += 1

        while word_index < len(words):
            candidate = f"{current} {words[word_index]}"
            if len(candidate) > capacity:
                break
            current = candidate
            word_index += 1
        chunks.append(current)

    if word_index != len(words):
        return None
    return chunks


def build_chat_relay_lines(text: str, limit: int = KERNEL_LINE_LIMIT) -> list[str]:
    normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(normalized) <= limit:
        return [normalized]

    for chunk_count in range(2, 33):
        templates = []
        capacities = []
        for index in range(1, chunk_count + 1):
            if index < chunk_count:
                template = (
                    f"Relay {index}/{chunk_count}. Store this chunk. Do not act yet. "
                    "Reply only waiting for more. Text: {chunk}"
                )
            else:
                template = (
                    f"Relay {index}/{chunk_count} final. Combine all earlier chunks with this one "
                    "and act now. Text: {chunk}"
                )
            templates.append(template)
            capacities.append(limit - len(template.format(chunk="")))

        chunks = _fit_text_to_capacities(normalized, capacities)
        if chunks is None or len(chunks) != chunk_count:
            continue
        return [template.format(chunk=chunk) for template, chunk in zip(templates, chunks)]

    raise ValueError("prompt is too long to relay safely through chat")


def record_pending_observation(
    webhook: str,
    pending_peeks: deque[dict],
    pending_patches: deque[dict],
    line: str,
    git_sync: GitSyncDebouncer,
) -> None:
    payload = match_pending_observation(pending_peeks, pending_patches, line)
    if payload is None:
        return

    if payload.get("kind") == "patch":
        try:
            changed_paths = persist_stage2_patch(payload["origin"], payload["observation"])
            if changed_paths:
                changed_list = ", ".join(str(path) for path in changed_paths)
                print_status(f"persisted live patch into source: {sanitize_line(changed_list)}")
                git_sync.note_changed_paths([str(path) for path in changed_paths])
        except Exception as exc:  # noqa: BLE001
            print_status(f"patch persistence error -> {sanitize_line(str(exc))}")

    data = forward_request(webhook, "/host", {
        "action": "record-observation",
        **payload,
    })
    print_status(f"observe[{payload['session']}] -> {sanitize_line(data.get('message', line))}")


def append_kernel_output(
    recent_output: dict[str, deque[str]],
    capture_session: str | None,
    line: str,
) -> str | None:
    if not capture_session:
        return capture_session
    if PROMPT_PATTERN.match(line):
        return None
    if line.startswith("POST "):
        return capture_session
    if line.startswith("AI: "):
        return capture_session
    recent_output.setdefault(capture_session, deque(maxlen=12)).append(line)
    return capture_session


def attach_recent_output(
    payload: dict,
    session_id: str,
    recent_output: dict[str, deque[str]],
) -> None:
    lines = recent_output.get(session_id)
    prompt = (payload.get("prompt") or "").strip()
    if not lines or not prompt or payload.get("messages"):
        return
    payload["messages"] = [
        {"role": "user", "content": "Kernel output since your last action:\n" + "\n".join(lines)},
        {"role": "user", "content": prompt},
    ]
    recent_output[session_id].clear()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.path.join("vm", "com1.sock"))
    parser.add_argument("--webhook", default="http://127.0.0.1:5005")
    parser.add_argument("--session", default="kernel-main")
    args = parser.parse_args()

    print_status(
        f"supervisor starting socket={args.socket} webhook={args.webhook} session={args.session}"
    )
    print_status("line prompts are buffered locally; long chat prompts are relayed safely; Ctrl-C exits")
    git_sync = GitSyncDebouncer(
        lambda paths: forward_request(args.webhook, "/host", {"action": "git-sync", "paths": paths}),
        lambda message: print_status(f"git sync -> {sanitize_line(message)}"),
        debounce_seconds=GIT_SYNC_DEBOUNCE_SECONDS,
    )

    try:
        with RawTerminal():
            while True:
                sock = connect_socket(args.socket)
                sock.setblocking(False)
                pending_peeks: deque[dict] = deque()
                pending_patches: deque[dict] = deque()
                recent_output: dict[str, deque[str]] = {}
                capture_session: str | None = None
                active_prompt: str | None = None
                operator_line_buffer = bytearray()
                pending_chat_relay: deque[str] = deque()
                relay_total = 0
                relay_sent = 0
                selector = selectors.DefaultSelector()
                selector.register(sock, selectors.EVENT_READ, "socket")
                if sys.stdin.isatty():
                    selector.register(sys.stdin, selectors.EVENT_READ, "stdin")

                line_buffer = ""
                print_status(f"connected to {args.socket}")

                try:
                    while True:
                        for key, _ in selector.select(timeout=0.5):
                            if key.data == "stdin":
                                data = os.read(sys.stdin.fileno(), 1)
                                if not data:
                                    return
                                if pending_chat_relay:
                                    if data == b"\x03":
                                        raise KeyboardInterrupt
                                    continue
                                if active_prompt is None:
                                    sock.sendall(data)
                                    continue

                                if data in (b"\r", b"\n"):
                                    text = operator_line_buffer.decode("utf-8", errors="replace")
                                    operator_line_buffer.clear()

                                    if len(text) <= KERNEL_LINE_LIMIT:
                                        write_line(sock, text)
                                        active_prompt = None
                                        continue

                                    if active_prompt.startswith("chat>"):
                                        try:
                                            relay_lines = build_chat_relay_lines(text)
                                        except ValueError as exc:
                                            print_status(sanitize_line(str(exc)))
                                            active_prompt = None
                                            continue
                                        relay_total = len(relay_lines)
                                        relay_sent = 1
                                        print_status(f"split long chat prompt into {relay_total} turns")
                                        write_line(sock, relay_lines[0])
                                        pending_chat_relay.extend(relay_lines[1:])
                                        active_prompt = None
                                        continue

                                    print_status(
                                        f"input exceeds {KERNEL_LINE_LIMIT} bytes for {sanitize_line(active_prompt)}; shorten it"
                                    )
                                    active_prompt = None
                                    continue

                                if data in (b"\x08", b"\x7f"):
                                    if operator_line_buffer:
                                        operator_line_buffer.pop()
                                    continue

                                if data == b"\x03":
                                    raise KeyboardInterrupt

                                byte = data[0]
                                if byte < 32:
                                    continue
                                operator_line_buffer.extend(data)
                                continue

                            chunk = sock.recv(4096)
                            if not chunk:
                                raise OSError("socket closed")

                            text = chunk.decode("utf-8", errors="replace")
                            sys.stdout.write(text)
                            sys.stdout.flush()
                            line_buffer += text

                            while "\n" in line_buffer:
                                raw_line, line_buffer = line_buffer.split("\n", 1)
                                line = raw_line.rstrip("\r")
                                if PROMPT_PATTERN.match(line):
                                    active_prompt = line
                                    operator_line_buffer.clear()
                                    if pending_chat_relay and line.startswith("chat>"):
                                        relay_sent += 1
                                        print_status(f"sending relayed chat prompt chunk {relay_sent}/{relay_total}")
                                        write_line(sock, pending_chat_relay.popleft())
                                        active_prompt = None
                                if not line.startswith(REQUEST_PREFIX):
                                    try:
                                        capture_session = append_kernel_output(recent_output, capture_session, line)
                                        record_pending_observation(args.webhook, pending_peeks, pending_patches, line, git_sync)
                                    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                                        print_status(f"observe error -> {sanitize_line(str(exc))}")
                                    continue

                                try:
                                    route, body = parse_kernel_line(line)
                                    payload = json.loads(body)
                                    if route == "/chat":
                                        payload.setdefault("session", args.session)
                                    request_session = (payload.get("session") or args.session).strip() or args.session
                                    if route == "/chat":
                                        attach_recent_output(payload, request_session, recent_output)
                                    data = forward_request(args.webhook, route, payload)
                                    reply = format_bridge_reply(route, data)
                                    command = data.get("kernel_command") or ""
                                    if command.startswith("/peek ") or command.startswith("/peekpage "):
                                        pending_peeks.append({"session": request_session, "command": command})
                                    if command.startswith("/patch "):
                                        pending_patches.append({"session": request_session, "command": command})
                                    if command:
                                        recent_output.setdefault(request_session, deque(maxlen=12)).clear()
                                        capture_session = request_session
                                    print_status(f"bridge[{request_session}] -> {reply}")
                                    write_line(sock, reply)
                                except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                                    error_reply = f"Error: {sanitize_line(str(exc))}"
                                    print_status(f"bridge error -> {error_reply}")
                                    write_line(sock, error_reply)

                            prompt_fragment = detect_prompt_fragment(line_buffer)
                            if prompt_fragment is not None:
                                active_prompt = prompt_fragment
                                if pending_chat_relay and prompt_fragment.startswith("chat>"):
                                    relay_sent += 1
                                    print_status(f"sending relayed chat prompt chunk {relay_sent}/{relay_total}")
                                    write_line(sock, pending_chat_relay.popleft())
                                    line_buffer = ""
                                    active_prompt = None
                            elif line_buffer:
                                active_prompt = None
                except KeyboardInterrupt:
                    print_status("supervisor exiting")
                    return
                except OSError:
                    print_status("socket disconnected, retrying")
                    selector.close()
                    try:
                        sock.close()
                    except OSError:
                        pass
                    time.sleep(0.5)
    finally:
        git_sync.close()


if __name__ == "__main__":
    main()
