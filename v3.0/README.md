# kernel_os v3.0

`v3.0` is a fresh QEMU-bootable kernel variant built around the fixed layout
described in the current design note:

- guest RAM: `64 MiB`
- bootable disk image: `64 MiB`
- logical SSD allocation: `64 MiB` starting at LBA `0x0000`
- QEMU topology target: `3` vCPUs
- RAM layout:
  - `0x00000000 -> 0x000FFFFF` : OS region (`1 MiB`)
  - `0x00100000 -> 0x020FFFFF` : training weights (`32 MiB`)
  - `0x02100000 -> 0x03FFFFFF` : user arena (`31 MiB`)

The current implementation keeps the three roles explicit inside the kernel:

- `user core`: updates a RISC0-style mailbox and mutates the user arena
- `forward reader`: scans the full `RAM + SSD` bytemap from low to high
- `backward reader`: scans the same bytemap from high to low

The intended topology is still `3` roles, but the default QEMU launch now uses
`-smp 1` because the current stage2 kernel still schedules those roles
cooperatively on the bootstrap CPU. Local-APIC application-processor bring-up
is not wired yet. Use `SMP=3 make -C v3.0 run` when you explicitly want to boot
the VM in that target topology.

The reader roles do **not** skip the weights region. Any scanned page, including
weight pages, folds back into the `32 MiB` weight allocation. The recursion is
intentional.

The bootable kernel footprint lives in the first `1 MiB` of that same `64 MiB`
SSD allocation. The forward/backward readers can read kernel sectors from disk,
and the live RAM mirror can overwrite that footprint during runtime. A fresh
`make -C v3.0 boot` restores the boot sectors before the next run.

`loop` is the new low-duty autonomous mode. It sleeps between ticks with BIOS
waits, defaults to `25 ms` per tick, and keeps the machine from pegging one CPU
core just to sustain the self-referential scan.

`v3.0` now builds from checked-in raw binaries in `binary/`. The canonical
`stage1.bin` and `stage2.bin` files are copied directly into `build/` and then
written onto the VM disk image. The hexadecimal tree in `hex/` is kept only as
a compatibility import/export snapshot for older hex-first workflows. `v3.0`
no longer ships any assembly source tree.

## Build

```sh
make -C v3.0 boot
```

Import the canonical binaries from the compatibility hex snapshots:

```sh
make -C v3.0 sync-binary-from-hex
```

Refresh the compatibility hex snapshots from the canonical binaries:

```sh
make -C v3.0 sync-hex-from-bin
```

## Run

```sh
make -C v3.0 run
```

Resume the current disk state without rewriting the boot region:

```sh
make -C v3.0 run-preserve
```

Headless serial mode:

```sh
make -C v3.0 run-headless
nc 127.0.0.1 5555
```

Headless resume mode:

```sh
make -C v3.0 run-headless-preserve
nc 127.0.0.1 5555
```

Integrated host-bridge mode:

```sh
cp -n v3.0/.env.example v3.0/.env
OPENAI_MOCK=1 make -C v3.0 run-stack
```

Set `OPENAI_API_KEY` in `v3.0/.env` to switch the bridge from the local mock
reply path to live OpenAI Responses API calls. The host bridge is now
drip-metered by default: it uses `OPENAI_DRIP_CENTS_PER_HOUR`,
`OPENAI_DRIP_BUCKET_CENTS`, and `OPENAI_DRIP_START_CENTS` from `.env`, and
ships with `OPENAI_MODEL=gpt-5-mini` as the default low-cost path.

`run-stack` also opens a local UNIX control socket at `v3.0/vm/bridge_control.sock`.
That socket is the general binary transport layer for the live stage2 window.

Discard the current disk and start from a blank image:

```sh
make -C v3.0 fresh-disk
```

## Commands

- `help`
- `layout`
- `status`
- `step [count]`
- `loop [count]`
- `pace [ms]`
- `train [count]`
- `seed <text>`
- `peek <hex-offset> <hex-count>`
- `patch <hex-offset> <hex-bytes...>`
- `persist`
- `chat <text>`
- `halt`

`step 64` runs a deterministic fixed number of ticks and then prints `status`.
`loop` runs the same kernel tick path, but throttled with the current `pace`
delay so it can stay alive indefinitely without busy-spinning.
`train 256` runs up to that many ticks, still allowing `Esc` to abort early.
`peek`, `patch`, and `persist` turn the loaded stage2 image into a live object:
the kernel can inspect, edit, and flush its own code/data window back to disk.
`chat` sends a prompt over COM1 as `POST /chat ...`; the host bridge can reply
with either `AI: ...` text or a safe `CMD: ...` line that the kernel dispatches.

## Drip Bridge

- `bridge/openai_serial_bridge.py`: host-side broker with budget gating
- `vm/bridge_state.json`: persistent session and budget state
- `vm/bridge_ledger.jsonl`: append-only ledger of approvals and deferrals
- `vm/kernel_journal.jsonl`: append-only journal of control-plane state transitions
- `vm/bridge_control.sock`: local JSON control socket for live binary transport
- `vm/stage2_shadow.bin`: mutable working image for staged binary changes
- `vm/stage2_rollback.bin`: last captured live window before a shadow promote
- `OPENAI_DRIP_ENABLED=1`: turns on budget enforcement
- `OPENAI_DRIP_CENTS_PER_HOUR=1.0`: refill rate in cents per hour
- `OPENAI_DRIP_BUCKET_CENTS=10.0`: maximum accumulated balance
- `OPENAI_DRIP_START_CENTS=1.0`: starting balance for a fresh state file
- `OPENAI_DRIP_ESTIMATE_MULTIPLIER=1.15`: conservative reserve before each call
- `OPENAI_PROMPT_CACHE_KEY=kernel-os-v3`: stable cache key prefix for repeated prompts
- `OPENAI_USE_CONVERSATION_STATE=0`: keeps the bridge stateless by default so hourly spend stays predictable

When the bucket is empty the kernel still gets a reply, but it will be an
`AI: budget defer ...` line instead of a live model call. The bridge records
each approval or deferral in `vm/bridge_ledger.jsonl`.

## Binary Transport

The bridge now owns the serial socket and exposes a separate host-local control
plane for live binary transport. The control socket uses one JSON request per
connection and returns one JSON line for simple actions, or a stream of JSON
frames for continuous binary reads.

CLI examples:

```sh
make -C v3.0 transport-info
make -C v3.0 transport-read OFFSET=0x0 LENGTH=0x10
make -C v3.0 transport-write OFFSET=0x0 DATA="FA 31 C0 8E" VERIFY=1
make -C v3.0 transport-persist
make -C v3.0 transport-stream OFFSET=0x0 LENGTH=0x10 COUNT=4 INTERVAL_MS=250
make -C v3.0 transport-shadow-init SHADOW_SOURCE=canonical
make -C v3.0 transport-shadow-write OFFSET=0x1F00 DATA="AA BB"
make -C v3.0 transport-shadow-diff BASE=canonical
make -C v3.0 transport-shadow-promote VERIFY=1
make -C v3.0 transport-rollback VERIFY=1
make -C v3.0 journal-replay TIMELINE=12
```

Direct tool usage:

```sh
python3 v3.0/tools/binary_transport.py info
python3 v3.0/tools/binary_transport.py read --offset 0x0 --length 0x20
python3 v3.0/tools/binary_transport.py write --offset 0x20 --hex "90 90 90" --verify
python3 v3.0/tools/binary_transport.py stream --offset 0x0 --length 0x10 --count 3 --interval-ms 500
python3 v3.0/tools/binary_transport.py shadow-init --source canonical
python3 v3.0/tools/binary_transport.py shadow-write --offset 0x1F00 --hex "AA BB"
python3 v3.0/tools/binary_transport.py shadow-promote --verify
python3 v3.0/tools/binary_transport.py rollback-live --verify
python3 v3.0/tools/journal_replay.py --timeline 12
```

JSON request examples:

```json
{"action":"info"}
{"action":"read","offset":0,"length":16,"encoding":"hex"}
{"action":"write","offset":32,"data_hex":"909090","verify":true}
{"action":"persist"}
{"action":"stream","offset":0,"length":16,"encoding":"hex","interval_ms":500,"iterations":4}
{"action":"shadow_init","source":"canonical"}
{"action":"shadow_write","offset":7936,"data_hex":"AABB"}
{"action":"shadow_diff","base":"canonical","limit_spans":16}
{"action":"shadow_promote","verify":true}
{"action":"rollback_live","verify":true}
```

Supported actions:

- `info`: report socket paths, transport window size, drip balance, and bridge state
- `command`: run an arbitrary kernel command and return raw lines
- `read`: pull live bytes from the stage2 window through chunked `peek`
- `write`: push live bytes into the stage2 window through chunked `patch`
- `persist`: flush the live stage2 window back to disk
- `stream`: repeatedly sample a live binary region and emit newline-delimited JSON frames
- `shadow_info`: inspect the mutable working image on the host
- `shadow_init`: initialize the working image from the immutable bootstrap or current live window
- `shadow_read`: inspect bytes from the working image without touching the kernel
- `shadow_write`: patch the working image on the host and log the proposed mutation
- `shadow_diff`: diff the working image against the immutable bootstrap or current live window
- `shadow_promote`: promote the working image into the live stage2 window with rollback capture
- `rollback_live`: restore the last captured pre-promote live window

The transport window defaults to `0x8000` bytes, matching the `64` loaded
stage2 sectors. Reads and writes beyond that window are rejected by the broker.

## Journaled Self-Reference

`v3.0` now has three explicit planes around the stored-program core:

- immutable bootstrap image: `binary/stage2.bin`
- mutable working image: `vm/stage2_shadow.bin`
- append-only experience log: `vm/kernel_journal.jsonl`

This lets you stage binary edits outside the live kernel, inspect the diff,
promote the shadow into the live window, and roll back to the captured
pre-promote state if the promote fails or produces bad behavior.

The replay tool reconstructs host-visible state transitions from the journal:

```sh
python3 v3.0/tools/journal_replay.py --json --timeline 16
```

The journal records structured events such as:

- `command_executed`
- `live_write`
- `live_persist`
- `shadow_initialized`
- `shadow_write`
- `shadow_promote_started`
- `shadow_promote_committed`
- `live_rollback_committed`

## Supervised Session

Use the host-side supervisor to run a bounded live experiment against the
kernel through the transport socket while capping direct API spend:

```sh
OPENAI_MOCK=1 make -C v3.0 run-stack
python3 v3.0/tools/supervised_session.py --budget-usd 0.05 --model gpt-4o-mini
```

The supervisor:

- collects `status`, `layout`, and a live binary head snapshot
- stabilizes pacing
- asks a model for one conservative command per phase
- executes only host-filtered safe commands
- writes a JSON report into `v3.0/vm/`

## Binary Layout

- `binary/stage1.bin`: canonical BIOS boot sector bytes
- `binary/stage2.bin`: canonical loaded kernel bytes
- `hex/stage1.hex`: compatibility text export of `binary/stage1.bin`
- `hex/stage2.hex`: compatibility text export of `binary/stage2.bin`
- `tools/bin_to_hex.py`: exporter from canonical raw binaries into compatibility hex snapshots
- `tools/hex_to_bin.py`: importer from compatibility hex snapshots back into raw binaries
- `tools/binary_transport.py`: client for the live control socket
- `tools/journal_replay.py`: reconstruct and summarize journaled state transitions
- `tools/supervised_session.py`: host-side supervisor for bounded live experiments

The normal authoring path is direct binary mutation. Hex remains only as an
optional text interchange format for `v3.0`.
