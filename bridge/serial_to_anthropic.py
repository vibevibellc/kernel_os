#!/usr/bin/env python3
import argparse
import json
import os
import re
import socket
import time
from collections import deque
from urllib.parse import urljoin

import requests

from command_protocol import match_pending_observation
from live_patch_persistence import persist_stage2_patch
from project_env import load_project_env


load_project_env()


REQUEST_PREFIX = "POST "
PROMPT_PATTERN = re.compile(r"^(?:kernel_os|chat|calc|url|session|goal|prompt|host action|source session|modifier|offset hex|count hex).*>\s*$")


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
    response = requests.post(url, json=payload, timeout=90)
    response.raise_for_status()
    return response.json()


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


def record_pending_observation(
    webhook: str,
    pending_peeks: deque[dict],
    pending_patches: deque[dict],
    line: str,
) -> None:
    payload = match_pending_observation(pending_peeks, pending_patches, line)
    if payload is None:
        return

    if payload.get("kind") == "patch":
        try:
            changed_paths = persist_stage2_patch(payload["origin"], payload["observation"])
            if changed_paths:
                changed_list = ", ".join(str(path) for path in changed_paths)
                print(f"Persisted live patch into source: {sanitize_line(changed_list)}")
        except Exception as exc:  # noqa: BLE001
            print(f"Patch persistence error: {sanitize_line(str(exc))}")

    data = forward_request(webhook, "/host", {
        "action": "record-observation",
        **payload,
    })
    print(f"Observed for {payload['session']}: {sanitize_line(data.get('message', line))}")


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

    while True:
        sock = connect_socket(args.socket)
        print(f"Connected to {args.socket}")
        pending_peeks: deque[dict] = deque()
        pending_patches: deque[dict] = deque()
        recent_output: dict[str, deque[str]] = {}
        capture_session: str | None = None

        try:
            with sock:
                reader = sock.makefile("r", encoding="utf-8", errors="replace", newline="\n")
                for raw_line in reader:
                    line = raw_line.strip()
                    if not line:
                        continue

                    print(f"Kernel sent: {line}")
                    if not line.startswith(REQUEST_PREFIX):
                        try:
                            capture_session = append_kernel_output(recent_output, capture_session, line)
                            record_pending_observation(args.webhook, pending_peeks, pending_patches, line)
                        except Exception as exc:  # noqa: BLE001
                            print(f"Observation error: {sanitize_line(str(exc))}")
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
