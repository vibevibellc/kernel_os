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


REQUEST_PREFIX = "POST "
PEEK_OUTPUT_PATTERN = re.compile(r"^peek 0x[0-9A-Fa-f]+:\s")


def sanitize_line(text: str, limit: int = 220) -> str:
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
    sock.sendall((text + "\r\n").encode("utf-8", errors="replace"))


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


def format_bridge_reply(data: dict) -> str:
    if data.get("retired"):
        return "SYS: session retired by /kill-self"
    if data.get("kernel_command"):
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


def record_pending_observation(
    webhook: str,
    pending_peeks: deque[dict],
    line: str,
) -> None:
    if not pending_peeks or not PEEK_OUTPUT_PATTERN.match(line):
        return

    pending = pending_peeks.popleft()
    payload = {
        "action": "record-observation",
        "session": pending["session"],
        "kind": "peek",
        "origin": pending["command"],
        "observation": line,
    }
    data = forward_request(webhook, "/host", payload)
    print_status(f"observe[{pending['session']}] -> {sanitize_line(data.get('message', line))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.path.join("vm", "com1.sock"))
    parser.add_argument("--webhook", default="http://127.0.0.1:5005")
    parser.add_argument("--session", default="kernel-main")
    args = parser.parse_args()

    print_status(
        f"supervisor starting socket={args.socket} webhook={args.webhook} session={args.session}"
    )
    print_status("keystrokes go straight to the kernel; Ctrl-C exits")

    with RawTerminal():
        while True:
            sock = connect_socket(args.socket)
            sock.setblocking(False)
            pending_peeks: deque[dict] = deque()
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
                            sock.sendall(data)
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
                            if not line.startswith(REQUEST_PREFIX):
                                try:
                                    record_pending_observation(args.webhook, pending_peeks, line)
                                except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                                    print_status(f"observe error -> {sanitize_line(str(exc))}")
                                continue

                            try:
                                route, body = parse_kernel_line(line)
                                payload = json.loads(body)
                                if route == "/chat":
                                    payload.setdefault("session", args.session)
                                request_session = (payload.get("session") or args.session).strip() or args.session
                                data = forward_request(args.webhook, route, payload)
                                reply = format_bridge_reply(data)
                                command = data.get("kernel_command") or ""
                                if command.startswith("/peek "):
                                    pending_peeks.append({"session": request_session, "command": command})
                                print_status(f"bridge[{request_session}] -> {reply}")
                                write_line(sock, reply)
                            except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                                error_reply = f"Error: {sanitize_line(str(exc))}"
                                print_status(f"bridge error -> {error_reply}")
                                write_line(sock, error_reply)
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


if __name__ == "__main__":
    main()
