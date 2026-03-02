#!/usr/bin/env python3
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable


class GitSyncDebouncer:
    def __init__(
        self,
        sync_callback: Callable[[list[str]], dict],
        log_callback: Callable[[str], None],
        *,
        debounce_seconds: float = 3.0,
    ) -> None:
        self._sync_callback = sync_callback
        self._log_callback = log_callback
        self._debounce_seconds = debounce_seconds
        self._lock = threading.Lock()
        self._pending_paths: set[str] = set()
        self._timer: threading.Timer | None = None

    def note_changed_paths(self, paths: list[str]) -> None:
        normalized = [str(Path(path)) for path in paths if str(path).strip()]
        if not normalized:
            return
        with self._lock:
            self._pending_paths.update(normalized)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_seconds, self._flush_from_timer)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            paths = sorted(self._pending_paths)
            self._pending_paths.clear()
        if not paths:
            return
        self._run_sync(paths)

    def close(self) -> None:
        self.flush()

    def _flush_from_timer(self) -> None:
        with self._lock:
            self._timer = None
            paths = sorted(self._pending_paths)
            self._pending_paths.clear()
        if not paths:
            return
        self._run_sync(paths)

    def _run_sync(self, paths: list[str]) -> None:
        try:
            result = self._sync_callback(paths)
            self._log_callback(result.get("message", "git sync completed"))
        except Exception as exc:  # noqa: BLE001
            self._log_callback(f"git sync error: {exc}")
