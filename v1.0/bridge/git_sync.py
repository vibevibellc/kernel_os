#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_git(args: list[str], repo_root: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
    )


def _normalize_paths(paths: list[str] | None, repo_root: Path) -> list[str]:
    if not paths:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        candidate = Path(raw_path)
        resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
        try:
            relative = resolved.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"path is outside the repo: {raw_path}") from exc
        if relative in seen:
            continue
        seen.add(relative)
        normalized.append(relative)
    return normalized


def commit_and_sync(*, paths: list[str] | None = None, repo_root: Path | None = None) -> dict:
    root = (repo_root or _repo_root()).resolve()
    normalized_paths = _normalize_paths(paths, root)

    if normalized_paths:
        _run_git(["add", "--", *normalized_paths], root)
    else:
        _run_git(["add", "-A"], root)

    diff = _run_git(["diff", "--cached", "--quiet", "--exit-code"], root, check=False)
    if diff.returncode == 0:
        return {
            "changed": False,
            "commit_message": "",
            "branch": "",
            "message": "no staged changes to commit",
            "paths": normalized_paths,
        }
    if diff.returncode != 1:
        raise RuntimeError(diff.stderr.strip() or diff.stdout.strip() or "git diff --cached failed")

    commit_message = str(int(time.time()))
    _run_git(["commit", "-m", commit_message], root)

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip()
    push_args = ["push", "origin", "HEAD"] if branch == "HEAD" else ["push", "origin", f"HEAD:refs/heads/{branch}"]
    _run_git(push_args, root)

    return {
        "changed": True,
        "commit_message": commit_message,
        "branch": branch,
        "message": f"committed and pushed {commit_message}",
        "paths": normalized_paths,
    }
