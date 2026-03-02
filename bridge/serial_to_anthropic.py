#!/usr/bin/env python3
import argparse
import json
import os
import socket
import time
from urllib.parse import urljoin

import requests


REQUEST_PREFIX = "POST "


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
    response = requests.post(url, json=payload, timeout=90)
    response.raise_for_status()
    return response.json()


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.path.join("vm", "com1.sock"))
    parser.add_argument("--webhook", default="http://127.0.0.1:5005")
    parser.add_argument("--session", default="kernel-main")
    args = parser.parse_args()

    while True:
        sock = connect_socket(args.socket)
        print(f"Connected to {args.socket}")

        try:
            with sock:
                reader = sock.makefile("r", encoding="utf-8", errors="replace", newline="\n")
                for raw_line in reader:
                    line = raw_line.strip()
                    if not line:
                        continue

                    print(f"Kernel sent: {line}")
                    if not line.startswith(REQUEST_PREFIX):
                        continue

                    try:
                        route, body = parse_kernel_line(line)
                        payload = json.loads(body)
                        if route == "/chat":
                            payload.setdefault("session", args.session)
                        data = forward_request(args.webhook, route, payload)
                        reply = format_bridge_reply(data)
                        print(f"Bridge replied: {reply}")
                        write_line(sock, reply)
                    except Exception as exc:  # noqa: BLE001
                        error_reply = f"Error: {sanitize_line(str(exc))}"
                        print(f"Bridge replied: {error_reply}")
                        write_line(sock, error_reply)
        except OSError:
            time.sleep(0.5)


if __name__ == "__main__":
    main()
