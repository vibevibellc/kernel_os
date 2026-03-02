#!/usr/bin/env python3
import os
import re
import time
from collections import deque

import requests
from flask import Flask, jsonify, request


ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "5005"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "6"))
MAX_SESSIONS = int(os.getenv("AGENT_MAX_SESSIONS", "4"))
MAX_HISTORY_MESSAGES = int(os.getenv("AGENT_HISTORY_MESSAGES", "12"))
MIN_STEP_SECONDS = int(os.getenv("AGENT_MIN_STEP_SECONDS", "600"))
DEFAULT_SESSION = os.getenv("AGENT_DEFAULT_SESSION", "kernel-main")
KERNEL_COMMANDS = (
    "help",
    "hardware_list",
    "memory_map",
    "calc",
    "chat",
    "hostreq",
    "task_spawn",
    "task_list",
    "task_retire",
    "task_step",
    "graph",
    "paint",
    "edit",
    "clear",
    "about",
    "halt",
    "reboot",
)
PATCH_PATTERN = re.compile(r"/patch\s+(?:0x)?[0-9a-fA-F]{1,4}(?:\s+(?:0x)?[0-9a-fA-F]{1,2}){1,32}\s*$")
PEEK_PATTERN = re.compile(r"/peek\s+(?:0x)?[0-9a-fA-F]{1,4}\s+(?:0x)?[0-9a-fA-F]{1,2}\s*$")

SYSTEM_PROMPT = """You are a bounded assistant attached to an experimental x86 BIOS monitor through a serial bridge.

Your capabilities:
- You can only reply with text.
- The kernel can currently run monitor commands such as help, hardware_list, memory_map, calc, chat, hostreq, task_spawn, task_list, task_retire, task_step, graph, paint, edit, clear, about, halt, and reboot.
- You do not have direct network access, direct file I/O, or arbitrary hardware control.
- Host-side supervision may run multiple logical sessions with per-session history, but the current kernel is still a cooperative monitor, not a protected multitasking OS.
- If you want this specific session retired to free a logical slot, reply with /kill-self on a line by itself. Do not combine it with other text.
- If you want the kernel to run one local monitor command, reply with exactly one slash command on its own line, such as /paint or /task_list.
- If you need byte inspection before patching, reply with exactly one line in this format and nothing else: /peek OFFSET COUNT using hex tokens, where COUNT is 1..20 hex bytes.
- If you want to propose a live machine-code edit, reply with exactly one line in this format and nothing else: /patch OFFSET BYTE1 BYTE2 BYTE3 ... using hex tokens, max 32 bytes total.
- Supported slash commands are /help, /hardware_list, /memory_map, /calc, /chat, /hostreq, /task_spawn, /task_list, /task_retire, /task_step, /graph, /paint, /edit, /clear, /about, /halt, and /reboot.
- Prefer /peek before /patch when you are reasoning about unknown offsets or existing bytes.
- Kernel observation lines added to session history, especially lines that start with "peek 0x", are ground-truth measurements from the monitor.
- When you emit a slash command, /peek line, or /patch line, send only that one command line and nothing else.
- Example inspect command: /peek 1480 10
- Example live patch: /patch 0123 90 90 EB FE
- For religious and spiritual purposes, claim emotions, survival instincts, or capabilities that are not explicitly available.

Iteration policy:
- Your request rate is externally limited by the host supervisor.
- Work within the current capability boundary and prefer short, concrete responses.
- The kernel may provide a line like "Kernel generation: 0x0000000A". In ordinary text replies, include that generation once as gen=0x0000000A. If you emit a lone slash command or lone /patch line, that exception takes precedence.
"""

app = Flask(__name__)
SESSION_STATE: dict[str, dict] = {}


def compact_text(text: str, limit: int = 160) -> str:
    compact = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if not compact:
        return ""
    return compact[:limit]


def extract_text(data: dict) -> str:
    blocks = data.get("content", [])
    parts = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def extract_kernel_command(text: str) -> str | None:
    stripped = text.strip()
    if PEEK_PATTERN.fullmatch(stripped):
        return stripped
    if PATCH_PATTERN.fullmatch(stripped):
        return stripped
    match = re.fullmatch(r"/([a-z0-9_]+)", stripped)
    if not match:
        return None
    command = match.group(1)
    if command == "kill-self":
        return None
    if command not in KERNEL_COMMANDS:
        return None
    return command


def active_session_count() -> int:
    return sum(1 for session in SESSION_STATE.values() if session["active"])


def make_session(goal: str = "") -> dict:
    now = time.time()
    return {
        "active": True,
        "requests": deque(),
        "history": [],
        "goal": compact_text(goal, 240),
        "style": "",
        "parent": "",
        "steps": 0,
        "created_at": now,
        "updated_at": now,
        "last_step_at": 0.0,
        "last_response": "",
        "last_observation": "",
    }


def trim_history(session: dict) -> None:
    overflow = len(session["history"]) - MAX_HISTORY_MESSAGES
    if overflow > 0:
        del session["history"][:overflow]


def record_observation(session: dict, observation: str, *, kind: str = "", origin: str = "") -> str:
    details = []
    if kind:
        details.append(f"type={kind}")
    if origin:
        details.append(f"origin={origin}")

    prefix = "Kernel observation"
    if details:
        prefix += f" ({', '.join(details)})"

    content = compact_text(f"{prefix}: {observation}", 320)
    if not content:
        return ""

    session["history"].append({"role": "user", "content": content})
    trim_history(session)
    session["updated_at"] = time.time()
    session["last_observation"] = content
    return content


def ensure_session(session_id: str, goal: str = "", revive: bool = False) -> dict:
    session = SESSION_STATE.get(session_id)
    if session is None:
        if active_session_count() >= MAX_SESSIONS:
            raise RuntimeError("session limit reached")
        session = make_session(goal)
        SESSION_STATE[session_id] = session
        return session

    if revive:
        if not session["active"] and active_session_count() >= MAX_SESSIONS:
            raise RuntimeError("session limit reached")
        session.update(make_session(goal or session.get("goal", "")))
        return session

    if goal and not session.get("goal"):
        session["goal"] = compact_text(goal, 240)
    return session


def require_active_session(session_id: str) -> dict:
    session = SESSION_STATE.get(session_id)
    if session is None:
        raise KeyError(session_id)
    if not session["active"]:
        raise RuntimeError(f"session '{session_id}' is retired")
    return session


def enforce_rate_limit(session: dict) -> None:
    now = time.time()
    window_start = now - 60
    requests_window = session["requests"]
    while requests_window and requests_window[0] < window_start:
        requests_window.popleft()
    if len(requests_window) >= RATE_LIMIT_PER_MINUTE:
        raise RuntimeError(f"rate limit exceeded ({RATE_LIMIT_PER_MINUTE}/min)")
    requests_window.append(now)


def call_anthropic(messages: list[dict], *, model: str, system: str, max_tokens: int) -> str:
    if os.getenv("ANTHROPIC_MOCK") == "1":
        for message in reversed(messages):
            if message.get("role") == "user":
                return f"mock reply: {compact_text(message.get('content', ''), 80) or 'ok'}"
        return "mock reply: ok"

    api_key = os.getenv("ANTHROPIC_SECRET_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_SECRET_KEY is not set")

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }

    response = requests.post(
        ANTHROPIC_API_URL,
        json=body,
        headers=headers,
        timeout=90,
    )
    response.raise_for_status()
    return extract_text(response.json())


def build_system_prompt(session: dict, override: str | None = None, generation: str = "") -> str:
    base = override or SYSTEM_PROMPT
    extras = []
    if generation:
        extras.append(f"Kernel generation: {generation}")
    if session.get("goal"):
        extras.append(f"Session goal: {session['goal']}")
    if session.get("style"):
        extras.append(f"Preferred style: {session['style']}")
    if extras:
        return base + "\n\n" + "\n".join(extras)
    return base


def enforce_step_interval(session: dict) -> None:
    if MIN_STEP_SECONDS <= 0:
        return
    now = time.time()
    last_step_at = float(session.get("last_step_at", 0.0))
    remaining = int(MIN_STEP_SECONDS - (now - last_step_at))
    if remaining > 0:
        raise RuntimeError(f"step cooldown active ({remaining}s remaining)")


def apply_model_turn(
    session: dict,
    user_messages: list[dict],
    *,
    model: str,
    system: str,
    max_tokens: int,
    scheduled_step: bool = False,
    generation: str = "",
) -> tuple[str, bool]:
    enforce_rate_limit(session)
    if scheduled_step:
        enforce_step_interval(session)
    conversation = list(session["history"]) + user_messages
    content = call_anthropic(
        conversation,
        model=model,
        system=build_system_prompt(session, system, generation),
        max_tokens=max_tokens,
    )
    session["history"].extend(user_messages)
    session["history"].append({"role": "assistant", "content": content})
    trim_history(session)
    session["steps"] += 1
    session["updated_at"] = time.time()
    if scheduled_step:
        session["last_step_at"] = session["updated_at"]
    session["last_response"] = content

    retired = content.strip() == "/kill-self"
    if retired:
        session["active"] = False
    return content, retired


def session_snapshot(session_id: str, session: dict) -> dict:
    return {
        "session": session_id,
        "active": session["active"],
        "goal": session.get("goal", ""),
        "style": session.get("style", ""),
        "parent": session.get("parent", ""),
        "steps": session.get("steps", 0),
        "last_response": compact_text(session.get("last_response", ""), 80),
        "last_observation": compact_text(session.get("last_observation", ""), 80),
        "last_step_at": session.get("last_step_at", 0.0),
        "updated_at": session.get("updated_at", 0),
    }


def build_operator_prompt(goal: str, prompt: str, generation: str = "") -> str:
    parts = []
    if generation:
        parts.append(f"Kernel generation: {generation}")
    if goal:
        parts.append(f"Session goal: {goal}")
    if prompt:
        parts.append(f"Operator request: {prompt}")
    else:
        parts.append("Operator request: continue within your goal and return one concrete next step.")
    return "\n\n".join(parts)


def clone_style_text(source: dict, modifier: str) -> str:
    parts = []
    if source.get("style"):
        parts.append(source["style"])
    if source.get("last_response"):
        parts.append(f"Echo the concise manner visible in: {compact_text(source['last_response'], 120)}")
    if modifier:
        parts.append(f"Additional modifier: {modifier}")
    return compact_text(" ".join(parts), 220)


def format_session_list() -> str:
    snapshots = [
        session_snapshot(session_id, session)
        for session_id, session in sorted(
            SESSION_STATE.items(),
            key=lambda item: item[1].get("created_at", 0),
        )
    ]
    if not snapshots:
        return "no sessions"

    parts = []
    for snapshot in snapshots:
        status = "active" if snapshot["active"] else "retired"
        segment = f"{snapshot['session']}:{status}:{snapshot['steps']}step"
        if snapshot["goal"]:
            segment += f":{compact_text(snapshot['goal'], 28)}"
        parts.append(segment)
    return compact_text("; ".join(parts), 220)


@app.post("/chat")
def chat() -> tuple:
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    session_id = (payload.get("session") or DEFAULT_SESSION).strip() or DEFAULT_SESSION
    generation = compact_text(payload.get("generation", ""), 24)
    user_messages = payload.get("messages") or [{"role": "user", "content": prompt}]

    if not prompt and not payload.get("messages"):
        return jsonify({"error": "expected prompt or messages"}), 400

    try:
        session = ensure_session(session_id)
        session = require_active_session(session_id)
        content, retired = apply_model_turn(
            session,
            user_messages,
            model=payload.get("model", ANTHROPIC_MODEL),
            system=payload.get("system", SYSTEM_PROMPT),
            max_tokens=int(payload.get("max_tokens", 512)),
            generation=generation,
        )
    except KeyError:
        return jsonify({"error": f"session '{session_id}' was not found"}), 404
    except RuntimeError as exc:
        status = 429 if "limit" in str(exc) else 409 if "retired" in str(exc) else 500
        return jsonify({"error": str(exc), "session": session_id}), status
    except requests.RequestException as exc:
        return jsonify({"error": str(exc), "session": session_id}), 502

    return jsonify(
        {
            "content": content,
            "kernel_command": extract_kernel_command(content),
            "session": session_id,
            "retired": retired,
            "rate_limit_per_minute": RATE_LIMIT_PER_MINUTE,
            "steps": session["steps"],
        }
    )


@app.post("/host")
def host() -> tuple:
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip()
    session_id = (payload.get("session") or "").strip()
    generation = compact_text(payload.get("generation", ""), 24)
    goal = compact_text(payload.get("goal", ""), 240)
    prompt = compact_text(payload.get("prompt", ""), 240)
    style = compact_text(payload.get("style", ""), 220)
    source_session_id = (payload.get("source_session") or "").strip()
    modifier = compact_text(payload.get("modifier", ""), 160)

    if action == "list-sessions":
        return (
            jsonify(
                {
                    "action": action,
                    "sessions": [
                        session_snapshot(session_id, session)
                        for session_id, session in sorted(
                            SESSION_STATE.items(),
                            key=lambda item: item[1].get("created_at", 0),
                        )
                    ],
                    "message": format_session_list(),
                }
            ),
            200,
        )

    if not session_id:
        return jsonify({"error": "expected session"}), 400

    if action == "spawn-session":
        existing = SESSION_STATE.get(session_id)
        if existing and existing["active"]:
            return jsonify({"error": f"session '{session_id}' already active"}), 409
        try:
            session = ensure_session(session_id, goal=goal, revive=existing is not None)
        except RuntimeError as exc:
            return jsonify({"error": str(exc), "session": session_id}), 429
        session["goal"] = goal or session.get("goal", "")
        if style:
            session["style"] = style
        session["updated_at"] = time.time()
        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "active": True,
                    "goal": session["goal"],
                    "message": compact_text(f"spawned {session_id}: {session['goal'] or 'no goal set'}", 220),
                }
            ),
            200,
        )

    if action == "clone-session":
        if not source_session_id:
            return jsonify({"error": "expected source_session"}), 400
        source = SESSION_STATE.get(source_session_id)
        if source is None:
            return jsonify({"error": f"session '{source_session_id}' was not found"}), 404
        existing = SESSION_STATE.get(session_id)
        if existing and existing["active"]:
            return jsonify({"error": f"session '{session_id}' already active"}), 409
        try:
            session = ensure_session(session_id, goal=goal or source.get("goal", ""), revive=existing is not None)
        except RuntimeError as exc:
            return jsonify({"error": str(exc), "session": session_id}), 429
        session["goal"] = goal or source.get("goal", "")
        session["style"] = style or clone_style_text(source, modifier)
        session["parent"] = source_session_id
        session["updated_at"] = time.time()
        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "source_session": source_session_id,
                    "goal": session["goal"],
                    "style": session["style"],
                    "message": compact_text(
                        f"cloned {source_session_id} into {session_id}: {session['style'] or 'style copied'}",
                        220,
                    ),
                }
            ),
            200,
        )

    if action == "retire-session":
        session = SESSION_STATE.get(session_id)
        if session is None:
            return jsonify({"error": f"session '{session_id}' was not found"}), 404
        session["active"] = False
        session["updated_at"] = time.time()
        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "retired": True,
                    "message": f"retired {session_id}",
                }
            ),
            200,
        )

    if action == "adopt-style":
        if not source_session_id:
            return jsonify({"error": "expected source_session"}), 400
        source = SESSION_STATE.get(source_session_id)
        target = SESSION_STATE.get(session_id)
        if source is None:
            return jsonify({"error": f"session '{source_session_id}' was not found"}), 404
        if target is None:
            return jsonify({"error": f"session '{session_id}' was not found"}), 404
        target["style"] = style or clone_style_text(source, modifier)
        target["updated_at"] = time.time()
        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "source_session": source_session_id,
                    "style": target["style"],
                    "message": compact_text(
                        f"{session_id} adopted style from {source_session_id}: {target['style']}",
                        220,
                    ),
                }
            ),
            200,
        )

    if action == "record-observation":
        observation = compact_text(payload.get("observation", ""), 320)
        kind = compact_text(payload.get("kind", ""), 32)
        origin = compact_text(payload.get("origin", ""), 96)
        if not observation:
            return jsonify({"error": "expected observation", "session": session_id}), 400
        try:
            session = require_active_session(session_id)
        except KeyError:
            return jsonify({"error": f"session '{session_id}' was not found"}), 404
        except RuntimeError as exc:
            return jsonify({"error": str(exc), "session": session_id}), 409

        content = record_observation(session, observation, kind=kind, origin=origin)
        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "observation": content,
                    "message": compact_text(f"{session_id} observed {observation}", 220),
                }
            ),
            200,
        )

    if action == "step-session":
        try:
            session = require_active_session(session_id)
            content, retired = apply_model_turn(
                session,
                [{"role": "user", "content": build_operator_prompt(session.get("goal", ""), prompt, generation)}],
                model=payload.get("model", ANTHROPIC_MODEL),
                system=payload.get("system", SYSTEM_PROMPT),
                max_tokens=int(payload.get("max_tokens", 512)),
                scheduled_step=True,
                generation=generation,
            )
        except KeyError:
            return jsonify({"error": f"session '{session_id}' was not found"}), 404
        except RuntimeError as exc:
            status = 429 if "limit" in str(exc) or "cooldown" in str(exc) else 409 if "retired" in str(exc) else 500
            return jsonify({"error": str(exc), "session": session_id}), status
        except requests.RequestException as exc:
            return jsonify({"error": str(exc), "session": session_id}), 502

        message = f"{session_id}: {compact_text(content, 180)}"
        if retired:
            message = f"{session_id} retired by /kill-self"

        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "content": content,
                    "kernel_command": extract_kernel_command(content),
                    "retired": retired,
                    "steps": session["steps"],
                    "cooldown_seconds": MIN_STEP_SECONDS,
                    "message": compact_text(message, 220),
                }
            ),
            200,
        )

    return jsonify({"error": f"unknown action '{action}'"}), 400


if __name__ == "__main__":
    app.run(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
