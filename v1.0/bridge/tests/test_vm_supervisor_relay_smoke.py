#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = ROOT / "bridge" / "vm_supervisor_relay_smoke.py"


@unittest.skipUnless(shutil.which("qemu-system-x86_64"), "qemu-system-x86_64 is required")
class SupervisorRelaySmokeTests(unittest.TestCase):
    def test_vm_supervisor_relay_smoke(self) -> None:
        subprocess.run(
            [sys.executable, str(SMOKE_SCRIPT)],
            cwd=ROOT,
            check=True,
            timeout=120,
        )


if __name__ == "__main__":
    unittest.main()
