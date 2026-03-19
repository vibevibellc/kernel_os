#!/usr/bin/env python3
from __future__ import annotations


LOCAL_MONITOR_COMMANDS = (
    "hardware_list",
    "memory_map",
    "calc",
    "chat",
    "curl",
    "hostreq",
    "task_spawn",
    "task_list",
    "task_retire",
    "task_step",
    "ramlist",
    "edit",
    "grep",
    "peek",
    "search",
    "next",
    "prev",
    "forward",
    "back",
    "view",
    "pm32",
    "halt",
    "reboot",
)


def format_monitor_command_names(commands: tuple[str, ...] = LOCAL_MONITOR_COMMANDS) -> str:
    return ", ".join(commands)


def format_slash_command_names(commands: tuple[str, ...] = LOCAL_MONITOR_COMMANDS) -> str:
    return ", ".join(f"/{command}" for command in commands)
