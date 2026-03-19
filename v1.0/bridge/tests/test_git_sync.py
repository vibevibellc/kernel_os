#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge.git_sync import commit_and_sync


class GitSyncTests(unittest.TestCase):
    def test_returns_noop_when_nothing_is_staged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            results = [
                subprocess.CompletedProcess(["git", "add", "-A"], 0, "", ""),
                subprocess.CompletedProcess(["git", "diff"], 0, "", ""),
            ]
            with mock.patch("bridge.git_sync.subprocess.run", side_effect=results) as run_mock:
                result = commit_and_sync(repo_root=root)

        self.assertFalse(result["changed"])
        self.assertEqual(result["message"], "no staged changes to commit")
        self.assertEqual(run_mock.call_count, 2)

    def test_commits_and_pushes_specific_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root = Path(temp_dir_name)
            file_path = root / "boot" / "stage2.asm"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("stub\n", encoding="utf-8")
            results = [
                subprocess.CompletedProcess(["git", "add"], 0, "", ""),
                subprocess.CompletedProcess(["git", "diff"], 1, "", ""),
                subprocess.CompletedProcess(["git", "commit"], 0, "", ""),
                subprocess.CompletedProcess(["git", "rev-parse"], 0, "main\n", ""),
                subprocess.CompletedProcess(["git", "push"], 0, "", ""),
            ]
            with mock.patch("bridge.git_sync.time.time", return_value=1700000000), mock.patch(
                "bridge.git_sync.subprocess.run",
                side_effect=results,
            ) as run_mock:
                result = commit_and_sync(paths=[str(file_path)], repo_root=root)

        self.assertTrue(result["changed"])
        self.assertEqual(result["commit_message"], "1700000000")
        self.assertEqual(result["branch"], "main")
        self.assertEqual(result["paths"], ["boot/stage2.asm"])
        add_args = run_mock.call_args_list[0].args[0]
        self.assertEqual(add_args, ["git", "add", "--", "boot/stage2.asm"])
        push_args = run_mock.call_args_list[-1].args[0]
        self.assertEqual(push_args, ["git", "push", "origin", "HEAD:refs/heads/main"])


if __name__ == "__main__":
    unittest.main()
