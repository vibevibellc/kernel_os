#!/usr/bin/env python3
from __future__ import annotations

import threading
import time
import unittest

from bridge.git_sync_debounce import GitSyncDebouncer


class GitSyncDebouncerTests(unittest.TestCase):
    def test_manual_flush_batches_paths(self) -> None:
        calls: list[list[str]] = []
        messages: list[str] = []
        debouncer = GitSyncDebouncer(
            lambda paths: calls.append(paths) or {"message": "synced"},
            messages.append,
            debounce_seconds=10.0,
        )

        try:
            debouncer.note_changed_paths(["a", "b"])
            debouncer.note_changed_paths(["b", "c"])
            debouncer.flush()
        finally:
            debouncer.close()

        self.assertEqual(calls, [["a", "b", "c"]])
        self.assertEqual(messages, ["synced"])

    def test_timer_flush_collapses_burst_into_one_sync(self) -> None:
        calls: list[list[str]] = []
        messages: list[str] = []
        synced = threading.Event()

        def sync(paths: list[str]) -> dict:
            calls.append(paths)
            synced.set()
            return {"message": "batched sync"}

        debouncer = GitSyncDebouncer(sync, messages.append, debounce_seconds=0.05)

        try:
            debouncer.note_changed_paths(["a"])
            time.sleep(0.02)
            debouncer.note_changed_paths(["b"])
            self.assertTrue(synced.wait(0.5))
        finally:
            debouncer.close()

        self.assertEqual(calls, [["a", "b"]])
        self.assertEqual(messages, ["batched sync"])


if __name__ == "__main__":
    unittest.main()
