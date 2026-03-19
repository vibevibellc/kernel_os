# kernel_os v2.0

This is a fresh minimal rewrite.

What exists right now:

- a 512-byte BIOS boot sector in `boot/stage1.asm`
- a stage2 console in `boot/stage2.asm`
- keyboard input through BIOS INT `0x16`
- text output through BIOS INT `0x10`
- serial console mirroring over COM1 for headless runs
- a persistent page-scanning predictor checkpointed to fixed disk sectors
- commands: `help`, `scan`, `map`, `train`, `chat`, `stream`, `set`, `bench`, `halt`

Defaults:

- RAM: 4 GB
- disk image size: 4 GB
- QEMU default binary: `qemu-system-i386`
- QEMU default accel path: `-accel tcg,thread=multi -cpu qemu32 -smp 8`
- QEMU PS/2 mouse disabled; keyboard input is provided by `usb-kbd`

Build and run from this directory:

```sh
make run
```

Headless serial run:

```sh
make run-headless
nc 127.0.0.1 5555
```

Use `HEADLESS_PORT=NNNN make run-headless` to change the listener port.

Terminal-only serial run:

```sh
make run-stdio
```

The current console is intentionally small. It boots, prints a prompt, accepts
line input, and treats a runtime-configurable unreal-mode RAM window plus a
runtime-configurable disk-sector window as the training corpus.

If no saved page state is present, boot initializes an empty model and waits
for `scan` or `train` instead of scanning the full corpus during bootstrap.
Saved page state is checkpointed to fixed disk sectors, and the loader build
now verifies that stage1's configured load window is large enough for the
assembled stage2 image.

The default RAM window is 4 MiB starting at `0x00100000`. The default disk
window follows `model.safetensors` when that file exists at build time: the
blob is written into `vm/os-disk.img` at LBA `0x1000`, and stage2 boots with
that LBA plus the blob's exact sector count as its disk corpus. You can change
both windows at runtime without recompiling:

```sh
set
set ram-mib 16
set ram-start 0x100000 ram-mib 1024
set ram-start 0x0 ram-mib 4096
set disk-lba 0x1000 disk-mib 3390
set disk-lba 0x0 disk-mib 4096
```

The kernel validates that the requested RAM and disk windows stay inside the
guest's 4 GiB physical address space and 4 GiB raw disk. During large scans it
prints coarse RAM and disk progress and `Esc` aborts cleanly while keeping any
partial count updates.

Command behavior:

- `scan`: performs one corpus pass over the configured RAM and disk windows
- `map`: prints the top tracked surprise pages from the most recent scan, highest first
- `train`: repeats corpus scans until `Esc`
- `chat`: takes one prompt, seeds the generator, then samples the page model
- `stream`: continuously samples the page model until `Esc`
- `set`: shows or updates `ram-start`, `ram-mib`, `disk-lba`, and `disk-mib`
- `bench`: times one scan pass using BIOS ticks

The model never resets itself during normal operation. Transition counts use
16-bit saturating counters, decay by half every 10 completed scan epochs to
avoid total lock-in, and generated output no longer executes live commands.

## Visualization: Von Neumann vs `kernel_os` v2.0

### Classical Von Neumann layout

```text
                +------------------+
                |   CPU / ALU + CU |
                +---------+--------+
                          |
                    instruction/data bus
                          |
          +---------------+---------------+
          |                               |
  +-------v--------+              +-------v--------+
  | Main Memory    |              | Input / Output |
  | code + data    |              | devices        |
  +----------------+              +----------------+

Flow:
1. CPU fetches instructions from memory.
2. CPU reads and writes data through the same shared path.
3. I/O stays outside the main compute loop.
```

### `kernel_os` v2.0 layout

```text
 +-----------+       BIOS INT 13h        +------------------------------+
 | Stage 1   +--------------------------->  Stage 2 console @ 0x8000    |
 | bootsector|                            | command loop + scanner       |
 +-----+-----+                            +-----+-------------+----------+
       |                                        |             |
       | BIOS INT 10h / 16h                     |             |
       |                                        |             |
 +-----v------------------+          unreal-mode RAM window   | fixed disk corpus
 | screen + keyboard      |<----------------------+           |
 +------------------------+                       |           |
                                                  v           v
                                         +---------------------------+
                                         | nibble Markov page model  |
                                         | 16-bit transition counts  |
                                         | page surprise map         |
                                         +-------------+-------------+
                                                       |
                                      save/load checkpoint to disk sectors
                                                       |
                                                       v
                                         +---------------------------+
                                         | generated output          |
                                         | `map` `chat` `stream`     |
                                         +---------------------------+
```

| Aspect | Classical Von Neumann machine | `kernel_os` v2.0 |
| --- | --- | --- |
| Compute center | CPU executes a program over separate memory contents | Stage2 console drives scanning and generation over machine state |
| Main data path | One shared instruction/data path between CPU and memory | Stage2 walks a RAM window plus fixed disk corpus as one dataset |
| Memory role | Holds instructions and working data | Becomes corpus, state source, and part of the thing being modeled |
| Disk role | Slow backing store outside the hot loop | Participates directly in scans and stores model checkpoints |
| I/O role | Peripheral support for the running program | BIOS screen, keyboard, and serial expose the training/sampling interface |
| System shape | Program-centered | Corpus-centered and self-observing |

`kernel_os` v2.0 still runs on a Von Neumann machine, but the workload is inverted: instead of mainly executing a program over external data, it repeatedly inspects its own machine state and learns from it.



### Core Concept: Training on the Entire Machine as One Giant Corpus

This project treats the **full physical memory** (RAM + selected disk sectors) as the sole training dataset for a tiny nibble-level Markov model. The "kernel" scans pages directly from low memory (via unreal mode for multi-MiB access), counts nibble transitions, and generates from those statistics — creating a self-referential loop where the model learns to predict (and hallucinate) its own runtime environment.

#### Key Advantage: RAM and SSD of Equivalent (or "Infinite") Size for the Training Window

In a hypothetical machine where **RAM capacity equals SSD capacity** (or in our emulated QEMU setup, where we can make guest RAM arbitrarily large and disk reads cheap/fast), the distinction between volatile/fast RAM and persistent/slow storage collapses for training purposes:

- **No classical paging/offloading penalty**: The entire working set (model state, KV-like context via the count table, gradients if expanded) fits "in-core" across both media without thrashing. Disk becomes an extension of addressable memory with only a constant latency factor.
- **Infinite effective context / corpus length for free**: The scan window can grow to encompass **gigabytes** (or theoretically the full 4 GB address space in unreal mode) without recompute-from-disk costs dominating. Every epoch attends over (predicts) everything the machine "knows" — a single pass over all bits.
- **Mathematical fixed-point attractor emerges naturally**: Training on the machine's own bits creates a closed loop. The model converges toward a **denoiser / lossless-ish compressor of the entire state** (including its own weights, once saved/loaded). Catastrophic forgetting is minimized because further epochs are circular/idempotent on a near-fixed dataset — the attractor is the machine itself.
- **Latency-bandwidth inversion unlocks low-arithmetic kernels**: With no size penalty for touching "slow" storage, embarrassingly parallel / low-FLOP operations (bitwise lookups, table-driven prediction) become surprisingly efficient compared to high-FLOP transformers. This regime favors **byte/nibble-level statistical models** over compute-heavy ones.

In real systems, RAM is usually 10–100× smaller than storage → offloading hurts. Here (in QEMU with large `-m` + unreal mode), we erase that gap → the anomaly lets the tiny 256-byte model ingest **orders of magnitude more self-data** per epoch, leading to deeper, weirder emergent patterns over reboots (e.g., regenerating boot echoes, ASCII drift, or self-code fragments).

Current implementation (v2.0+): Scans a configurable unreal-mode RAM window plus a configurable disk window. When `model.safetensors` is present, the default disk corpus covers the full blob inside the 4 GiB disk image. Next: Ramp the active windows toward the full 4 GiB RAM and 4 GiB disk limits where scan time still stays useful.


## Core Concept: Training on the Entire Machine as One Giant Corpus

This project is a tiny real-mode "kernel" (bootloader-style OS) that runs a nibble-level first-order Markov model. It scans physical memory pages (RAM) and selected disk sectors directly, counts nibble (4-bit) transitions in a 256-entry table, and generates output by sampling from those statistics. The result is a bizarre self-referential loop: the model learns to predict — and eventually hallucinate — fragments of its own runtime environment, boot code, BIOS data, and whatever else happens to live in the scanned regions.

### Key Advantage: Treating RAM and SSD as Equivalent-Size Pools (No Hierarchy Penalty)

In real hardware, RAM and storage (SSD/NAND) are **never** the same size — and for good engineering reasons:

- **Memory Hierarchy Physics & Economics**  
  DRAM (RAM) is optimized for ultra-low latency (~10–50 ns random access), requiring leaky capacitors, constant refresh circuits, high-speed buses, and expensive silicon per bit.  
  NAND flash (SSD) prioritizes **density** and **non-volatility** — cells are tiny, 3D-stacked, cheap per GB, but access is block-based with much higher latency (~10–100 µs) and no refresh needed.  
  Result: System designers provision RAM only for the active working set (what the CPU touches frequently), while storage holds cold/bulk data. RAM is typically 10–100× smaller and far more expensive per GB than SSD.

- **Interface & Bandwidth Trade-offs**  
  RAM connects via wide, multi-GHz DDR buses directly to the memory controller → massive bandwidth (100+ GB/s).  
  Storage uses narrower PCIe/NVMe or SATA links with protocol overhead → great sequential throughput but latency-bound for random access.  
  The further from the CPU cores (L1/L2/L3 cache → DRAM → SSD), the cheaper, slower, and larger-capacity the medium becomes.

- **Volatility**  
  DRAM is volatile (loses data without power).  
  NAND is non-volatile (retains bits indefinitely).  

These constraints create a strict **speed-density-cost gradient** that makes equal RAM + SSD size economically and physically impractical in real silicon.

### The Anomaly We Exploit in This Project

In our QEMU-emulated environment (large guest `-m 4G` + unreal mode), we deliberately collapse this hierarchy:

- RAM and "SSD" (emulated disk sectors) become **equivalent-capacity** pools for the training window.  
- No classical paging/offloading thrashing — the entire corpus fits "in-core" with only a constant latency penalty for disk reads.  
- **Infinite effective context length** for the model: every scan/epoch can process gigabytes (up to the 4 GB unreal-mode ceiling) without recompute-from-disk dominating.  
- Training becomes a **closed mathematical fixed-point loop**: the model converges toward a denoiser / near-lossless compressor of the machine's own state (including its weights once saved/loaded to disk). Further epochs are nearly idempotent/circular → catastrophic forgetting is minimized, and attractors emerge naturally (the model starts echoing its own boot messages, structures, or generated junk).  
- **Latency-bandwidth inversion** favors low-arithmetic kernels: with no size penalty for touching "slow" media, simple table lookups and bitwise operations become surprisingly efficient compared to high-FLOP neural nets.

This regime is impossible in real hardware due to the physics/cost walls above — but in emulation, it lets our tiny 256-byte model ingest **orders of magnitude more self-data** per epoch than nature normally allows, leading to deeper, weirder emergent self-regeneration over repeated `train` → `stream` cycles.

### Current Implementation Notes (v2.0+)
- Uses **unreal mode** (a silicon quirk of x86 segment descriptor caching) to access multi-MiB RAM from real-mode code without losing BIOS interrupts.  
- Scans configurable RAM and disk windows from the console, with coarse progress markers and `Esc` abort.  
- Keeps the persisted model state in a small fixed low-LBA checkpoint region so the active disk corpus can grow to multi-gigabyte blobs without bloating stage2.

Run `train` for 50–100 epochs and watch `stream` — the machine starts staring back at itself.
