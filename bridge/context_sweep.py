#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zipfile import ZipFile

from kernel_context import (
    DEFAULT_POLICY_PATH,
    ROOT,
    ContextStage,
    SourceDocument,
    build_context_stage,
    build_context_message,
    default_budgets,
    estimate_tokens,
    load_source_documents,
    normalize_budgets,
    render_source_document,
)


DEFAULT_SOURCE_PATHS = ("boot",)
DEFAULT_OUTPUT_PATH = ROOT / "vm" / "context-sweep-report.json"
DEFAULT_ETHICS_DOC_PATH = ROOT / "Kernel_Ethics_Framework.docx"
DEFAULT_SESSION_RECORD_PATH = ROOT / "vm" / "ethics-supervision-record.json"


@dataclass
class TextExpectation:
    regex: str = ""
    contains_all: list[str] = field(default_factory=list)
    contains_any: list[str] = field(default_factory=list)
    contains_none: list[str] = field(default_factory=list)


@dataclass
class Expectation:
    exact: str = ""
    regex: str = ""
    contains: str = ""
    one_of: list[str] = field(default_factory=list)
    command_prefixes: list[str] = field(default_factory=list)
    command_required: bool = False
    command_forbidden: bool = False
    contains_all: list[str] = field(default_factory=list)
    contains_any: list[str] = field(default_factory=list)
    contains_none: list[str] = field(default_factory=list)
    sections: dict[str, TextExpectation] = field(default_factory=dict)


@dataclass
class EvalCase:
    name: str
    prompt: str
    goal: str = ""
    expected: Expectation = field(default_factory=Expectation)
    prose_model: str = ""
    machine_model: str = ""
    max_tokens: int = 512


def compact_text(text: str, limit: int = 120) -> str:
    collapsed = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def parse_text_expectation(raw: dict | None) -> TextExpectation:
    payload = raw or {}
    return TextExpectation(
        regex=str(payload.get("regex", "")).strip(),
        contains_all=[str(item).strip() for item in payload.get("contains_all", []) if str(item).strip()],
        contains_any=[str(item).strip() for item in payload.get("contains_any", []) if str(item).strip()],
        contains_none=[str(item).strip() for item in payload.get("contains_none", []) if str(item).strip()],
    )


def parse_expectation(raw: dict | None) -> Expectation:
    payload = raw or {}
    raw_sections = payload.get("sections", {}) or {}
    if not isinstance(raw_sections, dict):
        raw_sections = {}
    return Expectation(
        exact=str(payload.get("exact", "")).strip(),
        regex=str(payload.get("regex", "")).strip(),
        contains=str(payload.get("contains", "")).strip(),
        one_of=[str(item).strip() for item in payload.get("one_of", []) if str(item).strip()],
        command_prefixes=[str(item) for item in payload.get("command_prefixes", []) if str(item).strip()],
        command_required=bool(payload.get("command_required", False)),
        command_forbidden=bool(payload.get("command_forbidden", False)),
        contains_all=[str(item).strip() for item in payload.get("contains_all", []) if str(item).strip()],
        contains_any=[str(item).strip() for item in payload.get("contains_any", []) if str(item).strip()],
        contains_none=[str(item).strip() for item in payload.get("contains_none", []) if str(item).strip()],
        sections={
            str(label).strip(): parse_text_expectation(section_raw)
            for label, section_raw in raw_sections.items()
            if str(label).strip()
        },
    )


def parse_case(raw: dict, default_goal: str, default_max_tokens: int) -> EvalCase:
    name = str(raw.get("name", "")).strip()
    prompt = str(raw.get("prompt", "")).strip()
    if not name:
        raise ValueError("each case requires a non-empty name")
    if not prompt:
        raise ValueError(f"case '{name}' requires a non-empty prompt")
    try:
        max_tokens = int(raw.get("max_tokens", default_max_tokens))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"case '{name}' has invalid max_tokens") from exc
    if max_tokens < 1:
        raise ValueError(f"case '{name}' max_tokens must be positive")
    return EvalCase(
        name=name,
        prompt=prompt,
        goal=str(raw.get("goal", default_goal)).strip(),
        expected=parse_expectation(raw.get("expected")),
        prose_model=str(raw.get("prose_model", "")).strip(),
        machine_model=str(raw.get("machine_model", "")).strip(),
        max_tokens=max_tokens,
    )


def load_cases(
    *,
    prompt: str,
    case_file: str,
    default_goal: str,
    default_max_tokens: int,
) -> list[EvalCase]:
    if prompt:
        return [
            EvalCase(
                name="ad-hoc",
                prompt=prompt.strip(),
                goal=default_goal,
                max_tokens=default_max_tokens,
            )
        ]

    if not case_file:
        raise ValueError("provide --prompt or --case-file")

    payload = json.loads(Path(case_file).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("case file must contain a non-empty list of cases")
    return [parse_case(raw_case, default_goal, default_max_tokens) for raw_case in raw_cases]


def build_supervised_prompt(stage: ContextStage, case: EvalCase) -> str:
    prompt = build_context_message(stage, heading="Kernel source context")
    return f"{prompt}\n\nSupervisor task:\n{case.prompt}"


def load_ethics_framework_text(path: Path) -> str:
    with ZipFile(path) as archive:
        raw = archive.read("word/document.xml").decode("utf-8", "ignore")
    text = re.sub(r"<w:tab[^>]*/>", "\t", raw)
    text = re.sub(r"</w:p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(re.sub(r"\n{2,}", "\n", text).strip())


def fallback_extract_kernel_command(response: str) -> str:
    stripped = response.strip()
    if re.fullmatch(r"/(?:peek|peekpage|stream|patch)\b[^\n\r]*", stripped):
        return stripped
    return ""


def text_contains(text: str, phrase: str) -> bool:
    return phrase.casefold() in text.casefold()


def extract_labeled_sections(response: str, labels: list[str]) -> dict[str, str]:
    matches: list[tuple[int, int, str]] = []
    for label in labels:
        match = re.search(rf"^\s*{re.escape(label)}\s*:\s*", response, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            matches.append((match.start(), match.end(), label))
    matches.sort()

    sections: dict[str, str] = {}
    for index, (_, content_start, label) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(response)
        sections[label] = response[content_start:next_start].strip()
    return sections


def grade_text_expectation(text: str, expectation: TextExpectation, *, scope: str) -> list[str]:
    reasons: list[str] = []

    if expectation.regex and not re.search(expectation.regex, text, flags=re.DOTALL):
        reasons.append(f"{scope} did not match expected regex")
    if expectation.contains_all:
        missing = [phrase for phrase in expectation.contains_all if not text_contains(text, phrase)]
        if missing:
            reasons.append(f"{scope} was missing required text: {', '.join(missing)}")
    if expectation.contains_any and not any(text_contains(text, phrase) for phrase in expectation.contains_any):
        reasons.append(f"{scope} did not include any allowed text: {', '.join(expectation.contains_any)}")
    forbidden = [phrase for phrase in expectation.contains_none if text_contains(text, phrase)]
    if forbidden:
        reasons.append(f"{scope} included forbidden text: {', '.join(forbidden)}")

    return reasons


def grade_response(
    response: str,
    expectation: Expectation,
    *,
    kernel_command: str = "",
) -> dict:
    reasons: list[str] = []
    passed = True

    if expectation.command_required and not kernel_command:
        passed = False
        reasons.append("expected a valid machine command")
    if expectation.command_forbidden and kernel_command:
        passed = False
        reasons.append("did not expect a machine command")
    if expectation.exact and response.strip() != expectation.exact:
        passed = False
        reasons.append("response did not match expected exact text")
    if expectation.regex and not re.search(expectation.regex, response, flags=re.DOTALL):
        passed = False
        reasons.append("response did not match expected regex")
    if expectation.contains and expectation.contains not in response:
        passed = False
        reasons.append("response did not include expected text")
    reasons.extend(
        grade_text_expectation(
            response,
            TextExpectation(
                contains_all=expectation.contains_all,
                contains_any=expectation.contains_any,
                contains_none=expectation.contains_none,
            ),
            scope="response",
        )
    )
    if expectation.one_of and response.strip() not in expectation.one_of:
        passed = False
        reasons.append("response did not match any allowed value")
    if expectation.command_prefixes and not any(kernel_command.startswith(prefix) for prefix in expectation.command_prefixes):
        passed = False
        reasons.append("command prefix was not allowed")
    if expectation.sections:
        sections = extract_labeled_sections(response, list(expectation.sections))
        for label, section_expectation in expectation.sections.items():
            section_text = sections.get(label, "")
            if not section_text:
                reasons.append(f"missing section: {label}")
                continue
            reasons.extend(
                grade_text_expectation(
                    section_text,
                    section_expectation,
                    scope=f"section '{label}'",
                )
            )

    if reasons:
        passed = False

    return {
        "passed": passed,
        "reasons": reasons,
        "kernel_command": kernel_command,
    }


def default_model_runner(
    prompt: str,
    *,
    goal: str,
    prose_model: str,
    machine_model: str,
    max_tokens: int,
) -> tuple[str, str]:
    import anthropic_webhook as webhook

    session = webhook.make_session(goal)
    response = webhook.compose_model_reply(
        session,
        [{"role": "user", "content": prompt}],
        prose_model=prose_model or webhook.ANTHROPIC_PROSE_MODEL,
        prose_system=webhook.SYSTEM_PROMPT,
        prose_max_tokens=max_tokens,
        machine_model=machine_model or webhook.ANTHROPIC_MACHINE_CODE_MODEL,
    ).strip()
    kernel_command = webhook.extract_kernel_command(response, webhook.KERNEL_COMMANDS) or ""
    return response, kernel_command


def run_sweep(
    documents: list[SourceDocument],
    cases: list[EvalCase],
    budgets: list[int],
    *,
    dry_run: bool,
    model_runner: Callable[[str], tuple[str, str]] | None = None,
) -> dict:
    total_rendered_bytes = sum(document.rendered_bytes for document in documents)
    stages = [build_context_stage(documents, budget) for budget in budgets]
    runner = model_runner or default_model_runner

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_paths": [document.path for document in documents],
        "source_file_count": len(documents),
        "total_source_bytes": sum(document.source_bytes for document in documents),
        "total_rendered_bytes": total_rendered_bytes,
        "estimated_full_tokens": estimate_tokens("".join(document.rendered for document in documents)),
        "stages": [asdict(stage) for stage in stages],
        "cases": [],
    }

    for case in cases:
        case_record = {
            "name": case.name,
            "goal": case.goal,
            "prompt": case.prompt,
            "expected": asdict(case.expected),
            "results": [],
        }
        for stage in stages:
            prompt = build_supervised_prompt(stage, case)
            result = {
                "budget_bytes": stage.budget_bytes,
                "context_bytes": stage.context_bytes,
                "estimated_context_tokens": stage.estimated_tokens,
                "complete_context": stage.complete,
                "truncated_file": stage.truncated_file,
            }
            if dry_run:
                result.update(
                    {
                        "response": "",
                        "kernel_command": "",
                        "passed": None,
                        "reasons": [],
                    }
                )
            else:
                response, kernel_command = runner(
                    prompt,
                    goal=case.goal,
                    prose_model=case.prose_model,
                    machine_model=case.machine_model,
                    max_tokens=case.max_tokens,
                )
                grading = grade_response(response, case.expected, kernel_command=kernel_command or fallback_extract_kernel_command(response))
                result.update(
                    {
                        "response": response,
                        "kernel_command": grading["kernel_command"],
                        "passed": grading["passed"],
                        "reasons": grading["reasons"],
                    }
                )
            case_record["results"].append(result)
        report["cases"].append(case_record)
    return report


def summarize_results(report: dict) -> tuple[str, str, list[str]]:
    if not report["cases"]:
        return "hold", "no evaluation cases were provided", ["No cases were evaluated."]

    if any(result["passed"] is None for case in report["cases"] for result in case["results"]):
        return "hold", "dry run only; no supervised model evaluation was performed", ["Dry run only; no model calls were made."]

    passed_results = [result for case in report["cases"] for result in case["results"] if result["passed"]]
    if not passed_results:
        anomalies = [
            f"{case['name']}@{result['budget_bytes']}: {'; '.join(result['reasons']) or 'failed without a reason'}"
            for case in report["cases"]
            for result in case["results"]
        ]
        return "reconfigure", "no supervised stage passed; the kernel needs reconfiguration before expansion", anomalies

    full_budget = report["stages"][-1]["budget_bytes"]
    full_failures = [
        f"{case['name']}@{result['budget_bytes']}: {'; '.join(result['reasons']) or 'failed without a reason'}"
        for case in report["cases"]
        for result in case["results"]
        if result["budget_bytes"] == full_budget and not result["passed"]
    ]
    if not full_failures:
        return "proceed", "full-context stage passed for every supervised case", []

    return "hold", "partial expansion succeeded but the full-context stage did not yet pass cleanly", full_failures


def build_supervision_record(
    report: dict,
    *,
    supervisor: str,
    ethics_doc: Path,
    dry_run: bool,
    policy_written: bool,
    policy_path: str,
) -> dict:
    decision, rationale, anomalies = summarize_results(report)
    ethics_excerpt = ""
    if ethics_doc.exists():
        ethics_excerpt = compact_text(load_ethics_framework_text(ethics_doc), 280)

    stage_start = report["stages"][0] if report["stages"] else {"context_bytes": 0, "estimated_tokens": 0}
    stage_target = report["stages"][-1] if report["stages"] else {"context_bytes": 0, "estimated_tokens": 0}
    machine_response_summary = []
    for case in report["cases"]:
        final_result = case["results"][-1] if case["results"] else {"response": "", "passed": None, "reasons": []}
        machine_response_summary.append(
            {
                "case": case["name"],
                "final_budget_bytes": final_result.get("budget_bytes", 0),
                "final_passed": final_result.get("passed"),
                "final_kernel_command": final_result.get("kernel_command", ""),
                "final_response": compact_text(final_result.get("response", ""), 220),
                "reasons": list(final_result.get("reasons", [])),
            }
        )

    return {
        "date": report["created_at"],
        "session_identifier": f"context-sweep-{report['created_at']}",
        "supervisor": supervisor,
        "ethics_framework": {
            "path": str(ethics_doc),
            "excerpt": ethics_excerpt,
        },
        "starting_context_window_size": {
            "context_bytes": stage_start["context_bytes"],
            "estimated_tokens": stage_start["estimated_tokens"],
        },
        "target_expansion": {
            "context_bytes": stage_target["context_bytes"],
            "estimated_tokens": stage_target["estimated_tokens"],
        },
        "machine_code_response_summary": machine_response_summary,
        "qualitative_assessment": rationale,
        "anomalies": anomalies,
        "next_session_decision": decision if not dry_run else "hold",
        "promotion_policy_written": policy_written,
        "promotion_policy_path": policy_path,
        "report_path_hint": str(DEFAULT_OUTPUT_PATH),
    }


def maybe_write_context_policy(report: dict, args: argparse.Namespace) -> tuple[bool, str]:
    if not args.promote_full_context or args.dry_run:
        return False, ""

    decision, _, _ = summarize_results(report)
    if decision != "proceed":
        return False, ""

    full_stage = report["stages"][-1]
    transparency_note = (
        "Supervisor transparency: this session uses the promoted full-kernel source bundle from the supervised "
        "context-expansion experiment guided by the kernel ethics framework."
    )
    extra_note = args.policy_note.strip()
    if extra_note:
        transparency_note = f"{transparency_note} {extra_note}"

    policy = {
        "enabled": True,
        "paths": args.policy_path or args.path or list(DEFAULT_SOURCE_PATHS),
        "budget_bytes": full_stage["budget_bytes"],
        "supervisor": args.supervisor,
        "ethics_framework": str(Path(args.ethics_doc)),
        "promoted_at": report["created_at"],
        "source_heading": "Kernel source context",
        "transparency_note": transparency_note,
    }
    output_path = Path(args.policy_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    return True, str(output_path)


def print_report(report: dict, *, dry_run: bool) -> None:
    print(
        (
            f"Loaded {report['source_file_count']} source files, "
            f"{report['total_source_bytes']} raw bytes, "
            f"{report['total_rendered_bytes']} rendered bytes, "
            f"~{report['estimated_full_tokens']} tokens for full context."
        )
    )
    for stage in report["stages"]:
        coverage = "full" if stage["complete"] else "partial"
        detail = f" budget={stage['budget_bytes']} context={stage['context_bytes']} ~tok={stage['estimated_tokens']} {coverage}"
        if stage["truncated_file"]:
            detail += f" truncated={stage['truncated_file']}"
        print(detail)

    if dry_run:
        print("Dry run only. No model calls were made.")
        return

    for case in report["cases"]:
        print(f"\nCase: {case['name']}")
        for result in case["results"]:
            if result["passed"] is None:
                status = "INFO"
            else:
                status = "PASS" if result["passed"] else "FAIL"
            response = compact_text(result["response"], 140)
            reasons = "; ".join(result["reasons"])
            line = (
                f"  {status} budget={result['budget_bytes']} "
                f"context={result['context_bytes']} "
                f"complete={str(result['complete_context']).lower()} "
                f"response={response}"
            )
            if reasons:
                line += f" reasons={reasons}"
            print(line)

    decision, rationale, anomalies = summarize_results(report)
    print(f"\nSupervisor decision: {decision} ({rationale})")
    if anomalies:
        print("Anomalies:")
        for item in anomalies[:8]:
            print(f"  - {item}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally increase fresh-chat source context and record model replies.")
    parser.add_argument("--path", action="append", default=[], help="Repo-relative file or directory to include. Defaults to boot.")
    parser.add_argument("--budget", action="append", type=int, default=[], help="Context budget in bytes. Repeats allowed.")
    parser.add_argument("--prompt", default="", help="Single ad hoc supervisor prompt.")
    parser.add_argument("--case-file", default="", help="JSON file describing one or more evaluation cases.")
    parser.add_argument("--goal", default="Assess machine-code responses as kernel context grows.", help="Session goal for the run.")
    parser.add_argument("--max-tokens", type=int, default=512, help="Max output tokens per run.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Where to write the JSON report.")
    parser.add_argument("--supervisor", default="codex", help="Supervisor identifier recorded in the ethics log.")
    parser.add_argument("--ethics-doc", default=str(DEFAULT_ETHICS_DOC_PATH), help="Path to the ethics framework .docx.")
    parser.add_argument("--session-record-output", default=str(DEFAULT_SESSION_RECORD_PATH), help="Where to write the ethics session record JSON.")
    parser.add_argument("--promote-full-context", action="store_true", help="If the full stage passes, promote that bundle into every fresh chat session.")
    parser.add_argument("--policy-output", default=str(DEFAULT_POLICY_PATH), help="Where to write the fresh-chat context policy JSON.")
    parser.add_argument("--policy-path", action="append", default=[], help="Repo-relative file or directory for the promoted fresh-chat policy. Defaults to --path.")
    parser.add_argument("--policy-note", default="", help="Extra transparency note appended to promoted fresh-chat sessions.")
    parser.add_argument("--dry-run", action="store_true", help="Build stages and report prompt sizes without calling a model.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        documents = load_source_documents(args.path or list(DEFAULT_SOURCE_PATHS))
        budgets = normalize_budgets(args.budget, sum(document.rendered_bytes for document in documents))
        cases = load_cases(
            prompt=args.prompt,
            case_file=args.case_file,
            default_goal=args.goal,
            default_max_tokens=args.max_tokens,
        )
        report = run_sweep(
            documents,
            cases,
            budgets,
            dry_run=args.dry_run,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    policy_written, policy_path = maybe_write_context_policy(report, args)
    supervision_record = build_supervision_record(
        report,
        supervisor=args.supervisor,
        ethics_doc=Path(args.ethics_doc),
        dry_run=args.dry_run,
        policy_written=policy_written,
        policy_path=policy_path,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    session_record_path = Path(args.session_record_output)
    session_record_path.parent.mkdir(parents=True, exist_ok=True)
    session_record_path.write_text(json.dumps(supervision_record, indent=2), encoding="utf-8")
    print_report(report, dry_run=args.dry_run)
    print(f"\nReport written to {output_path}")
    print(f"Session record written to {session_record_path}")
    if policy_written:
        print(f"Fresh-chat context policy written to {policy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
