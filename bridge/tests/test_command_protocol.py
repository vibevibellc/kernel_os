import sys
import types
import unittest
from collections import deque
from pathlib import Path


BRIDGE_DIR = Path(__file__).resolve().parents[1]
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")

    class _DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {}

    class _DummySession:
        def __init__(self) -> None:
            self.verify = None

        def request(self, *args, **kwargs):
            return _DummyResponse()

    class _RequestException(Exception):
        pass

    class _SSLError(_RequestException):
        pass

    requests_stub.Session = _DummySession
    requests_stub.Response = _DummyResponse
    requests_stub.RequestException = _RequestException
    requests_stub.exceptions = types.SimpleNamespace(SSLError=_SSLError)
    requests_stub.post = lambda *args, **kwargs: _DummyResponse()
    sys.modules["requests"] = requests_stub

from command_protocol import extract_kernel_command, match_pending_observation
from kernel_capabilities import LOCAL_MONITOR_COMMANDS
from serial_to_anthropic import attach_recent_output as serial_attach_recent_output
from serial_to_anthropic import format_bridge_reply as serial_format_bridge_reply
from supervise_kernel import build_chat_relay_lines
from supervise_kernel import detect_prompt_fragment
from supervise_kernel import format_bridge_reply as supervise_format_bridge_reply


KERNEL_COMMANDS = LOCAL_MONITOR_COMMANDS


class ExtractKernelCommandTests(unittest.TestCase):
    def test_returns_exact_patch_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/patch 0 90", KERNEL_COMMANDS),
            "/patch 0 90",
        )

    def test_returns_exact_stream_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/stream B8 00 0F CD 10", KERNEL_COMMANDS),
            "/stream B8 00 0F CD 10",
        )

    def test_returns_exact_loop_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/loop", KERNEL_COMMANDS),
            "/loop",
        )

    def test_returns_exact_peekpage_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/peekpage 1000 0002", KERNEL_COMMANDS),
            "/peekpage 1000 0002",
        )

    def test_returns_plain_ramlist_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/ramlist", KERNEL_COMMANDS),
            "ramlist",
        )

    def test_returns_standalone_command_from_multiline_reply(self) -> None:
        reply = (
            "I found the first opcode.\n"
            "This is enough to test the edit path.\n\n"
            "/patch 0 90\n"
        )
        self.assertEqual(extract_kernel_command(reply, KERNEL_COMMANDS), "/patch 0 90")

    def test_ignores_inline_code_mentions(self) -> None:
        reply = "I would try `/patch 0 90`, but I need confirmation first."
        self.assertIsNone(extract_kernel_command(reply, KERNEL_COMMANDS))

    def test_rejects_multiple_standalone_commands(self) -> None:
        reply = "/peek 0 10\n/patch 0 90"
        self.assertIsNone(extract_kernel_command(reply, KERNEL_COMMANDS))


class MatchPendingObservationTests(unittest.TestCase):
    def test_matches_peek_output(self) -> None:
        pending_peeks = deque([{"session": "kernel-main", "command": "/peek 0 10"}])
        pending_patches = deque()

        payload = match_pending_observation(
            pending_peeks,
            deque(),
            pending_patches,
            "peek 0x0000: FA 31 C0 8E",
        )

        self.assertEqual(
            payload,
            {
                "session": "kernel-main",
                "kind": "peek",
                "origin": "/peek 0 10",
                "observation": "peek 0x0000: FA 31 C0 8E",
            },
        )
        self.assertEqual(len(pending_peeks), 0)

    def test_matches_patch_result(self) -> None:
        pending_peeks = deque()
        pending_streams = deque()
        pending_patches = deque([{"session": "kernel-main", "command": "/patch 0 90"}])

        payload = match_pending_observation(
            pending_peeks,
            pending_streams,
            pending_patches,
            "patch applied. if we crash now, blame this one.",
        )

        self.assertEqual(
            payload,
            {
                "session": "kernel-main",
                "kind": "patch",
                "origin": "/patch 0 90",
                "observation": "patch applied. if we crash now, blame this one.",
            },
        )
        self.assertEqual(len(pending_patches), 0)

    def test_matches_stream_output(self) -> None:
        pending_peeks = deque()
        pending_streams = deque([{"session": "kernel-main", "command": "/stream B8 34 12"}])
        pending_patches = deque()

        payload = match_pending_observation(
            pending_peeks,
            pending_streams,
            pending_patches,
            "stream ax=0x1234",
        )

        self.assertEqual(
            payload,
            {
                "session": "kernel-main",
                "kind": "stream",
                "origin": "/stream B8 34 12",
                "observation": "stream ax=0x1234",
            },
        )
        self.assertEqual(len(pending_streams), 0)

    def test_ignores_unmatched_lines(self) -> None:
        pending_peeks = deque([{"session": "kernel-main", "command": "/peek 0 10"}])
        pending_patches = deque([{"session": "kernel-main", "command": "/patch 0 90"}])

        payload = match_pending_observation(
            pending_peeks,
            deque(),
            pending_patches,
            "generation advanced to 0x00000002",
        )

        self.assertIsNone(payload)
        self.assertEqual(len(pending_peeks), 1)
        self.assertEqual(len(pending_patches), 1)


class BridgeReplyFormattingTests(unittest.TestCase):
    def test_chat_kill_self_maps_to_sys_reply(self) -> None:
        for formatter in (serial_format_bridge_reply, supervise_format_bridge_reply):
            with self.subTest(formatter=formatter.__module__):
                self.assertEqual(
                    formatter("/chat", {"retired": True, "retired_reason": "kill-self"}),
                    "SYS: session retired by /kill-self",
                )

    def test_host_retire_request_stays_ai_text(self) -> None:
        for formatter in (serial_format_bridge_reply, supervise_format_bridge_reply):
            with self.subTest(formatter=formatter.__module__):
                self.assertEqual(
                    formatter(
                        "/host",
                        {
                            "action": "retire-session",
                            "retired": True,
                            "retired_reason": "host-request",
                            "message": "retired chat-00000003",
                        },
                    ),
                    "AI: retired chat-00000003",
                )

    def test_host_kill_self_still_maps_to_sys_reply(self) -> None:
        for formatter in (serial_format_bridge_reply, supervise_format_bridge_reply):
            with self.subTest(formatter=formatter.__module__):
                self.assertEqual(
                    formatter("/host", {"retired": True, "retired_reason": "kill-self"}),
                    "SYS: session retired by /kill-self",
                )

    def test_chat_command_reply_stays_cmd(self) -> None:
        for formatter in (serial_format_bridge_reply, supervise_format_bridge_reply):
            with self.subTest(formatter=formatter.__module__):
                self.assertEqual(
                    formatter("/chat", {"kernel_command": "/peek 0 10", "retired_reason": ""}),
                    "CMD: /peek 0 10",
                )


class AttachRecentOutputTests(unittest.TestCase):
    def test_attach_recent_output_appends_kernel_output_to_same_chat_session(self) -> None:
        payload = {"prompt": "make an edit to it"}
        recent_output = {
            "chat-00000003": deque(
                [
                    "AI requested command: /peek 0000 20",
                    "peek 0x0000: FA 31 C0 8E",
                ]
            )
        }

        serial_attach_recent_output(payload, "chat-00000003", recent_output)

        self.assertEqual(
            payload["messages"],
            [
                {
                    "role": "user",
                    "content": "Kernel output since your last action:\nAI requested command: /peek 0000 20\npeek 0x0000: FA 31 C0 8E",
                },
                {"role": "user", "content": "make an edit to it"},
            ],
        )
        self.assertEqual(len(recent_output["chat-00000003"]), 0)


class SupervisionRelayTests(unittest.TestCase):
    def test_detect_prompt_fragment_without_trailing_newline(self) -> None:
        self.assertEqual(detect_prompt_fragment("chat> "), "chat> ")
        self.assertEqual(detect_prompt_fragment("kernel_os> "), "kernel_os> ")
        self.assertIsNone(detect_prompt_fragment("AI: hello"))

    def test_build_chat_relay_lines_splits_long_prompt_within_limit(self) -> None:
        prompt = " ".join(f"chunk{i:02d}" for i in range(40))

        relay_lines = build_chat_relay_lines(prompt, limit=120)

        self.assertGreater(len(relay_lines), 1)
        for relay_line in relay_lines:
            self.assertLessEqual(len(relay_line), 120)
        self.assertIn("reply only waiting for more", relay_lines[0].lower())
        self.assertIn("act now", relay_lines[-1].lower())

    def test_build_chat_relay_lines_leaves_short_prompt_unchanged(self) -> None:
        self.assertEqual(build_chat_relay_lines("peek 0000 then patch", limit=120), ["peek 0000 then patch"])


if __name__ == "__main__":
    unittest.main()
