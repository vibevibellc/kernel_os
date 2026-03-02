# kernel_os playground

Python + Machine Code

Minimal BIOS playground that boots a two-stage loader on a raw disk image, pairs it with a Flask webhook, and bridges COM1 output to Anthropic-backed supervised sessions.

## Key components

- `boot/stage1.asm`, `boot/stage2.asm`: 512-byte sector loader + real-mode monitor utilities.
- `build/`: prebuilt binaries (`stage1.bin` / `stage2.bin`) written to the disk image.
- `run-vm.sh` & `Makefile`: build, write, and launch helpers for the QEMU image.
- `bridge/`: Flask webhook, serial bridge, and CLI helpers that coordinate Anthropic sessions.
- `vm/os-disk.img`: raw disk that the BIOS loader writes to and boots from.

## Requirements

- Linux/macOS host with `qemu-system-x86_64`, `nasm`, and `python` (3.10+ recommended).
- Python 3 virtual environment (`.venv/`) with the dependencies in `bridge/requirements.txt`.

## Getting started

1. Build and write the boot image:
   ```sh
   make boot
   ```
2. Run with a GUI console:
   ```sh
   make run
   ```
   Headless with serial I/O:
   ```sh
   make run-headless
   ```
   COM1 exposed as a Unix socket for chat automation:
   ```sh
   make run-chat
   ```
3. Set up the host bridge environment:
   ```sh
   .venv/bin/pip install -r bridge/requirements.txt
   export ANTHROPIC_SECRET_KEY=...
   export CHOSEN_MODEL=claude-haiku-4-5-20251001
   ```
4. Start the webhook and serial bridge (adjust `--socket` for your setup):
   ```sh
   .venv/bin/python bridge/anthropic_webhook.py
   .venv/bin/python bridge/serial_to_anthropic.py --socket vm/com1.sock
   ```
   Optional flags:
   ```sh
   --session kernel-main   # keep a stable logical session
   --mock                 # skip external Anthropic requests
   ```

## Monitor commands highlights

- `help`, `graph`, `paint`, `edit`, `clear`, `about`, `halt`, `reboot`
- Supervised task helpers: `task_spawn`, `task_list`, `task_step`, `task_retire`
- Host interaction: `chat`, `hostreq`, `hardware_list`, `memory_map`, `calc`
  
The kernel prints `CMD:` lines when the bridge receives slash commands (`/task_list`, `/paint`, `/clear`, etc.).

## Configuration notes

- The webhook sources these limits from environment variables documented at the top of `bridge/anthropic_webhook.py`. The defaults are `AGENT_RATE_LIMIT_PER_MINUTE=6`, `AGENT_MAX_SESSIONS=4`, `AGENT_HISTORY_MESSAGES=12`, `AGENT_MIN_STEP_SECONDS=600`, `AGENT_DEFAULT_SESSION=kernel-main`, `WEBHOOK_HOST=127.0.0.1`, and `WEBHOOK_PORT=5005`.
- Keep `ANTHROPIC_SECRET_KEY` in a secret store or a local `.env` (ignored by `.gitignore`) and never commit it. The default model is `claude-haiku-4-5-20251001`, but override `ANTHROPIC_MODEL` only if your key allows another option.
- `ANTHROPIC_MOCK=1` skips real Anthropic calls for offline testing.
- The serial bridge runs on COM1; do not expose its socket to untrusted networks—run it locally or behind a trusted proxy.

