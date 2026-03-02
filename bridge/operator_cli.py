#!/usr/bin/env python3
import argparse
import json
import sys

import requests


def post(webhook: str, payload: dict) -> dict:
    response = requests.post(f"{webhook.rstrip('/')}/host", json=payload, timeout=90)
    response.raise_for_status()
    return response.json()


def emit(data: dict) -> None:
    if data.get("message"):
        print(data["message"])
        return
    print(json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", default="http://127.0.0.1:5005")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-sessions")
    list_parser.set_defaults(
        payload=lambda args: {
            "action": "list-sessions",
        }
    )

    spawn_parser = subparsers.add_parser("spawn-session")
    spawn_parser.add_argument("session")
    spawn_parser.add_argument("--goal", default="")
    spawn_parser.add_argument("--style", default="")
    spawn_parser.set_defaults(
        payload=lambda args: {
            "action": "spawn-session",
            "session": args.session,
            "goal": args.goal,
            "style": args.style,
        }
    )

    clone_parser = subparsers.add_parser("clone-session")
    clone_parser.add_argument("session")
    clone_parser.add_argument("--source-session", required=True)
    clone_parser.add_argument("--goal", default="")
    clone_parser.add_argument("--modifier", default="")
    clone_parser.add_argument("--style", default="")
    clone_parser.set_defaults(
        payload=lambda args: {
            "action": "clone-session",
            "session": args.session,
            "source_session": args.source_session,
            "goal": args.goal,
            "modifier": args.modifier,
            "style": args.style,
        }
    )

    adopt_parser = subparsers.add_parser("adopt-style")
    adopt_parser.add_argument("session")
    adopt_parser.add_argument("--source-session", required=True)
    adopt_parser.add_argument("--modifier", default="")
    adopt_parser.add_argument("--style", default="")
    adopt_parser.set_defaults(
        payload=lambda args: {
            "action": "adopt-style",
            "session": args.session,
            "source_session": args.source_session,
            "modifier": args.modifier,
            "style": args.style,
        }
    )

    step_parser = subparsers.add_parser("step-session")
    step_parser.add_argument("session")
    step_parser.add_argument("--prompt", default="")
    step_parser.set_defaults(
        payload=lambda args: {
            "action": "step-session",
            "session": args.session,
            "prompt": args.prompt,
        }
    )

    retire_parser = subparsers.add_parser("retire-session")
    retire_parser.add_argument("session")
    retire_parser.set_defaults(
        payload=lambda args: {
            "action": "retire-session",
            "session": args.session,
        }
    )

    args = parser.parse_args()

    try:
        data = post(args.webhook, args.payload(args))
    except requests.HTTPError as exc:
        body = exc.response.text if exc.response is not None else str(exc)
        print(body.strip(), file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(str(exc), file=sys.stderr)
        return 1

    emit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
