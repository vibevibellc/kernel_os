import sys
import unittest
from collections import deque
from pathlib import Path


BRIDGE_DIR = Path(__file__).resolve().parents[1]
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

from command_protocol import extract_kernel_command, match_pending_observation


KERNEL_COMMANDS = (
    "help",
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
    "graph",
    "paint",
    "edit",
    "clear",
    "about",
    "halt",
    "reboot",
)


class ExtractKernelCommandTests(unittest.TestCase):
    def test_returns_exact_patch_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/patch 0 90", KERNEL_COMMANDS),
            "/patch 0 90",
        )

    def test_returns_exact_loop_command(self) -> None:
        self.assertEqual(
            extract_kernel_command("/loop", KERNEL_COMMANDS),
            "/loop",
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
        pending_patches = deque([{"session": "kernel-main", "command": "/patch 0 90"}])

        payload = match_pending_observation(
            pending_peeks,
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

    def test_ignores_unmatched_lines(self) -> None:
        pending_peeks = deque([{"session": "kernel-main", "command": "/peek 0 10"}])
        pending_patches = deque([{"session": "kernel-main", "command": "/patch 0 90"}])

        payload = match_pending_observation(
            pending_peeks,
            pending_patches,
            "generation advanced to 0x00000002",
        )

        self.assertIsNone(payload)
        self.assertEqual(len(pending_peeks), 1)
        self.assertEqual(len(pending_patches), 1)


if __name__ == "__main__":
    unittest.main()
