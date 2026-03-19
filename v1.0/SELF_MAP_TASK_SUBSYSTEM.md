# Self-Map: Supervised Task Subsystem

This document maps one concrete subsystem inside `kernel_os`: the supervised task control path behind the monitor commands `task_spawn`, `task_list`, `task_retire`, and `task_step`.

It is not a full map of the kernel. It is a source-level explanation of one end-to-end control flow that starts in the stage2 monitor, crosses the serial bridge, and lands in the host-side session supervisor.

## What This Subsystem Does

The task subsystem lets the kernel monitor treat a host-supervised AI session as a named task slot.

From the operator's point of view:

- `task_spawn` creates a local kernel task slot and a matching host session.
- `task_list` shows both local task slots and the host's session summary.
- `task_retire` removes a task locally and retires the matching host session.
- `task_step` asks one named task to take one bounded next step through the host model loop.

This is a cooperative monitor design, not a protected multitasking kernel. The "tasks" here are mostly a synchronization layer between stage2 state and the Python host supervisor.

## Main Source Files

### Stage2 entry and dispatch

- `boot/stage2.asm`
  - Top-level stage2 compilation unit.
  - Includes the stage2 fragments that define monitor entry, subsystem logic, command strings, and state tables.

- `boot/stage2/01_entry_io.asm`
  - `start`
  - `main_loop`
  - `dispatch_command`
  - `read_line`
  - `serial_init`
  - `serial_write_string`
  - `read_serial_line`

This file is where booted stage2 becomes an interactive command monitor and where COM1 is initialized.

### Task subsystem logic

- `boot/stage2/02_systems.asm`
  - `task_spawn_program`
  - `task_list_program`
  - `task_retire_program`
  - `task_step_program`
  - `prompt_task_identity`
  - `task_alloc_slot`
  - `task_find_slot`
  - `task_name_ptr`
  - `task_goal_ptr`
  - `task_clear_slot`
  - `host_read_response`
  - `host_send_list_request`
  - `host_send_spawn_request`
  - `host_send_retire_request`
  - `host_send_step_request`

This file contains both the local task-slot bookkeeping and the code that serializes host requests onto COM1.

### Command table and strings

- `boot/stage2/04_commands_messages.asm`
  - `command_table`
  - `cmd_task_spawn`
  - `cmd_task_list`
  - `cmd_task_retire`
  - `cmd_task_step`
  - task-related prompts and status messages

This file binds command names to handler entry points.

### Runtime state

- `boot/stage2/05_state_tables.asm`
  - `task_session_buffer`
  - `task_source_buffer`
  - `task_goal_buffer`
  - `task_arg_buffer`
  - `task_active`
  - `task_names`
  - `task_goals`
  - `host_request_buffer`
  - `serial_line_buffer`
  - `generation`

This file contains the task subsystem's persistent stage2 data.

### Serial bridge and host supervisor

- `run-stack.sh`
  - Starts QEMU, the Flask webhook, and the default serial bridge.

- `bridge/serial_to_anthropic.py`
  - `parse_kernel_line`
  - `forward_request`
  - `format_bridge_reply`
  - `attach_recent_output`
  - `record_pending_observation`

This is the default bridge started by `run-stack.sh`. It reads `POST ...` lines from the kernel, forwards them to the webhook, and sends one-line replies back over the serial socket.

- `bridge/command_protocol.py`
  - `extract_kernel_command`
  - `match_pending_observation`

This file is the protocol guardrail layer. It validates model output that is allowed to become a kernel command and associates later observation lines with the session that requested them.

- `bridge/anthropic_webhook.py`
  - `/chat`
  - `/host`
  - `ensure_session`
  - `require_active_session`
  - `record_observation`
  - `build_operator_prompt`
  - `apply_model_turn`
  - `compose_model_reply`

This file is the host-side control plane. It stores session state, runs model turns, and exposes the host actions that the kernel task subsystem calls.

## Core Data Model

There are two parallel representations of a task:

- Local kernel-side slot state in stage2 memory.
- Host-side session state in `bridge/anthropic_webhook.py`.

The local stage2 representation uses:

- `task_active`
  - One byte per slot indicating whether the slot is occupied.
- `task_names`
  - Fixed-width session names for each slot.
- `task_goals`
  - Fixed-width goal text for each slot.
- `task_session_buffer`, `task_goal_buffer`, `task_arg_buffer`
  - Scratch buffers for operator input and request serialization.

The host representation stores session dictionaries in `SESSION_STATE`, persisted to `vm/session_state.json`.

Important consequence: the kernel is maintaining a local mirror of host sessions, not the other way around. `task_spawn` and `task_retire` explicitly synchronize the two sides.

## Entry Path

Stage2 enters through `start` in `boot/stage2/01_entry_io.asm`.

The relevant flow is:

1. `serial_init` configures COM1.
2. `main_loop` prints the prompt and reads a line into `input_buffer`.
3. `dispatch_command` scans `command_table`.
4. If the text matches `task_spawn`, `task_list`, `task_retire`, or `task_step`, it calls the corresponding `do_*` stub.
5. That stub transfers control into the real task subsystem function in `boot/stage2/02_systems.asm`.

This is the top-level monitor dispatch path shared by all commands.

## Command-to-Handler Binding

The relevant entries in `command_table` are:

- `cmd_task_spawn -> do_task_spawn`
- `cmd_task_list -> do_task_list`
- `cmd_task_retire -> do_task_retire`
- `cmd_task_step -> do_task_step`

The `do_*` functions in `01_entry_io.asm` are thin wrappers. They just call:

- `task_spawn_program`
- `task_list_program`
- `task_retire_program`
- `task_step_program`

That means the actual subsystem behavior lives almost entirely in `02_systems.asm`, while discovery and dispatch live in `01_entry_io.asm` and `04_commands_messages.asm`.

## Local Control Flow by Command

### `task_spawn`

`task_spawn_program` does the following:

1. Switches to text mode and prints the intro message.
2. Calls `prompt_task_identity`, which reads the desired session name into `task_session_buffer`.
3. Calls `task_find_slot` to reject duplicate local task names.
4. Calls `task_alloc_slot` to reserve a free local slot index in `BX`.
5. Prompts for the goal and stores it in `task_goal_buffer`.
6. Calls `host_send_spawn_request`, which constructs a serial line:
   - `POST /host {"action":"spawn-session","session":"...","goal":"...","generation":"0x..."}`
7. Calls `host_read_response` to wait for the bridge's reply.
8. If the host call did not report an error, stage2 marks `task_active[slot] = 1` and copies:
   - `task_session_buffer -> task_names[slot]`
   - `task_goal_buffer -> task_goals[slot]`

Important detail: the local slot is only committed after the host spawn succeeds. The kernel avoids creating a local task that has no corresponding host session.

### `task_list`

`task_list_program` does two separate listings:

1. Iterates through all `TASK_SLOT_COUNT` local slots.
2. For each active slot:
   - prints slot number
   - prints `name=...`
   - prints `goal=...`
3. If no local tasks exist, prints `no local tasks`.
4. Prints `host summary:`.
5. Calls `host_send_list_request`.
6. Calls `host_read_response`.

This command is the clearest place where the design reveals itself: local kernel state and host state are intentionally shown side by side.

### `task_retire`

`task_retire_program`:

1. Prompts for a session name.
2. Calls `task_find_slot`.
3. Saves the carry flag result and slot index.
4. Sends `retire-session` to the host with `host_send_retire_request`.
5. Waits in `host_read_response`.
6. If the host reply was not an error and the local slot existed, calls `task_clear_slot`.

`task_clear_slot`:

- clears `task_active[slot]`
- zero-terminates the stored name
- zero-terminates the stored goal

This command is asymmetrical by design: the host retirement is attempted even if the kernel-side slot is already missing, but the local mirror is only cleared when a real local slot existed.

### `task_step`

`task_step_program` is the most important runtime path:

1. Prompts for a session name.
2. Uses `task_find_slot` to ensure the task exists locally.
3. Prompts for a short step request and stores it in `task_arg_buffer`.
4. Calls `host_send_step_request`, which serializes:
   - `POST /host {"action":"step-session","session":"...","prompt":"...","generation":"0x..."}`
5. Calls `host_read_response`.
6. If the host returned a normal successful step, the kernel bumps `generation`.

This is the point where the stage2 monitor hands execution initiative to the host-side model supervisor.

## Host Request Serialization

The kernel does not speak HTTP directly. It emits text lines over COM1 that look like:

```text
POST /host {"action":"step-session","session":"build-fix","prompt":"continue","generation":"0x00000002"}
```

The relevant helper chain is:

- `host_send_*_request`
- `buffer_write_string`
- `buffer_write_json_escaped`
- `buffer_write_generation_field`
- `serial_write_buffer`

This separation matters:

- buffer builders assemble the request in `host_request_buffer`
- `serial_write_buffer` emits the finished line over COM1
- `read_serial_line` receives the host bridge's one-line response

So the kernel-side protocol is a compact line-oriented RPC layer carried over serial.

## Bridge Control Flow

The default runtime path from `run-stack.sh` is:

1. Start `bridge/anthropic_webhook.py`
2. Start QEMU with a Unix socket wired to COM1
3. Start `bridge/serial_to_anthropic.py`

Inside `serial_to_anthropic.py`, the bridge loop is:

1. Read a line from the serial socket.
2. If it does not start with `POST `:
   - treat it as kernel output
   - maybe append it to `recent_output`
   - maybe record it as a pending observation
3. If it does start with `POST `:
   - `parse_kernel_line` splits route and JSON body
   - `forward_request` POSTs that payload to the Flask webhook
   - `format_bridge_reply` converts the JSON result into one serial line
4. Send the reply back to the kernel as either:
   - `AI: ...`
   - `CMD: ...`
   - `SYS: session retired by /kill-self`

For the task subsystem specifically, normal `/host` actions usually return `AI: ...`, which `host_read_response` prints directly.

## Host Webhook Control Flow

The webhook has two distinct entry points:

- `/chat`
  - model-facing
- `/host`
  - control-plane actions such as session lifecycle and stepping

For task supervision, `/host` is the main path.

### `/host` actions used by this subsystem

- `list-sessions`
- `spawn-session`
- `retire-session`
- `step-session`

The control flow inside `bridge/anthropic_webhook.py` is:

1. Parse JSON payload.
2. Read `action`.
3. Dispatch inside the `/host` function.

#### `spawn-session`

- validates `session`
- checks for duplicates
- calls `ensure_session`
- sets `goal`, `mode`, and optional style
- persists state
- returns a short message

#### `list-sessions`

- serializes `SESSION_STATE` through `session_snapshot`
- compresses it through `format_session_list`
- returns a compact summary string

#### `retire-session`

- finds the session
- marks it inactive
- persists state
- returns a retirement message

#### `step-session`

This is the deepest path:

1. `require_active_session` ensures the session exists and is not retired.
2. `build_operator_prompt` combines:
   - kernel generation
   - session goal
   - operator step prompt
3. `apply_model_turn` executes one supervised turn.
4. `apply_model_turn` calls `compose_model_reply`.
5. `compose_model_reply` decides whether to:
   - respond directly
   - or consult the machine-code specialist first
6. The final content is stored in session history.
7. The webhook returns both:
   - `content`
   - `kernel_command = extract_kernel_command(content, KERNEL_COMMANDS)`

That last field is what lets a host step become an actionable kernel command.

## How a Host Step Turns Back Into Kernel Control

When the webhook returns from `step-session`, the bridge examines the result.

If `kernel_command` is present:

- `format_bridge_reply` returns `CMD: <command>`

If not:

- `format_bridge_reply` returns `AI: <text>`

Back in stage2, `host_read_response` checks the line prefix.

### `AI:` path

- print the line
- return to the monitor or caller

### `CMD:` path

`host_read_response` treats this as executable monitor control:

1. Prints `AI requested command: ...`
2. Strips the `CMD: ` prefix
3. Checks for special slash commands:
   - `/curl`
   - `/loop`
   - `/patch`
   - `/stream`
   - `/peekpage`
   - `/peek`
4. If it is not one of those special forms, copies the command into `input_buffer`
5. Calls `dispatch_command`

That means a host-supervised task step can re-enter the same monitor dispatch table that a human operator uses.

This is the critical control-flow loop in the system:

`task_step` -> `/host step-session` -> model output -> `CMD:` reply -> `dispatch_command` again

## Observation Feedback Loop

The bridge also preserves evidence from non-interactive commands.

Relevant pieces:

- `bridge/command_protocol.py::match_pending_observation`
- `bridge/serial_to_anthropic.py::record_pending_observation`
- `bridge/anthropic_webhook.py::record_observation`

Flow:

1. A host reply asks for `/peek`, `/stream`, or `/patch`.
2. The bridge records that as a pending observation for the requesting session.
3. The kernel executes the command and prints the resulting observation line.
4. The bridge matches that line to the pending request.
5. It sends `/host {"action":"record-observation", ...}`.
6. The webhook appends a normalized observation message into that session's history.

This matters because a supervised task is stateful across turns. It can inspect kernel memory or live execution output, and that observation is fed back into later reasoning.

## Why This Subsystem Is a Good Self-Map Target

This subsystem is especially useful for self-mapping because it crosses every major boundary in the project:

- booted stage2 assembly
- command dispatch
- static state tables
- serial protocol framing
- Python bridge logic
- host session persistence
- model-turn orchestration
- command feedback into the monitor

It shows that `kernel_os` is not only a BIOS monitor. It is also a cooperative control loop between:

- a tiny assembly monitor
- a serial RPC layer
- a Python supervisor
- a session-based AI control plane

## Short Summary

If you want the shortest accurate description:

- `task_*` commands are declared in `04_commands_messages.asm`
- entered through `dispatch_command` in `01_entry_io.asm`
- implemented in `02_systems.asm`
- backed by local slot state in `05_state_tables.asm`
- forwarded over COM1 as `POST /host {...}` lines
- translated by `bridge/serial_to_anthropic.py`
- executed by `/host` in `bridge/anthropic_webhook.py`
- and, for `task_step`, may return a `CMD:` line that re-enters the kernel command dispatcher

That re-entry path is the core idea of the subsystem.
