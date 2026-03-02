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
5. Run the deterministic chat smoke suite:
   ```sh
   python3 bridge/vm_chat_smoke.py
   ```
   This boots the VM on a blocking COM1 socket and validates persistent `chat` context, `peek`, `peekpage`, `edit`, `/loop`, live `/patch`, and fatal `/kill-self` behavior end-to-end. The transcript is saved to `vm/chat-smoke-transcript.log`.

## Monitor commands highlights

- `help`, `graph`, `paint`, `edit`, `clear`, `about`, `halt`, `reboot`
- Supervised task helpers: `task_spawn`, `task_list`, `task_step`, `task_retire`
- Host interaction: `chat`, `curl`, `hostreq`, `hardware_list`, `memory_map`, `calc`
  
The kernel prints `CMD:` lines when the bridge receives slash commands (`/task_list`, `/paint`, `/clear`, etc.).
Entering `chat` starts one fresh host conversation, and later prompts in that same `chat` visit keep their context until you leave `chat`.
Inside `chat`, non-interactive command results such as `peek`, `peekpage`, `patch`, `curl`, and selected text-only monitor commands are fed back to the model automatically so it can keep working without waiting for another user prompt.
The model can still emit `/loop` to request broader autonomous recursion across several host round-trips. The loop ends when the model returns a normal prose reply or the kernel hits its local recursion cap.
If the model emits `/kill-self`, the bridge marks that explicitly and the kernel halts.

## Configuration notes

- The bridge entry points load the project `.env` automatically at startup and use those values as runtime configuration. The defaults are still documented at the top of `bridge/anthropic_webhook.py`.
- The kernel sets `fresh_chat:true` on the first `/chat` request of each `chat` visit. The webhook returns `retired_reason` so the bridge can distinguish ordinary host retirement from model-triggered `/kill-self`.
- Outbound HTTPS from the webhook now uses `certifi` by default via `REQUESTS_CA_BUNDLE`. Override that env var only if you need a custom CA bundle.
- If your host still fails TLS verification because of a broken or intercepted certificate chain, set `ALLOW_INSECURE_HTTPS=1` before starting the webhook to skip HTTPS verification entirely.
- QEMU now forces `KEYBOARD_LAYOUT=en-us` by default in `run-vm.sh`. Override that env var only if your host layout really differs.
- QEMU now opens `vm/os-disk.img` with `file.locking=off` by default in `run-vm.sh`, so multiple VM processes can boot the same raw image concurrently. This is intentionally unsafe; concurrent guest writes can corrupt the shared disk. Set `DISK_LOCKING=on` if you want QEMU's normal exclusive lock back.
- For serial automation, set `SERIAL_MODE=socket` and `SERIAL_WAIT=on` so QEMU waits for the client before the BIOS monitor starts writing COM1 output.
- If you run multiple bridged stacks at once, give each one its own `SERIAL_SOCKET`, `WEBHOOK_PORT`, and `SESSION_STATE_PATH`. `WEBHOOK_LOG` and `BRIDGE_LOG` are also overridable now if you want isolated logs.
- QEMU now defaults to `-vga std` and `-display cocoa,zoom-to-fit=on`, so the window can resize and scale more cleanly on macOS. This is host-window scaling only; the guest still uses fixed BIOS text mode and mode `13h` graphics until VBE support exists in the kernel.
- Keep `ANTHROPIC_SECRET_KEY` in the local `.env` and never commit it. `ANTHROPIC_PROSE_MODEL` is the operator-facing lead model and `ANTHROPIC_MACHINE_CODE_MODEL` is the byte-level specialist; both default to `claude-haiku-4-5-20251001` unless you override them.
- `ANTHROPIC_DIRECTOR_MAX_TOKENS` and `ANTHROPIC_MACHINE_MAX_TOKENS` cap the internal director and machine-specialist subcalls. The outward reply still uses the regular `max_tokens` request field.
- `ANTHROPIC_MOCK=1` skips real Anthropic calls for offline testing.
- The serial bridge runs on COM1; do not expose its socket to untrusted networks—run it locally or behind a trusted proxy.

## The 10 Commandments of ASM

1. Thou Shalt Not Go in Circles Forever
   Never write a loop that only waits for an external signal (like a sensor). Always use a timeout counter. If the sensor doesn't respond in `X` cycles, the code must move on or trigger an error.
2. Thou Shalt Keep Thy Functions Tiny
   If a subroutine is longer than a single screen of text, it's too long. Break it up. Small functions are easy to prove correct; giant spaghetti blocks are where bugs hide.
3. Thou Shalt Not Use "Magic" Memory
   Do not use dynamic memory allocation. Decide exactly where every byte of data lives before you turn the computer on. Static memory is predictable memory.
4. Thou Shalt Not Jump Blindly
   Avoid complex spaghetti jumps (`JMP`). Use `CALL` and `RET` properly. Never jump into the middle of someone else's function. Every door you enter, you must exit through the same way.
5. Thou Shalt Check Thy Flags Constantly
   The CPU tells you if an addition overflowed or a result was zero. Do not ignore it. After every critical math or I/O operation, check the status flags immediately.
6. Thou Shalt Limit Thy Indirection
   Don't use pointers to pointers to pointers. It makes it impossible for a human, or a testing tool, to track where the data is actually going. Keep your memory addresses simple and direct.
7. Thou Shalt Protect Thy Registers
   When you enter a subroutine, save the registers you're going to use by pushing them to the stack. Before you leave, restore them by popping them. Leave the CPU exactly how you found it.
8. Thou Shalt Not Write "Clever" Macros
   Macros that hide hundreds of lines of code are dangerous. If an engineer can't look at a line of code and know exactly what the processor is doing, that code shouldn't be there.
9. Thou Shalt Define Thy Bounds
   Before you write to an array or a buffer, check the index. If your buffer is 10 bytes and you're trying to write to the 11th, stop everything. In space, a buffer overflow isn't a crash; it's a mission failure.
10. Thou Shalt Demand Perfection from the Assembler
    If the assembler gives you even a single minor warning, fix it. Warnings are the computer's way of saying, "I'm doing what you asked, but it looks like a mistake."

## VS Code ASM warnings

VS Code task support now lives in `.vscode/tasks.json`:

- `ASM: lint` runs `tools/asm_lint.py` and reports commandment-style warnings directly in the Problems panel.
- `ASM: lint (strict)` does the same, but exits non-zero on any warning.
- `Boot: build` is the default VS Code build task and assembles with NASM warnings enabled.
- `Boot: build (strict)` runs the strict linter first, then assembles with NASM warnings promoted to errors.

Run `ASM: lint` directly if you want the Problems panel populated without building.
