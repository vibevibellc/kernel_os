#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE_GLOBS = ("boot/*.asm",)
FUNCTION_LINE_LIMIT = 80
MACRO_LINE_LIMIT = 25
WAIT_COUNTER_OPS = {
    "dec",
    "sub",
    "loop",
    "loope",
    "loopne",
    "loopnz",
    "loopz",
}
WAIT_HINTS = ("wait", "poll", "spin", "idle", "halt")
GLOBAL_LABEL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:")
LOCAL_LABEL_RE = re.compile(r"^\s*(\.[A-Za-z_][A-Za-z0-9_]*)\s*:")
CALL_RE = re.compile(r"^\s*call\s+([A-Za-z_][A-Za-z0-9_\.]*)\b", re.IGNORECASE)
SELF_JUMP_TEMPLATE = r"\bj(?:mp|z|nz|c|nc|e|ne|a|ae|b|be|g|ge|l|le|s|ns|o|no|p|pe|po)\b\s+(?:short\s+|near\s+)?{label}\b"
EXTERNAL_WAIT_RE = re.compile(r"\b(?:in|hlt)\b", re.IGNORECASE)
NASM_DIAG_RE = re.compile(r"^(.*?):(\d+)(?::(\d+))?:\s*(warning|error):\s*(.*)$", re.IGNORECASE)
DATA_DIRECTIVE_RE = re.compile(r"^\s*(?:db|dw|dd|dq|dt|do|dy|dz|resb|resw|resd|times)\b", re.IGNORECASE)
NAMED_DATA_DIRECTIVE_RE = re.compile(
    r"^\s*[A-Za-z_\.][A-Za-z0-9_\.]*\s+(?:db|dw|dd|dq|dt|do|dy|dz|resb|resw|resd|times)\b",
    re.IGNORECASE,
)
LEADING_LABEL_RE = re.compile(r"^\s*(?:[A-Za-z_\.][A-Za-z0-9_\.]*:)\s*")


@dataclass
class SourceLine:
    number: int
    raw: str
    code: str


@dataclass
class Diagnostic:
    path: Path
    line: int
    column: int
    severity: str
    code: str
    message: str

    def render(self) -> str:
        rel = self.path.relative_to(ROOT)
        return f"{rel}:{self.line}:{self.column}: {self.severity}: [{self.code}] {self.message}"


def strip_comment(line: str) -> str:
    return line.split(";", 1)[0].rstrip()


def meaningful(code: str) -> bool:
    return bool(code.strip())


def strip_leading_label(code: str) -> str:
    return LEADING_LABEL_RE.sub("", code, count=1)


def is_data_definition(code: str) -> bool:
    stripped = strip_leading_label(code)
    return bool(DATA_DIRECTIVE_RE.match(stripped) or NAMED_DATA_DIRECTIVE_RE.match(code))


def read_lines(path: Path) -> list[SourceLine]:
    return [
        SourceLine(number=index, raw=line.rstrip("\n"), code=strip_comment(line))
        for index, line in enumerate(path.read_text().splitlines(), start=1)
    ]


def find_files(paths: list[str]) -> list[Path]:
    if paths:
        return sorted(ROOT / path for path in paths)

    found: list[Path] = []
    for pattern in DEFAULT_FILE_GLOBS:
        found.extend(sorted(ROOT.glob(pattern)))
    return found


def global_labels(lines: list[SourceLine]) -> list[tuple[int, str]]:
    labels: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        match = GLOBAL_LABEL_RE.match(line.code)
        if match:
            labels.append((idx, match.group(1)))
    return labels


def label_blocks(lines: list[SourceLine], start_idx: int, end_idx: int) -> list[tuple[int, int, str]]:
    labels: list[tuple[int, str]] = []
    for idx in range(start_idx, end_idx + 1):
        match = GLOBAL_LABEL_RE.match(lines[idx].code) or LOCAL_LABEL_RE.match(lines[idx].code)
        if match:
            labels.append((idx, match.group(1)))

    blocks: list[tuple[int, int, str]] = []
    for pos, (idx, name) in enumerate(labels):
        block_end = labels[pos + 1][0] - 1 if pos + 1 < len(labels) else end_idx
        blocks.append((idx, block_end, name))
    return blocks


def function_bounds(lines: list[SourceLine]) -> list[tuple[int, int, str]]:
    globals_ = global_labels(lines)
    blocks: list[tuple[int, int, str]] = []
    for pos, (idx, name) in enumerate(globals_):
        block_end = globals_[pos + 1][0] - 1 if pos + 1 < len(globals_) else len(lines) - 1
        blocks.append((idx, block_end, name))
    return blocks


def has_self_jump(label: str, code_lines: list[str]) -> bool:
    matcher = re.compile(SELF_JUMP_TEMPLATE.format(label=re.escape(label)), re.IGNORECASE)
    for code in code_lines:
        stripped = code.strip().lower()
        if stripped == "jmp $":
            return True
        if matcher.search(code):
            return True
    return False


def has_timeout_counter(code_lines: list[str]) -> bool:
    for code in code_lines:
        op = code.strip().split(maxsplit=1)
        if op and op[0].lower() in WAIT_COUNTER_OPS:
            return True
    return False


def block_looks_like_external_wait(label: str, code_lines: list[str]) -> bool:
    lowered = label.lower().lstrip(".")
    if any(hint in lowered for hint in WAIT_HINTS):
        return True

    for code in code_lines:
        if EXTERNAL_WAIT_RE.search(code):
            return True
        call_match = CALL_RE.match(code)
        if call_match:
            target = call_match.group(1).lower()
            if any(hint in target for hint in WAIT_HINTS):
                return True
    return False


def lint_macros(path: Path, lines: list[SourceLine]) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    idx = 0
    while idx < len(lines):
        code = lines[idx].code.strip().lower()
        if code.startswith("%macro") or code.startswith("%imacro"):
            start = idx
            idx += 1
            while idx < len(lines) and lines[idx].code.strip().lower() != "%endmacro":
                idx += 1
            body = lines[start + 1 : idx]
            count = sum(1 for line in body if meaningful(line.code))
            if count > MACRO_LINE_LIMIT:
                diags.append(
                    Diagnostic(
                        path=path,
                        line=lines[start].number,
                        column=1,
                        severity="warning",
                        code="ASM104",
                        message=f"Macro body is {count} lines; keep macros small and explicit.",
                    )
                )
        idx += 1
    return diags


def lint_functions(path: Path, lines: list[SourceLine]) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for start_idx, end_idx, name in function_bounds(lines):
        block = lines[start_idx : end_idx + 1]
        body = block[1:]
        body_codes = [line.code for line in body if meaningful(line.code)]
        if not body_codes:
            continue
        if all(is_data_definition(code) for code in body_codes):
            continue

        meaningful_count = sum(1 for line in body if meaningful(line.code))
        if meaningful_count > FUNCTION_LINE_LIMIT:
            diags.append(
                Diagnostic(
                    path=path,
                    line=lines[start_idx].number,
                    column=1,
                    severity="warning",
                    code="ASM101",
                    message=f"Function `{name}` is {meaningful_count} lines; split it into smaller routines.",
                )
            )

        for label_idx, label_end, label in label_blocks(lines, start_idx, end_idx):
            code_lines = [line.code for line in lines[label_idx : label_end + 1]]
            if not has_self_jump(label, code_lines):
                continue
            if not block_looks_like_external_wait(label, code_lines):
                continue
            if has_timeout_counter(code_lines):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=lines[label_idx].number,
                    column=1,
                    severity="warning",
                    code="ASM100",
                    message=f"Possible unbounded wait loop at `{label}`; add a timeout counter or an explicit failure path.",
                )
            )

        for line in body:
            if line.code.strip().lower() == "jmp $":
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line.number,
                        column=1,
                        severity="warning",
                        code="ASM102",
                        message="Infinite `jmp $` loop found; prefer a bounded wait or explicit panic path.",
                    )
                )
    return diags


def lint_with_nasm(path: Path) -> list[Diagnostic]:
    command = [
        "nasm",
        "-f",
        "bin",
        "-o",
        "/dev/null",
        "-w+all",
        "-w-reloc-abs-word",
        "-X",
        "gnu",
        str(path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    output = [line for line in (proc.stderr or "").splitlines() if line.strip()]
    diags: list[Diagnostic] = []
    for line in output:
        match = NASM_DIAG_RE.match(line)
        if not match:
            continue
        file_name, line_no, col_no, severity, message = match.groups()
        diag_path = Path(file_name)
        if not diag_path.is_absolute():
            diag_path = (ROOT / diag_path).resolve()
        diags.append(
            Diagnostic(
                path=diag_path,
                line=int(line_no),
                column=int(col_no or "1"),
                severity=severity.lower(),
                code="NASM",
                message=message.strip(),
            )
        )

    if proc.returncode != 0 and not diags:
        diags.append(
            Diagnostic(
                path=path,
                line=1,
                column=1,
                severity="error",
                code="NASM",
                message="Assembler failed without a parseable diagnostic.",
            )
        )
    return diags


def lint_file(path: Path) -> list[Diagnostic]:
    lines = read_lines(path)
    diags = []
    diags.extend(lint_macros(path, lines))
    diags.extend(lint_functions(path, lines))
    diags.extend(lint_with_nasm(path))
    return diags


def collect_diagnostics(files: list[Path]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for path in files:
        diagnostics.extend(lint_file(path.resolve()))
    diagnostics.sort(key=lambda diag: (str(diag.path), diag.line, diag.column, diag.code))
    return diagnostics


def emit_diagnostics(diagnostics: list[Diagnostic]) -> None:
    print("ASM_LINT_BEGIN")
    for diag in diagnostics:
        print(diag.render())
    print("ASM_LINT_END")
    sys.stdout.flush()


def diagnostics_fingerprint(diagnostics: list[Diagnostic]) -> str:
    payload = "\n".join(diag.render() for diag in diagnostics)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_watch(files: list[Path], fail_on_warning: bool, interval: float) -> int:
    last_fingerprint: str | None = None
    last_mtimes: dict[Path, int] = {}

    while True:
        current_mtimes = {}
        for path in files:
            try:
                current_mtimes[path] = path.stat().st_mtime_ns
            except FileNotFoundError:
                current_mtimes[path] = -1

        if current_mtimes != last_mtimes:
            diagnostics = collect_diagnostics(files)
            fingerprint = diagnostics_fingerprint(diagnostics)
            if fingerprint != last_fingerprint:
                emit_diagnostics(diagnostics)
                last_fingerprint = fingerprint
            last_mtimes = current_mtimes

        if fail_on_warning:
            time.sleep(interval)
            continue
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Heuristic lint checks for NASM commandment violations.")
    parser.add_argument("paths", nargs="*", help="ASM files relative to the repo root")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return a non-zero exit code if any warning is emitted")
    parser.add_argument("--watch", action="store_true", help="Watch ASM files and continuously emit diagnostics")
    parser.add_argument("--interval", type=float, default=0.75, help="Polling interval in seconds for --watch")
    args = parser.parse_args()

    files = find_files(args.paths)
    if not files:
        print("asm_lint: no ASM files found", file=sys.stderr)
        return 1

    if args.watch:
        return run_watch(files, args.fail_on_warning, args.interval)

    diagnostics = collect_diagnostics(files)
    for diag in diagnostics:
        print(diag.render())

    has_error = any(diag.severity == "error" for diag in diagnostics)
    has_warning = any(diag.severity == "warning" for diag in diagnostics)
    if has_error:
        return 1
    if args.fail_on_warning and has_warning:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
