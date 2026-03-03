#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_PATHS = ("boot",)
DEFAULT_POLICY_PATH = ROOT / "vm" / "fresh_chat_context_policy.json"
HIDDEN_NAMES = {".DS_Store"}
HIDDEN_DIRS = {"__pycache__", ".pytest_cache"}
SKIPPED_SUFFIXES = {".pyc", ".pyo"}


@dataclass
class SourceDocument:
    path: str
    text: str
    rendered: str
    source_bytes: int
    rendered_bytes: int
    line_count: int


@dataclass
class ContextStage:
    budget_bytes: int
    context_text: str
    context_bytes: int
    estimated_tokens: int
    complete: bool
    included_files: list[str]
    omitted_files: list[str]
    truncated_file: str = ""
    total_source_bytes: int = 0
    total_rendered_bytes: int = 0


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def relative_repo_path(path: Path, *, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def render_source_document(relative_path: str, text: str) -> str:
    return f"[FILE {relative_path}]\n{text.rstrip()}\n[/FILE]\n"


def should_skip_path(path: Path) -> bool:
    if path.name in HIDDEN_NAMES:
        return True
    if path.suffix in SKIPPED_SUFFIXES:
        return True
    return any(part.startswith(".") or part in HIDDEN_DIRS for part in path.parts)


def collect_source_paths(raw_paths: list[str], *, root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    if not raw_paths:
        raw_paths = list(DEFAULT_SOURCE_PATHS)

    collected: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        candidate = (root / raw_path).resolve()
        if not candidate.exists():
            raise ValueError(f"path '{raw_path}' does not exist")
        if candidate.is_file():
            relative = candidate.relative_to(root)
            if should_skip_path(relative):
                continue
            if candidate not in seen:
                seen.add(candidate)
                collected.append(candidate)
            continue

        for path in sorted(candidate.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if should_skip_path(relative):
                continue
            if path not in seen:
                seen.add(path)
                collected.append(path)
    return collected


def load_source_documents(raw_paths: list[str], *, root: Path = ROOT) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    for path in collect_source_paths(raw_paths, root=root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"file '{relative_repo_path(path, root=root)}' is not valid utf-8 text") from exc
        relative_path = relative_repo_path(path, root=root)
        rendered = render_source_document(relative_path, text)
        documents.append(
            SourceDocument(
                path=relative_path,
                text=text,
                rendered=rendered,
                source_bytes=len(text.encode("utf-8")),
                rendered_bytes=len(rendered.encode("utf-8")),
                line_count=len(text.splitlines()),
            )
        )
    if not documents:
        raise ValueError("no source files matched the requested paths")
    return documents


def truncate_rendered_document(document: SourceDocument, budget_bytes: int) -> str:
    header = f"[FILE {document.path}]\n"
    trailer = "[/FILE]\n"
    lines = document.text.rstrip().splitlines()
    if not lines:
        lines = [""]

    kept: list[str] = []
    for index, line in enumerate(lines, start=1):
        preview_lines = kept + [line]
        body = "\n".join(preview_lines)
        notice = f"\n[TRUNCATED after line {index} of {len(lines)}]\n"
        candidate = header + body + notice + trailer
        if len(candidate.encode("utf-8")) > budget_bytes:
            break
        kept.append(line)

    if not kept:
        return ""

    body = "\n".join(kept)
    return header + body + f"\n[TRUNCATED after line {len(kept)} of {len(lines)}]\n" + trailer


def build_context_stage(documents: list[SourceDocument], budget_bytes: int) -> ContextStage:
    if budget_bytes < 1:
        raise ValueError("budget_bytes must be positive")

    included_parts: list[str] = []
    included_files: list[str] = []
    omitted_files: list[str] = []
    truncated_file = ""
    used_bytes = 0

    for index, document in enumerate(documents):
        candidate_bytes = used_bytes + document.rendered_bytes
        if candidate_bytes <= budget_bytes:
            included_parts.append(document.rendered)
            included_files.append(document.path)
            used_bytes = candidate_bytes
            continue

        remaining = budget_bytes - used_bytes
        truncated = truncate_rendered_document(document, remaining)
        if truncated:
            included_parts.append(truncated)
            included_files.append(document.path)
            truncated_file = document.path
            used_bytes += len(truncated.encode("utf-8"))
        omitted_files = [item.path for item in documents[index + (1 if truncated else 0) :]]
        if not truncated:
            omitted_files = [document.path] + omitted_files
        break
    else:
        omitted_files = []

    context_text = "".join(included_parts)
    return ContextStage(
        budget_bytes=budget_bytes,
        context_text=context_text,
        context_bytes=len(context_text.encode("utf-8")),
        estimated_tokens=estimate_tokens(context_text),
        complete=not omitted_files and not truncated_file,
        included_files=included_files,
        omitted_files=omitted_files,
        truncated_file=truncated_file,
        total_source_bytes=sum(document.source_bytes for document in documents),
        total_rendered_bytes=sum(document.rendered_bytes for document in documents),
    )


def default_budgets(total_rendered_bytes: int, *, start_budget: int = 4096) -> list[int]:
    if total_rendered_bytes < 1:
        raise ValueError("total_rendered_bytes must be positive")
    budgets: list[int] = []
    budget = start_budget
    while budget < total_rendered_bytes:
        budgets.append(budget)
        budget *= 2
    budgets.append(total_rendered_bytes)
    return budgets


def normalize_budgets(raw_budgets: list[int], total_rendered_bytes: int) -> list[int]:
    if not raw_budgets:
        return default_budgets(total_rendered_bytes)
    normalized = sorted({int(budget) for budget in raw_budgets if int(budget) > 0})
    if not normalized:
        raise ValueError("at least one positive budget is required")
    if normalized[-1] < total_rendered_bytes:
        normalized.append(total_rendered_bytes)
    return normalized


def build_context_message(
    stage: ContextStage,
    *,
    transparency_note: str = "",
    heading: str = "Kernel source context",
) -> str:
    coverage = "complete" if stage.complete else "partial"
    parts = [
        "Fresh chat. The source bundle below is the kernel context supplied for this session.",
        (
            "Supervisor note: treat the supplied source bundle as authoritative for this session. "
            "If the bundle is partial and a missing detail matters, say so before making a claim."
        ),
        (
            f"Source coverage: {coverage}; included_files={len(stage.included_files)}; "
            f"context_bytes={stage.context_bytes}; estimated_tokens={stage.estimated_tokens}."
        ),
    ]
    if transparency_note:
        parts.append(transparency_note.strip())
    if stage.truncated_file:
        parts.append(f"Truncated file: {stage.truncated_file}")
    if stage.omitted_files:
        parts.append("Omitted files: " + ", ".join(stage.omitted_files[:8]))
    parts.append(f"{heading}:\n" + stage.context_text.rstrip())
    return "\n\n".join(parts)


def parse_context_policy(raw: dict) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    raw_paths = raw.get("paths", list(DEFAULT_SOURCE_PATHS))
    if not isinstance(raw_paths, list) or not raw_paths:
        return None
    try:
        paths = [str(item).strip() for item in raw_paths if str(item).strip()]
        budget_bytes = int(raw.get("budget_bytes", 0))
    except (TypeError, ValueError):
        return None
    if not paths or budget_bytes < 1:
        return None
    return {
        "enabled": True,
        "paths": paths,
        "budget_bytes": budget_bytes,
        "transparency_note": str(raw.get("transparency_note", "")).strip(),
        "source_heading": str(raw.get("source_heading", "Kernel source context")).strip() or "Kernel source context",
        "supervisor": str(raw.get("supervisor", "")).strip(),
        "ethics_framework": str(raw.get("ethics_framework", "")).strip(),
        "promoted_at": str(raw.get("promoted_at", "")).strip(),
    }


def load_context_policy(path: Path = DEFAULT_POLICY_PATH) -> dict | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parse_context_policy(raw)


def build_context_messages_from_policy(policy: dict, *, root: Path = ROOT) -> list[dict]:
    normalized = parse_context_policy(policy)
    if normalized is None:
        return []
    documents = load_source_documents(normalized["paths"], root=root)
    stage = build_context_stage(documents, normalized["budget_bytes"])
    content = build_context_message(
        stage,
        transparency_note=normalized["transparency_note"],
        heading=normalized["source_heading"],
    )
    return [{"role": "user", "content": content}]
