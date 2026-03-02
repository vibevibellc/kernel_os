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


if __name__ == "__main__":
    unittest.main()
