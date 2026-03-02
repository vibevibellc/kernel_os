#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import deque


PATCH_PATTERN = re.compile(r"/patch\s+(?:0x)?[0-9a-fA-F]{1,4}(?:\s+(?:0x)?[0-9a-fA-F]{1,2}){1,32}\s*$")
STREAM_PATTERN = re.compile(r"/stream(?:\s+(?:0x)?[0-9a-fA-F]{1,2}){1,31}\s*$")
PEEK_PATTERN = re.compile(r"/peek\s+(?:0x)?[0-9a-fA-F]{1,4}\s+(?:0x)?[0-9a-fA-F]{1,2}\s*$")
PEEK_PAGE_PATTERN = re.compile(r"/peekpage\s+(?:0x)?[0-9a-fA-F]{1,4}\s+(?:0x)?[0-9a-fA-F]{1,4}\s*$")
CURL_PATTERN = re.compile(r"/curl\s+https?://\S+\s*$")
LOOP_PATTERN = re.compile(r"/loop\s*$")
PEEK_OUTPUT_PATTERN = re.compile(r"^peek 0x[0-9A-Fa-f]+:\s")
STREAM_OUTPUT_PATTERN = re.compile(r"^stream ax=0x[0-9A-Fa-f]{4}\b")
PATCH_RESULT_PATTERNS = (
    re.compile(r"^patch applied\b", re.IGNORECASE),
    re.compile(r"^patch aborted by human\b", re.IGNORECASE),
    re.compile(r"^claude sent a malformed patch\b", re.IGNORECASE),
)


def extract_command_line(text: str, kernel_commands: tuple[str, ...]) -> str | None:
    stripped = text.strip()
    if CURL_PATTERN.fullmatch(stripped):
        return stripped
    if LOOP_PATTERN.fullmatch(stripped):
        return stripped
    if PEEK_PATTERN.fullmatch(stripped):
        return stripped
    if PEEK_PAGE_PATTERN.fullmatch(stripped):
        return stripped
    if STREAM_PATTERN.fullmatch(stripped):
        return stripped
    if PATCH_PATTERN.fullmatch(stripped):
        return stripped

    match = re.fullmatch(r"/([a-z0-9_]+)", stripped)
    if not match:
        return None

    command = match.group(1)
    if command == "kill-self":
        return None
    if command not in kernel_commands:
        return None
    return command


def extract_kernel_command(text: str, kernel_commands: tuple[str, ...]) -> str | None:
    direct_command = extract_command_line(text, kernel_commands)
    if direct_command is not None:
        return direct_command

    commands = []
    for line in text.splitlines():
        command = extract_command_line(line, kernel_commands)
        if command is not None:
            commands.append(command)

    if len(commands) == 1:
        return commands[0]
    return None


def match_pending_observation(
    pending_peeks: deque[dict],
    pending_streams: deque[dict],
    pending_patches: deque[dict],
    line: str,
) -> dict | None:
    if pending_peeks and PEEK_OUTPUT_PATTERN.match(line):
        pending = pending_peeks.popleft()
        return {
            "session": pending["session"],
            "kind": "peek",
            "origin": pending["command"],
            "observation": line,
        }

    if pending_streams and STREAM_OUTPUT_PATTERN.match(line):
        pending = pending_streams.popleft()
        return {
            "session": pending["session"],
            "kind": "stream",
            "origin": pending["command"],
            "observation": line,
        }

    if pending_patches and any(pattern.match(line) for pattern in PATCH_RESULT_PATTERNS):
        pending = pending_patches.popleft()
        return {
            "session": pending["session"],
            "kind": "patch",
            "origin": pending["command"],
            "observation": line,
        }

    return None
