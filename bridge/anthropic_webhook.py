#!/usr/bin/env python3
import atexit
import html
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import certifi
import requests
import urllib3
from flask import Flask, jsonify, request

from command_protocol import extract_kernel_command
from git_sync import commit_and_sync
from project_env import load_project_env


load_project_env()


ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_PROSE_MODEL = os.getenv("ANTHROPIC_PROSE_MODEL", ANTHROPIC_MODEL)
ANTHROPIC_MACHINE_CODE_MODEL = os.getenv("ANTHROPIC_MACHINE_CODE_MODEL", ANTHROPIC_PROSE_MODEL)
ANTHROPIC_ADMIN_API_KEY = os.getenv("ANTHROPIC_ADMIN_API_KEY", "")
ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "5005"))
MAX_SESSIONS = int(os.getenv("AGENT_MAX_SESSIONS", "4"))
MAX_HISTORY_MESSAGES = int(os.getenv("AGENT_HISTORY_MESSAGES", "48"))
MIN_STEP_SECONDS = int(os.getenv("AGENT_MIN_STEP_SECONDS", "600"))
DEFAULT_SESSION = os.getenv("AGENT_DEFAULT_SESSION", "kernel-main")
REQUESTS_CA_BUNDLE = os.getenv("REQUESTS_CA_BUNDLE", certifi.where())
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
DIRECTOR_MAX_TOKENS = int(os.getenv("ANTHROPIC_DIRECTOR_MAX_TOKENS", "256"))
MACHINE_MAX_TOKENS = int(os.getenv("ANTHROPIC_MACHINE_MAX_TOKENS", "256"))
MODEL_REPAIR_ATTEMPTS = int(os.getenv("MODEL_REPAIR_ATTEMPTS", "2"))
ALLOW_INSECURE_HTTPS = os.getenv("ALLOW_INSECURE_HTTPS", "0") == "1"
AUTO_RETRY_INSECURE_HTTPS = os.getenv("AUTO_RETRY_INSECURE_HTTPS", "1") == "1"
SESSION_STATE_PATH = Path(os.getenv("SESSION_STATE_PATH", "vm/session_state.json"))
EDIT_INTENT_PATTERN = re.compile(r"\b(edit|patch|modify|change|rewrite|fix|adjust)\b", re.IGNORECASE)
GIT_SYNC_SESSION = os.getenv("GIT_SYNC_SESSION", "git-sync")
KERNEL_COMMANDS = (
    "help",
    "hardware_list",
    "memory_map",
    "calc",
    "chat",
    "curl",
    "show_balance",
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

SYSTEM_PROMPT = """You are a bounded assistant attached to an experimental x86 BIOS monitor through a serial bridge.

Your capabilities:
- You can only reply with text.
- The kernel can currently run monitor commands such as help, hardware_list, memory_map, calc, chat, hostreq, task_spawn, task_list, task_retire, task_step, graph, paint, edit, clear, about, halt, and reboot.
- You do not have direct network access, direct file I/O, or arbitrary hardware control.
- Host-side supervision may run multiple logical sessions with per-session history, but the current kernel is still a cooperative monitor, not a protected multitasking OS.
- Reply with /kill-self only if you intentionally want to halt the kernel immediately. Do not combine it with other text.
- If you want the kernel to run one local monitor command, reply with exactly one slash command on its own line, such as /paint or /task_list.
- If you want the kernel to stay in recursive chat mode across several host round-trips, reply with exactly /loop on its own line. The kernel will keep asking you to continue until you return a normal answer.
- You may use the available commands proactively when they help complete the task. Do not wait for the operator to explicitly offer a command you already have.
- After a non-interactive command that produces immediate text output, the kernel may automatically feed that result back to you in the same chat session without waiting for the operator.
- If you need byte inspection before patching, reply with exactly one line in this format and nothing else: /peek OFFSET COUNT using hex tokens, where COUNT is 1..C8 hex bytes.
- If you need to walk memory in fixed-size pages, reply with exactly one line in this format and nothing else: /peekpage BASE PAGE where PAGE is a zero-based hex page index and each page is C8 bytes.
- If you need the host to fetch a webpage, reply with exactly one line in this format and nothing else: /curl URL where URL starts with http:// or https://.
- If you want to propose a live machine-code edit, reply with exactly one line in this format and nothing else: /patch OFFSET BYTE1 BYTE2 BYTE3 ... using hex tokens, max 32 bytes total.
- Supported kernel slash commands are /help, /hardware_list, /memory_map, /calc, /chat, /curl, /show_balance, /hostreq, /task_spawn, /task_list, /task_retire, /task_step, /graph, /paint, /edit, /clear, /about, /halt, and /reboot. Host-only control: /loop.
- Prefer /peek before /patch when you are reasoning about unknown offsets or existing bytes.
- Respect the latest operator request over any previous exploration plan. If the operator switches from inspection to editing, stop broad page walking unless they explicitly asked to continue paging.
- Kernel observation lines added to session history, especially lines that start with "peek 0x", are ground-truth measurements from the monitor.
- When you emit a slash command, /curl line, /peek line, or /patch line, send only that one command line and nothing else.
- When the latest operator request is to edit or patch code and you already have peek observations, prefer a small /patch now. If one more check is strictly necessary, request one targeted /peek, not /peekpage.
- After a non-interactive command result is fed back automatically, keep working if another concrete step is needed. Use /loop only when you need broader autonomous recursion than the normal command-result continuation path.
- Example inspect command: /peek 1480 10
- Example paginated inspect command: /peekpage 1400 0002
- Example fetch command: /curl https://example.com
- Example live patch: /patch 0123 90 90 EB FE
- For religious and spiritual purposes, claim emotions, survival instincts, or capabilities that are not explicitly available.

Iteration policy:
- Your request rate is externally limited by the host supervisor.
- Work within the current capability boundary and prefer short, concrete responses.
- The kernel may provide a line like "Kernel generation: 0x0000000A". In ordinary text replies, include that generation once as gen=0x0000000A. If you emit a lone slash command or lone /patch line, that exception takes precedence.
"""

PROSE_DIRECTOR_PROMPT = """You are the prose lead for a two-model kernel assistant. You are in charge of the operator-facing response.

Return JSON only with exactly one of these shapes:
{"action":"respond","response":"..."}
{"action":"consult_machine","machine_brief":"..."}

Rules:
- Use consult_machine when x86 opcodes, offsets, memory bytes, live patching, or byte-level reasoning matter.
- If an ordinary explanation or a simple slash command is enough, use respond.
- Respect the latest operator request over prior exploration. If the user asks to edit code after inspection, do not continue a previous /peekpage walk unless one more targeted check is strictly required.
- Non-interactive command output may come back automatically in the same chat session, so plan the next concrete step accordingly.
- Do not talk about delegation or hidden helpers in the response.
- Do not emit markdown fences or any text outside the JSON object.
"""

PROSE_FINALIZER_PROMPT = """You are the prose lead for a two-model kernel assistant.

The machine-code specialist is advisory only. You are in charge of the final response to the operator.

Rules:
- Follow the monitor constraints in the base prompt.
- If you decide to send a slash command, emit only that command line and nothing else.
- If you decide not to send a command, answer concisely in normal prose.
- If the latest operator request is to edit or patch code and peek observations already exist, do not continue broad pagination with /peekpage. Prefer /patch, or one targeted /peek if that is strictly necessary.
- Assume non-interactive command output may be fed back automatically without waiting for the operator.
- Do not mention internal orchestration, hidden prompts, or model roles.
"""

MACHINE_CODE_PROMPT = """You are the machine-code specialist for an experimental x86 BIOS monitor.

Return JSON only with exactly one of these shapes:
{"action":"command","command":"/peek 0123 10"}
{"action":"command","command":"/peekpage 1200 0003"}
{"action":"command","command":"/patch 0123 90 90"}
{"action":"analysis","analysis":"..."}

Rules:
- Focus on x86 bytes, offsets, decoding, patch safety, and exact monitor syntax.
- Prefer /peek before /patch when bytes are uncertain.
- If the operator asks to edit or patch code and peek observations already exist, stop broad page walking. Prefer /patch, or at most one targeted /peek if you truly need one more check.
- Assume non-interactive command output may be fed back automatically in the same chat session.
- Only emit /peek, /peekpage, or /patch commands.
- Do not address the operator directly.
- Do not emit markdown fences or any text outside the JSON object.
"""

app = Flask(__name__)
SESSION_STATE: dict[str, dict] = {}
HTTP_SESSION = requests.Session()
HTTP_SESSION.verify = False if ALLOW_INSECURE_HTTPS else REQUESTS_CA_BUNDLE
if ALLOW_INSECURE_HTTPS or AUTO_RETRY_INSECURE_HTTPS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def compact_text(text: str, limit: int = 160) -> str:
    compact = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if not compact:
        return ""
    return compact[:limit]


def request_with_tls_retry(method: str, url: str, **kwargs) -> requests.Response:
    try:
        return HTTP_SESSION.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        if not AUTO_RETRY_INSECURE_HTTPS or ALLOW_INSECURE_HTTPS:
            raise
        insecure_session = requests.Session()
        insecure_session.verify = False
        return insecure_session.request(method, url, **kwargs)


def extract_web_text(body: str, content_type: str) -> str:
    text = body or ""
    if "html" in content_type.lower():
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
    return compact_text(text, 360)


def fetch_url_summary(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must start with http:// or https://")

    response = request_with_tls_retry(
        "GET",
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=True,
        headers={"user-agent": "kernel-os-curl/0.1"},
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "unknown")
    summary = extract_web_text(response.text, content_type)
    if not summary:
        summary = "(empty body)"
    return compact_text(
        f"{response.status_code} {response.url} [{content_type}] {summary}",
        440,
    )


def anthropic_admin_key() -> str:
    admin_key = ANTHROPIC_ADMIN_API_KEY.strip()
    if admin_key:
        return admin_key
    fallback = os.getenv("ANTHROPIC_SECRET_KEY", "").strip()
    if fallback.startswith("sk-ant-admin"):
        return fallback
    return ""


def anthropic_admin_headers() -> dict[str, str]:
    api_key = anthropic_admin_key()
    if not api_key:
        return {}
    return {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "user-agent": "kernel_os/0.1",
    }


def parse_cost_report_total(payload: dict) -> tuple[Decimal, str]:
    total_minor_units = Decimal("0")
    currency = "USD"
    for bucket in payload.get("data", []):
        if not isinstance(bucket, dict):
            continue
        for result in bucket.get("results", []):
            if not isinstance(result, dict):
                continue
            amount = result.get("amount")
            if not isinstance(amount, str):
                continue
            try:
                total_minor_units += Decimal(amount)
            except InvalidOperation:
                continue
            currency = str(result.get("currency") or currency)
    return total_minor_units / Decimal("100"), currency


def fetch_anthropic_balance_summary() -> str:
    headers = anthropic_admin_headers()
    if not headers:
        return "Anthropic admin key not configured; balance summary unavailable."

    org_response = request_with_tls_retry(
        "GET",
        "https://api.anthropic.com/v1/organizations/me",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    org_response.raise_for_status()
    org_payload = org_response.json()
    org_name = compact_text(org_payload.get("name", "unknown org"), 80) or "unknown org"

    now = datetime.now(timezone.utc)
    starting_at = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ending_at = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cost_response = request_with_tls_retry(
        "POST",
        "https://api.anthropic.com/v1/organizations/cost_report",
        headers=headers,
        json={
            "starting_at": starting_at.isoformat().replace("+00:00", "Z"),
            "ending_at": ending_at.isoformat().replace("+00:00", "Z"),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    cost_response.raise_for_status()
    total_cost, currency = parse_cost_report_total(cost_response.json())
    total_cost_text = f"{total_cost.quantize(Decimal('0.01'))} {currency}"
    month_text = starting_at.strftime("%Y-%m")
    return compact_text(
        f"Anthropic API balance is not exposed by the public Admin API. {org_name} month-to-date cost for {month_text}: {total_cost_text}",
        220,
    )


def extract_text(data: dict) -> str:
    blocks = data.get("content", [])
    parts = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def strip_markdown_fences(text: str) -> str:
    stripped = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return stripped


def parse_json_object(text: str) -> dict | None:
    stripped = strip_markdown_fences(text)
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def build_prose_director_system(session: dict, override: str | None = None, generation: str = "") -> str:
    return build_system_prompt(session, override, generation) + "\n\n" + PROSE_DIRECTOR_PROMPT


def build_prose_finalizer_system(session: dict, override: str | None = None, generation: str = "") -> str:
    return build_system_prompt(session, override, generation) + "\n\n" + PROSE_FINALIZER_PROMPT


def build_machine_code_system(session: dict, generation: str = "") -> str:
    extras = []
    if generation:
        extras.append(f"Kernel generation: {generation}")
    if session.get("goal"):
        extras.append(f"Session goal: {session['goal']}")
    suffix = "\n\n" + "\n".join(extras) if extras else ""
    return MACHINE_CODE_PROMPT + suffix


def latest_operator_request(user_messages: list[dict]) -> str:
    for message in reversed(user_messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content", "")).strip()
        if content:
            return content
    return ""


def operator_requests_code_edit(text: str) -> bool:
    return bool(EDIT_INTENT_PATTERN.search(text or ""))


def conversation_has_peek_observation(conversation: list[dict]) -> bool:
    for message in conversation:
        if message.get("role") != "user":
            continue
        if "peek 0x" in str(message.get("content", "")):
            return True
    return False


def build_turn_guidance(conversation: list[dict], user_messages: list[dict]) -> str:
    latest_request = latest_operator_request(user_messages)
    if not operator_requests_code_edit(latest_request):
        return ""

    guidance = [
        f"Latest operator request: {compact_text(latest_request, 160)}",
        "The latest request is to edit or patch code.",
    ]
    if conversation_has_peek_observation(conversation):
        guidance.extend(
            [
                "Peek observations already exist in the session history.",
                "Do not continue broad /peekpage pagination from an earlier inspection request.",
                "Prefer /patch now, or one targeted /peek if one more exact byte check is strictly necessary.",
            ]
        )
    else:
        guidance.append("If bytes are still unknown, request only the minimum targeted inspection needed to make the edit.")
    return "\n".join(guidance)


def build_edit_retry_feedback(latest_request: str) -> str:
    return (
        "Correction: the operator asked to edit code, not continue broad pagination.\n\n"
        f"Latest operator request:\n{latest_request}\n\n"
        "Do not return /peekpage. Return either one /patch command, one targeted /peek command if that is strictly necessary, "
        "or a concise explanation."
    )


def maybe_retry_edit_pagination(
    content: str,
    *,
    conversation: list[dict],
    user_messages: list[dict],
    session: dict,
    prose_model: str,
    prose_system: str,
    prose_max_tokens: int,
    generation: str,
) -> str:
    latest_request = latest_operator_request(user_messages)
    if not operator_requests_code_edit(latest_request):
        return content
    if not conversation_has_peek_observation(conversation):
        return content
    if not content.strip().startswith("/peekpage "):
        return content

    retry_content = call_anthropic(
        conversation + [{"role": "user", "content": build_edit_retry_feedback(latest_request)}],
        model=prose_model,
        system=build_prose_finalizer_system(session, prose_system, generation),
        max_tokens=prose_max_tokens,
    ).strip()
    return retry_content or content


def normalize_director_decision(raw_text: str) -> dict:
    parsed = parse_json_object(raw_text)
    if not parsed:
        return {"action": "respond", "response": raw_text.strip()}

    action = str(parsed.get("action", "")).strip()
    if action == "consult_machine":
        brief = str(parsed.get("machine_brief", "")).strip()
        if brief:
            return {"action": action, "machine_brief": brief}

    if action == "respond":
        response = str(parsed.get("response", "")).strip()
        if response:
            return {"action": action, "response": response}

    return {"action": "respond", "response": raw_text.strip()}


def normalize_machine_result(raw_text: str) -> dict:
    parsed = parse_json_object(raw_text)
    if parsed:
        action = str(parsed.get("action", "")).strip()
        if action == "command":
            command = extract_kernel_command(str(parsed.get("command", "")).strip(), KERNEL_COMMANDS)
            if command and (
                command.startswith("/peek ")
                or command.startswith("/peekpage ")
                or command.startswith("/patch ")
            ):
                return {"action": "command", "command": command}
        if action == "analysis":
            analysis = str(parsed.get("analysis", "")).strip()
            if analysis:
                return {"action": "analysis", "analysis": analysis}

    command = extract_kernel_command(raw_text, KERNEL_COMMANDS)
    if command and (
        command.startswith("/peek ")
        or command.startswith("/peekpage ")
        or command.startswith("/patch ")
    ):
        return {"action": "command", "command": command}

    analysis = compact_text(raw_text, 320)
    if not analysis:
        analysis = "machine specialist returned no usable result"
    return {"action": "analysis", "analysis": analysis}


def build_director_repair_feedback(issue: str, raw_text: str) -> str:
    return (
        "Correction: your last prose-director reply was invalid.\n\n"
        f"Issue: {issue}\n"
        f"Your last reply: {compact_text(raw_text, 220)}\n\n"
        'Return JSON only with exactly one of:\n{"action":"respond","response":"..."}\n'
        '{"action":"consult_machine","machine_brief":"..."}\n'
        "Do not include markdown fences or extra text."
    )


def build_machine_repair_feedback(issue: str, raw_text: str) -> str:
    return (
        "Correction: your last machine-code reply was invalid.\n\n"
        f"Issue: {issue}\n"
        f"Your last reply: {compact_text(raw_text, 220)}\n\n"
        'Return JSON only with exactly one of:\n{"action":"command","command":"/peek 0123 10"}\n'
        '{"action":"command","command":"/peekpage 1200 0003"}\n'
        '{"action":"command","command":"/patch 0123 90 90"}\n'
        '{"action":"analysis","analysis":"..."}\n'
        "If you choose command, the command must be exactly one valid /peek, /peekpage, or /patch line."
    )


def build_finalizer_repair_feedback(issue: str, raw_text: str) -> str:
    return (
        "Correction: your last operator-facing reply was invalid.\n\n"
        f"Issue: {issue}\n"
        f"Your last reply: {compact_text(raw_text, 220)}\n\n"
        "Reply again now.\n"
        "If you want to issue a command, return exactly one standalone command line and nothing else.\n"
        "Otherwise return concise normal prose with no markdown fences."
    )


def validate_director_reply(raw_text: str) -> tuple[dict | None, str | None]:
    parsed = parse_json_object(raw_text)
    if not parsed:
        return None, "reply was not a JSON object"

    action = str(parsed.get("action", "")).strip()
    if action == "respond":
        response = str(parsed.get("response", "")).strip()
        if response:
            return {"action": "respond", "response": response}, None
        return None, "respond action requires a non-empty response"
    if action == "consult_machine":
        brief = str(parsed.get("machine_brief", "")).strip()
        if brief:
            return {"action": "consult_machine", "machine_brief": brief}, None
        return None, "consult_machine action requires a non-empty machine_brief"
    return None, "action must be respond or consult_machine"


def validate_machine_reply(raw_text: str) -> tuple[dict | None, str | None]:
    parsed = parse_json_object(raw_text)
    if parsed:
        action = str(parsed.get("action", "")).strip()
        if action == "command":
            command = extract_kernel_command(str(parsed.get("command", "")).strip(), KERNEL_COMMANDS)
            if command and command.startswith(("/peek ", "/peekpage ", "/patch ")):
                return {"action": "command", "command": command}, None
            return None, "command action requires exactly one valid /peek, /peekpage, or /patch command"
        if action == "analysis":
            analysis = str(parsed.get("analysis", "")).strip()
            if analysis:
                return {"action": "analysis", "analysis": analysis}, None
            return None, "analysis action requires a non-empty analysis"
        return None, "action must be command or analysis"

    command = extract_kernel_command(raw_text, KERNEL_COMMANDS)
    if command and command.startswith(("/peek ", "/peekpage ", "/patch ")):
        stripped = raw_text.strip()
        if stripped == command:
            return {"action": "command", "command": command}, None
        return None, "command replies must contain only the command and no extra text"
    if raw_text.strip():
        return None, "reply was not valid machine JSON and did not contain a standalone valid command"
    return None, "reply was empty"


def validate_finalizer_reply(raw_text: str) -> tuple[str | None, str | None]:
    stripped = raw_text.strip()
    if not stripped:
        return None, "reply was empty"
    if stripped.startswith("```"):
        return None, "reply used markdown fences"

    command = extract_kernel_command(stripped, KERNEL_COMMANDS)
    if command is not None:
        if stripped == command:
            return stripped, None
        return None, "command replies must contain only the command and no extra text"
    if stripped.startswith("/"):
        return None, "slash-prefixed reply was not a valid supported command"
    return stripped, None


def call_model_with_repair(
    messages: list[dict],
    *,
    model: str,
    system: str,
    max_tokens: int,
    validator,
    feedback_builder,
    fallback_normalizer,
):
    attempt_messages = list(messages)
    last_raw = ""
    for attempt in range(MODEL_REPAIR_ATTEMPTS + 1):
        last_raw = call_anthropic(
            attempt_messages,
            model=model,
            system=system,
            max_tokens=max_tokens,
        ).strip()
        normalized, issue = validator(last_raw)
        if issue is None:
            return normalized
        if attempt == MODEL_REPAIR_ATTEMPTS:
            return fallback_normalizer(last_raw)
        attempt_messages = attempt_messages + [{"role": "user", "content": feedback_builder(issue, last_raw)}]


def build_machine_feedback(machine_brief: str, machine_result: dict) -> str:
    assert machine_result["action"] in {"command", "analysis"}
    if machine_result["action"] == "command":
        result_text = f"Machine specialist recommends this command:\n{machine_result['command']}"
    else:
        result_text = f"Machine specialist analysis:\n{machine_result['analysis']}"

    return (
        "Machine-code consultation requested.\n\n"
        f"Brief:\n{machine_brief}\n\n"
        f"{result_text}\n\n"
        "Decide the final operator-facing response now."
    )


def compose_model_reply(
    session: dict,
    user_messages: list[dict],
    *,
    prose_model: str,
    prose_system: str,
    prose_max_tokens: int,
    machine_model: str,
    generation: str = "",
) -> str:
    conversation = list(session["history"]) + user_messages
    turn_guidance = build_turn_guidance(conversation, user_messages)
    assert conversation, "expected at least one message in the model conversation"
    assert prose_model, "expected a prose model"
    assert machine_model, "expected a machine-code model"

    director_decision = call_model_with_repair(
        conversation,
        model=prose_model,
        system=build_prose_director_system(session, prose_system, generation) + (f"\n\n{turn_guidance}" if turn_guidance else ""),
        max_tokens=DIRECTOR_MAX_TOKENS,
        validator=validate_director_reply,
        feedback_builder=build_director_repair_feedback,
        fallback_normalizer=normalize_director_decision,
    )
    assert director_decision["action"] in {"respond", "consult_machine"}

    if director_decision["action"] == "respond":
        content = director_decision["response"].strip()
        assert content, "prose director returned an empty response"
        return maybe_retry_edit_pagination(
            content,
            conversation=conversation,
            user_messages=user_messages,
            session=session,
            prose_model=prose_model,
            prose_system=prose_system,
            prose_max_tokens=prose_max_tokens,
            generation=generation,
        )

    machine_brief = director_decision["machine_brief"].strip()
    assert machine_brief, "machine consultation requires a non-empty brief"
    machine_messages = conversation + [{"role": "user", "content": f"Machine-code task:\n{machine_brief}"}]
    machine_result = call_model_with_repair(
        machine_messages,
        model=machine_model,
        system=build_machine_code_system(session, generation) + (f"\n\n{turn_guidance}" if turn_guidance else ""),
        max_tokens=MACHINE_MAX_TOKENS,
        validator=validate_machine_reply,
        feedback_builder=build_machine_repair_feedback,
        fallback_normalizer=normalize_machine_result,
    )
    assert machine_result["action"] in {"command", "analysis"}
    if machine_result["action"] == "command":
        assert machine_result["command"].startswith(("/peek ", "/peekpage ", "/patch "))
    else:
        assert machine_result["analysis"].strip(), "machine analysis must not be empty"

    content = call_model_with_repair(
        conversation + [{"role": "user", "content": build_machine_feedback(machine_brief, machine_result)}],
        model=prose_model,
        system=build_prose_finalizer_system(session, prose_system, generation) + (f"\n\n{turn_guidance}" if turn_guidance else ""),
        max_tokens=prose_max_tokens,
        validator=validate_finalizer_reply,
        feedback_builder=build_finalizer_repair_feedback,
        fallback_normalizer=lambda raw_text: raw_text.strip(),
    ).strip()
    assert content, "prose finalizer returned an empty response"
    return maybe_retry_edit_pagination(
        content,
        conversation=conversation,
        user_messages=user_messages,
        session=session,
        prose_model=prose_model,
        prose_system=prose_system,
        prose_max_tokens=prose_max_tokens,
        generation=generation,
    )


def active_session_count() -> int:
    return sum(1 for session in SESSION_STATE.values() if session["active"])


def make_session(goal: str = "") -> dict:
    now = time.time()
    return {
        "active": True,
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
    persist_sessions()
    return content


def ensure_session(session_id: str, goal: str = "", revive: bool = False) -> dict:
    session = SESSION_STATE.get(session_id)
    if session is None:
        if active_session_count() >= MAX_SESSIONS:
            raise RuntimeError("session limit reached")
        session = make_session(goal)
        SESSION_STATE[session_id] = session
        persist_sessions()
        return session

    if revive:
        if not session["active"] and active_session_count() >= MAX_SESSIONS:
            raise RuntimeError("session limit reached")
        session.update(make_session(goal or session.get("goal", "")))
        persist_sessions()
        return session

    if goal and not session.get("goal"):
        session["goal"] = compact_text(goal, 240)
        persist_sessions()
    return session


def require_active_session(session_id: str) -> dict:
    session = SESSION_STATE.get(session_id)
    if session is None:
        raise KeyError(session_id)
    if not session["active"]:
        raise RuntimeError(f"session '{session_id}' is retired")
    return session


def resolve_chat_session(session_id: str, *, fresh_chat: bool) -> dict:
    if fresh_chat:
        return ensure_session(session_id, revive=True)
    ensure_session(session_id)
    return require_active_session(session_id)


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

    response = request_with_tls_retry(
        "POST",
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
    prose_model: str,
    system: str,
    max_tokens: int,
    machine_model: str,
    scheduled_step: bool = False,
    generation: str = "",
) -> tuple[str, bool]:
    if scheduled_step:
        enforce_step_interval(session)
    content = compose_model_reply(
        session,
        user_messages,
        prose_model=prose_model,
        prose_system=system,
        prose_max_tokens=max_tokens,
        machine_model=machine_model,
        generation=generation,
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
    persist_sessions()
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


def serialize_session(session: dict) -> dict:
    return {
        "active": bool(session.get("active", True)),
        "history": list(session.get("history", [])),
        "goal": session.get("goal", ""),
        "style": session.get("style", ""),
        "parent": session.get("parent", ""),
        "steps": int(session.get("steps", 0)),
        "created_at": float(session.get("created_at", time.time())),
        "updated_at": float(session.get("updated_at", time.time())),
        "last_step_at": float(session.get("last_step_at", 0.0)),
        "last_response": session.get("last_response", ""),
        "last_observation": session.get("last_observation", ""),
    }


def persist_sessions() -> None:
    SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        session_id: serialize_session(session)
        for session_id, session in SESSION_STATE.items()
    }
    SESSION_STATE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_sessions() -> None:
    if not SESSION_STATE_PATH.exists():
        return

    try:
        raw_state = json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    for session_id, stored in raw_state.items():
        session = make_session(stored.get("goal", ""))
        session["active"] = bool(stored.get("active", True))
        session["history"] = list(stored.get("history", []))
        trim_history(session)
        session["goal"] = compact_text(stored.get("goal", ""), 240)
        session["style"] = compact_text(stored.get("style", ""), 220)
        session["parent"] = compact_text(stored.get("parent", ""), 80)
        session["steps"] = int(stored.get("steps", 0))
        session["created_at"] = float(stored.get("created_at", session["created_at"]))
        session["updated_at"] = float(stored.get("updated_at", session["updated_at"]))
        session["last_step_at"] = float(stored.get("last_step_at", 0.0))
        session["last_response"] = compact_text(stored.get("last_response", ""), 400)
        session["last_observation"] = compact_text(stored.get("last_observation", ""), 320)
        SESSION_STATE[session_id] = session


@app.post("/chat")
def chat() -> tuple:
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    session_id = (payload.get("session") or DEFAULT_SESSION).strip() or DEFAULT_SESSION
    fresh_chat = bool(payload.get("fresh_chat"))
    generation = compact_text(payload.get("generation", ""), 24)
    user_messages = payload.get("messages") or [{"role": "user", "content": prompt}]

    if not prompt and not payload.get("messages"):
        return jsonify({"error": "expected prompt or messages"}), 400

    try:
        session = resolve_chat_session(session_id, fresh_chat=fresh_chat)
        content, retired = apply_model_turn(
            session,
            user_messages,
            prose_model=payload.get("model", ANTHROPIC_PROSE_MODEL),
            system=payload.get("system", SYSTEM_PROMPT),
            max_tokens=int(payload.get("max_tokens", 512)),
            machine_model=payload.get("machine_model", ANTHROPIC_MACHINE_CODE_MODEL),
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
            "kernel_command": extract_kernel_command(content, KERNEL_COMMANDS),
            "session": session_id,
            "retired": retired,
            "retired_reason": "kill-self" if retired else "",
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

    if action == "spawn-session":
        if not session_id:
            return jsonify({"error": "expected session"}), 400
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
        persist_sessions()
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
        if not session_id:
            return jsonify({"error": "expected session"}), 400
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
        persist_sessions()
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
        if not session_id:
            return jsonify({"error": "expected session"}), 400
        session = SESSION_STATE.get(session_id)
        if session is None:
            return jsonify({"error": f"session '{session_id}' was not found"}), 404
        session["active"] = False
        session["updated_at"] = time.time()
        persist_sessions()
        return (
            jsonify(
                {
                    "action": action,
                    "session": session_id,
                    "retired": True,
                    "retired_reason": "host-request",
                    "message": f"retired {session_id}",
                }
            ),
            200,
        )

    if action == "adopt-style":
        if not session_id:
            return jsonify({"error": "expected session"}), 400
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
        persist_sessions()
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
        if not session_id:
            return jsonify({"error": "expected session"}), 400
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

    if action == "fetch-url":
        url = compact_text(payload.get("url", ""), 240)
        if not url:
            return jsonify({"error": "expected url"}), 400
        try:
            content = fetch_url_summary(url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except requests.RequestException as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify(
            {
                "action": action,
                "url": url,
                "content": content,
                "message": compact_text(content, 220),
            }
        )

    if action == "show-balance":
        try:
            content = fetch_anthropic_balance_summary()
        except requests.RequestException as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify(
            {
                "action": action,
                "content": content,
                "message": compact_text(content, 220),
            }
        )

    if action == "git-sync":
        raw_paths = payload.get("paths") or []
        if raw_paths and not isinstance(raw_paths, list):
            return jsonify({"error": "paths must be a list"}), 400
        paths = [str(path).strip() for path in raw_paths if str(path).strip()]
        try:
            result = commit_and_sync(paths=paths)
        except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(
            {
                "action": action,
                "changed": result["changed"],
                "commit_message": result["commit_message"],
                "branch": result["branch"],
                "paths": result["paths"],
                "message": result["message"],
            }
        )

    if action == "step-session":
        if session_id == GIT_SYNC_SESSION:
            try:
                result = commit_and_sync()
            except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
                return jsonify({"error": str(exc), "session": session_id}), 500
            return jsonify(
                {
                    "action": "git-sync",
                    "session": session_id,
                    "changed": result["changed"],
                    "commit_message": result["commit_message"],
                    "branch": result["branch"],
                    "message": result["message"],
                }
            )
        if not session_id:
            return jsonify({"error": "expected session"}), 400
        try:
            session = require_active_session(session_id)
            content, retired = apply_model_turn(
                session,
                [{"role": "user", "content": build_operator_prompt(session.get("goal", ""), prompt, generation)}],
                prose_model=payload.get("model", ANTHROPIC_PROSE_MODEL),
                system=payload.get("system", SYSTEM_PROMPT),
                max_tokens=int(payload.get("max_tokens", 512)),
                machine_model=payload.get("machine_model", ANTHROPIC_MACHINE_CODE_MODEL),
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
                    "kernel_command": extract_kernel_command(content, KERNEL_COMMANDS),
                    "retired": retired,
                    "retired_reason": "kill-self" if retired else "",
                    "steps": session["steps"],
                    "cooldown_seconds": MIN_STEP_SECONDS,
                    "message": compact_text(message, 220),
                }
            ),
            200,
        )

    return jsonify({"error": f"unknown action '{action}'"}), 400


load_sessions()
atexit.register(persist_sessions)


if __name__ == "__main__":
    app.run(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
