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
   This is the integrated path: it starts QEMU plus the local webhook and serial bridge, and streams bridge logs in the terminal while the VM uses a GUI window.

   Raw VM only, no host bridge:
   ```sh
   make run-raw
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
   ```
   Runtime configuration is loaded automatically from the project `.env` file. Copy `.env.example` to `.env` and edit values there instead of relying on ambient shell exports.
4. If you are not using `make run`, start the webhook and serial bridge manually (adjust `--socket` for your setup):
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
- Host interaction: `chat`, `curl`, `hostreq`, `hardware_list`, `memory_map`, `calc`
  
The kernel prints `CMD:` lines when the bridge receives slash commands (`/task_list`, `/paint`, `/clear`, etc.).
Inside `chat`, the model can now emit `/loop` to stay in autonomous recursive mode across several host round-trips. The loop ends when the model returns a normal prose reply or the kernel hits its local recursion cap.

## Configuration notes

- The bridge entry points load the project `.env` automatically at startup and use those values as runtime configuration. The defaults are still documented at the top of `bridge/anthropic_webhook.py`.
- Outbound HTTPS from the webhook now uses `certifi` by default via `REQUESTS_CA_BUNDLE`. Override that env var only if you need a custom CA bundle.
- If your host still fails TLS verification because of a broken or intercepted certificate chain, set `ALLOW_INSECURE_HTTPS=1` before starting the webhook to skip HTTPS verification entirely.
- QEMU now forces `KEYBOARD_LAYOUT=en-us` by default in `run-vm.sh`. Override that env var only if your host layout really differs.
- QEMU now defaults to `-vga std` and `-display cocoa,zoom-to-fit=on`, so the window can resize and scale more cleanly on macOS. This is host-window scaling only; the guest still uses fixed BIOS text mode and mode `13h` graphics until VBE support exists in the kernel.
- Keep `ANTHROPIC_SECRET_KEY` in the local `.env` and never commit it. `ANTHROPIC_PROSE_MODEL` is the operator-facing lead model and `ANTHROPIC_MACHINE_CODE_MODEL` is the byte-level specialist; both default to `claude-haiku-4-5-20251001` unless you override them.
- `ANTHROPIC_DIRECTOR_MAX_TOKENS` and `ANTHROPIC_MACHINE_MAX_TOKENS` cap the internal director and machine-specialist subcalls. The outward reply still uses the regular `max_tokens` request field.
- `ANTHROPIC_MOCK=1` skips real Anthropic calls for offline testing.
- The serial bridge runs on COM1; do not expose its socket to untrusted networks—run it locally or behind a trusted proxy.
