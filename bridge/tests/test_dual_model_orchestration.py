import sys
import types
import unittest
from pathlib import Path
from unittest import mock


BRIDGE_DIR = Path(__file__).resolve().parents[1]
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))


if "certifi" not in sys.modules:
    certifi_stub = types.ModuleType("certifi")
    certifi_stub.where = lambda: ""
    sys.modules["certifi"] = certifi_stub

if "urllib3" not in sys.modules:
    urllib3_stub = types.ModuleType("urllib3")
    urllib3_stub.disable_warnings = lambda *args, **kwargs: None
    urllib3_stub.exceptions = types.SimpleNamespace(InsecureRequestWarning=RuntimeWarning)
    sys.modules["urllib3"] = urllib3_stub

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
    sys.modules["requests"] = requests_stub

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")

    class _DummyFlask:
        def __init__(self, name: str) -> None:
            self.name = name

        def post(self, _route: str):
            def decorator(func):
                return func

            return decorator

    flask_stub.Flask = _DummyFlask
    flask_stub.jsonify = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    flask_stub.request = types.SimpleNamespace(get_json=lambda silent=True: {})
    sys.modules["flask"] = flask_stub

import anthropic_webhook as webhook


class ComposeModelReplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = webhook.make_session("inspect boot code")
        self.user_messages = [{"role": "user", "content": "peek the boot bytes and patch if safe"}]

    def test_director_can_respond_without_machine_consult(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            return_value='{"action":"respond","response":"/task_list"}',
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/task_list")
        self.assertEqual(call_mock.call_count, 1)
        self.assertEqual(call_mock.call_args.kwargs["model"], "prose-model")
        self.assertIn("two-model kernel assistant", call_mock.call_args.kwargs["system"])

    def test_machine_consultation_ends_with_prose_finalizer_output(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"consult_machine","machine_brief":"Find the exact bytes at the reset vector and propose the next monitor command."}',
                '{"action":"command","command":"/peek FFF0 10"}',
                "/peek FFF0 10",
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/peek FFF0 10")
        self.assertEqual(call_mock.call_count, 3)
        self.assertEqual(call_mock.call_args_list[0].kwargs["model"], "prose-model")
        self.assertEqual(call_mock.call_args_list[1].kwargs["model"], "machine-model")
        self.assertIn("Machine-code task:", call_mock.call_args_list[1].args[0][-1]["content"])
        self.assertEqual(call_mock.call_args_list[2].kwargs["model"], "prose-model")
        self.assertIn(
            "Machine specialist recommends this command:",
            call_mock.call_args_list[2].args[0][-1]["content"],
        )

    def test_machine_consultation_can_return_peekpage_command(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"consult_machine","machine_brief":"Walk memory near 0x1400 in fixed-size pages."}',
                '{"action":"command","command":"/peekpage 1400 0002"}',
                "/peekpage 1400 0002",
            ],
        ):
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/peekpage 1400 0002")

    def test_machine_consultation_can_return_stream_command(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"consult_machine","machine_brief":"Run a short live hardware probe through the stream path."}',
                '{"action":"command","command":"/stream B8 00 0F CD 10"}',
                "/stream B8 00 0F CD 10",
            ],
        ):
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/stream B8 00 0F CD 10")

    def test_hardware_probe_peek_reply_is_bounced_to_stream(self) -> None:
        hardware_prompt = [
            {
                "role": "user",
                "content": (
                    "Probe current BIOS video mode without patching anything. "
                    "Use direct live execution if available and keep it non-destructive."
                ),
            }
        ]

        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"respond","response":"/peek 0040 10"}',
                "/stream B8 00 0F CD 10",
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                hardware_prompt,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/stream B8 00 0F CD 10")
        self.assertIn(
            "live hardware-state probe",
            call_mock.call_args_list[1].args[0][-1]["content"],
        )

    def test_machine_analysis_can_be_turned_into_prose(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"consult_machine","machine_brief":"Decode the bytes at 0x0000 and recommend a safe next step."}',
                '{"action":"analysis","analysis":"The first opcode is CLI, so patching blindly is risky without another peek."}',
                "Use /peek 0 10 first so we can verify the current bytes. gen=0x00000001",
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "Use /peek 0 10 first so we can verify the current bytes. gen=0x00000001")
        self.assertEqual(call_mock.call_count, 3)
        self.assertIn(
            "Machine specialist analysis:",
            call_mock.call_args_list[2].args[0][-1]["content"],
        )

    def test_edit_request_with_existing_peek_retries_broad_pagination_reply(self) -> None:
        self.session["history"].append(
            {
                "role": "user",
                "content": "Kernel observation (type=peek, origin=/peek 0 20): peek 0x0000: FA 31 C0 8E",
            }
        )
        user_messages = [{"role": "user", "content": "edit some code non destructively"}]

        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"respond","response":"/peekpage 0000 0001"}',
                "/patch 0003 90",
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/patch 0003 90")
        self.assertEqual(call_mock.call_count, 2)
        self.assertIn(
            "Do not continue broad /peekpage pagination",
            call_mock.call_args_list[0].kwargs["system"],
        )
        self.assertIn(
            "Do not return /peekpage",
            call_mock.call_args_list[1].args[0][-1]["content"],
        )

    def test_director_invalid_json_is_bounced_back_for_repair(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                "respond with /task_list",
                '{"action":"respond","response":"/task_list"}',
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/task_list")
        self.assertEqual(call_mock.call_count, 2)
        self.assertIn(
            "your last prose-director reply was invalid",
            call_mock.call_args_list[1].args[0][-1]["content"],
        )

    def test_director_invalid_direct_patch_command_is_bounced_back_for_repair(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"respond","response":"/patch 2814 68 6F 73 74 72 65 71 3A 20 6C 69 73 74 2C 20 73 70 61 77 6E 2C 20 63 6C 6F 6E 65 2C 20 72 65 74 69 72 65 2C 20 73 74 65 70"}',
                '{"action":"respond","response":"/patch 2814 68 6F 73 74 72 65 71 3A 20 6C 69 73 74 2C 20"}',
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/patch 2814 68 6F 73 74 72 65 71 3A 20 6C 69 73 74 2C 20")
        self.assertEqual(call_mock.call_count, 2)
        self.assertIn(
            "invalid direct command",
            call_mock.call_args_list[1].args[0][-1]["content"],
        )

    def test_machine_invalid_command_is_bounced_back_for_repair(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"consult_machine","machine_brief":"Return the exact next patch command."}',
                '{"action":"command","command":"patch 0003 90"}',
                '{"action":"command","command":"/patch 0003 90"}',
                "/patch 0003 90",
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/patch 0003 90")
        self.assertEqual(call_mock.call_count, 4)
        self.assertIn(
            "your last machine-code reply was invalid",
            call_mock.call_args_list[2].args[0][-1]["content"],
        )

    def test_finalizer_noisy_command_is_bounced_back_for_repair(self) -> None:
        with mock.patch.object(
            webhook,
            "call_anthropic",
            side_effect=[
                '{"action":"consult_machine","machine_brief":"Return the exact next peek command."}',
                '{"action":"command","command":"/peek 0000 10"}',
                "Use this:\n/peek 0000 10",
                "/peek 0000 10",
            ],
        ) as call_mock:
            content = webhook.compose_model_reply(
                self.session,
                self.user_messages,
                prose_model="prose-model",
                prose_system=webhook.SYSTEM_PROMPT,
                prose_max_tokens=512,
                machine_model="machine-model",
                generation="0x00000001",
            )

        self.assertEqual(content, "/peek 0000 10")
        self.assertEqual(call_mock.call_count, 4)
        self.assertIn(
            "your last operator-facing reply was invalid",
            call_mock.call_args_list[3].args[0][-1]["content"],
        )


class AnthropicBalanceFallbackTests(unittest.TestCase):
    def test_missing_admin_key_returns_graceful_message(self) -> None:
        with mock.patch.object(webhook, "anthropic_admin_key", return_value=""), mock.patch.object(
            webhook,
            "request_with_tls_retry",
            side_effect=AssertionError("network call should not happen without an admin key"),
        ):
            content = webhook.fetch_anthropic_balance_summary()

        self.assertEqual(
            content,
            "Anthropic admin key not configured; balance summary unavailable.",
        )


class ChatSessionResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_patch = mock.patch.object(webhook, "persist_sessions", return_value=None)
        self.state_patch.start()
        webhook.SESSION_STATE.clear()

    def tearDown(self) -> None:
        webhook.SESSION_STATE.clear()
        self.state_patch.stop()

    def test_fresh_chat_revives_retired_session(self) -> None:
        session = webhook.make_session("old goal")
        session["active"] = False
        session["history"] = [{"role": "user", "content": "old"}]
        session["steps"] = 5
        webhook.SESSION_STATE["chat-0001"] = session

        revived = webhook.resolve_chat_session("chat-0001", fresh_chat=True)

        self.assertTrue(revived["active"])
        self.assertEqual(revived["history"], [])
        self.assertEqual(revived["steps"], 0)
        self.assertEqual(revived["goal"], "old goal")

    def test_non_fresh_chat_reuses_active_session(self) -> None:
        session = webhook.make_session("keep context")
        session["history"] = [{"role": "user", "content": "peek first"}]
        webhook.SESSION_STATE["chat-0002"] = session

        resolved = webhook.resolve_chat_session("chat-0002", fresh_chat=False)

        self.assertIs(resolved, session)
        self.assertEqual(resolved["history"], [{"role": "user", "content": "peek first"}])


class ChatAndHostRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.persist_patch = mock.patch.object(webhook, "persist_sessions", return_value=None)
        self.persist_patch.start()
        webhook.SESSION_STATE.clear()

    def tearDown(self) -> None:
        webhook.SESSION_STATE.clear()
        self.persist_patch.stop()

    def test_host_retire_session_returns_host_request_reason(self) -> None:
        webhook.SESSION_STATE["chat-0003"] = webhook.make_session()
        payload = {"action": "retire-session", "session": "chat-0003"}

        with mock.patch.object(webhook, "request", types.SimpleNamespace(get_json=lambda silent=True: payload)), mock.patch.object(
            webhook,
            "jsonify",
            side_effect=lambda data: data,
        ):
            data, status = webhook.host()

        self.assertEqual(status, 200)
        self.assertEqual(data["retired_reason"], "host-request")
        self.assertTrue(data["retired"])

    def test_host_git_sync_returns_commit_result(self) -> None:
        payload = {"action": "git-sync", "paths": ["boot/stage2.asm"]}

        with mock.patch.object(webhook, "request", types.SimpleNamespace(get_json=lambda silent=True: payload)), mock.patch.object(
            webhook,
            "jsonify",
            side_effect=lambda data: data,
        ), mock.patch.object(
            webhook,
            "commit_and_sync",
            return_value={
                "changed": True,
                "commit_message": "1700000000",
                "branch": "main",
                "message": "committed and pushed 1700000000",
                "paths": ["boot/stage2.asm"],
            },
        ) as sync_mock:
            data = webhook.host()

        self.assertEqual(data["action"], "git-sync")
        self.assertEqual(data["commit_message"], "1700000000")
        sync_mock.assert_called_once_with(paths=["boot/stage2.asm"])

    def test_step_session_git_sync_uses_reserved_session_name(self) -> None:
        payload = {"action": "step-session", "session": webhook.GIT_SYNC_SESSION, "prompt": ""}

        with mock.patch.object(webhook, "request", types.SimpleNamespace(get_json=lambda silent=True: payload)), mock.patch.object(
            webhook,
            "jsonify",
            side_effect=lambda data: data,
        ), mock.patch.object(
            webhook,
            "commit_and_sync",
            return_value={
                "changed": False,
                "commit_message": "",
                "branch": "",
                "message": "no staged changes to commit",
                "paths": [],
            },
        ) as sync_mock:
            data = webhook.host()

        self.assertEqual(data["action"], "git-sync")
        self.assertEqual(data["session"], webhook.GIT_SYNC_SESSION)
        sync_mock.assert_called_once_with()

    def test_chat_route_marks_kill_self_reason(self) -> None:
        payload = {"prompt": "halt yourself", "session": "chat-0004", "fresh_chat": True}
        session = webhook.make_session()

        with mock.patch.object(webhook, "request", types.SimpleNamespace(get_json=lambda silent=True: payload)), mock.patch.object(
            webhook,
            "jsonify",
            side_effect=lambda data: data,
        ), mock.patch.object(
            webhook,
            "resolve_chat_session",
            return_value=session,
        ), mock.patch.object(
            webhook,
            "apply_model_turn",
            return_value=("/kill-self", True),
        ):
            data = webhook.chat()

        self.assertEqual(data["retired_reason"], "kill-self")
        self.assertTrue(data["retired"])
        self.assertEqual(data["session"], "chat-0004")


class PromptSurfaceTests(unittest.TestCase):
    def test_system_prompt_mentions_ramlist_and_peek(self) -> None:
        self.assertIn("/ramlist", webhook.SYSTEM_PROMPT)
        self.assertIn("/peek", webhook.SYSTEM_PROMPT)
        self.assertIn("/stream", webhook.SYSTEM_PROMPT)
        self.assertIn("hardware-state questions", webhook.SYSTEM_PROMPT)

    def test_kernel_commands_accept_ramlist(self) -> None:
        self.assertIn("ramlist", webhook.KERNEL_COMMANDS)

    def test_without_patching_phrase_is_not_treated_as_edit_request(self) -> None:
        self.assertFalse(
            webhook.operator_requests_code_edit(
                "Probe current BIOS video mode without patching anything."
            )
        )


if __name__ == "__main__":
    unittest.main()
