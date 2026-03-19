QEMU ?= qemu-system-i386
QEMU_IMG ?= qemu-img
PYTHON ?= python3

VM_DIR := vm
BUILD_DIR := build
SOURCE_DIR := binary
HEX_DIR := hex
TOOLS_DIR := tools

DISK := $(VM_DIR)/os-disk.img
CONTROL_SOCKET := $(VM_DIR)/bridge_control.sock
JOURNAL := $(VM_DIR)/kernel_journal.jsonl
MEMORY := 64M
DISK_SIZE := 64M
SMP ?= 1
CPU_MODEL ?= qemu32
QEMU_ACCEL ?= tcg,thread=multi
HEADLESS_PORT ?= 5555
QEMU_RUN_ARGS := -machine q35,i8042=off,usb=on -cpu $(CPU_MODEL) -accel $(QEMU_ACCEL) -smp $(SMP) -device usb-kbd -no-reboot
QEMU_HEADLESS_ARGS := -display none -serial tcp:127.0.0.1:$(HEADLESS_PORT),server,nowait
QEMU_STDIO_ARGS := -display none -serial mon:stdio

STAGE1_SOURCE_BIN := $(SOURCE_DIR)/stage1.bin
STAGE2_SOURCE_BIN := $(SOURCE_DIR)/stage2.bin
STAGE1_HEX := $(HEX_DIR)/stage1.hex
STAGE2_HEX := $(HEX_DIR)/stage2.hex
STAGE1_BIN := $(BUILD_DIR)/stage1.bin
STAGE2_BIN := $(BUILD_DIR)/stage2.bin
STAGE2_LOAD_SECTORS := 64
BOOT_REGION_SECTORS := 65
STAGE2_MAX_BYTES := 32768

.PHONY: disk fresh-disk boot run run-headless run-stdio run-fresh run-headless-fresh run-stdio-fresh run-preserve run-headless-preserve run-stdio-preserve run-stack transport-info transport-read transport-write transport-persist transport-stream transport-shadow-info transport-shadow-init transport-shadow-read transport-shadow-write transport-shadow-diff transport-shadow-promote transport-rollback journal-replay sync-binary-from-hex sync-hex-from-bin clean

disk:
	mkdir -p $(VM_DIR)
	@if [ ! -f "$(DISK)" ]; then \
		 $(QEMU_IMG) create -f raw $(DISK) $(DISK_SIZE); \
	else \
		 $(QEMU_IMG) resize --shrink -f raw $(DISK) $(DISK_SIZE); \
	fi

fresh-disk:
	rm -f $(DISK)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(STAGE1_BIN): $(STAGE1_SOURCE_BIN) Makefile | $(BUILD_DIR)
	cp $(STAGE1_SOURCE_BIN) $(STAGE1_BIN)

$(STAGE2_BIN): $(STAGE2_SOURCE_BIN) Makefile | $(BUILD_DIR)
	cp $(STAGE2_SOURCE_BIN) $(STAGE2_BIN)

boot: disk $(STAGE1_BIN) $(STAGE2_BIN)
	@stage2_size=$$(stat -f%z $(STAGE2_BIN)); \
	stage2_load_bytes=$$(($(STAGE2_LOAD_SECTORS) * 512)); \
	if [ "$$stage2_size" -gt "$(STAGE2_MAX_BYTES)" ]; then \
		echo "stage2 is $$stage2_size bytes; limit is $(STAGE2_MAX_BYTES) bytes" >&2; \
		exit 1; \
	fi; \
	if [ "$$stage2_size" -gt "$$stage2_load_bytes" ]; then \
		echo "stage2 is $$stage2_size bytes; stage1 only loads $$stage2_load_bytes bytes" >&2; \
		exit 1; \
	fi
	dd if=/dev/zero of=$(DISK) bs=512 count=$(BOOT_REGION_SECTORS) conv=notrunc
	dd if=$(STAGE1_BIN) of=$(DISK) bs=512 count=1 conv=notrunc
	dd if=$(STAGE2_BIN) of=$(DISK) bs=512 seek=1 conv=notrunc

run: run-fresh

run-fresh: boot
	$(QEMU) $(QEMU_RUN_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-headless: run-headless-fresh

run-headless-fresh: boot
	$(QEMU) $(QEMU_RUN_ARGS) $(QEMU_HEADLESS_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-stdio: run-stdio-fresh

run-stdio-fresh: boot
	$(QEMU) $(QEMU_RUN_ARGS) $(QEMU_STDIO_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-preserve:
	@test -f "$(DISK)" || { echo "missing $(DISK); run \`make boot\` or a *-fresh target first" >&2; exit 1; }
	$(QEMU) $(QEMU_RUN_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-headless-preserve:
	@test -f "$(DISK)" || { echo "missing $(DISK); run \`make boot\` or a *-fresh target first" >&2; exit 1; }
	$(QEMU) $(QEMU_RUN_ARGS) $(QEMU_HEADLESS_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-stdio-preserve:
	@test -f "$(DISK)" || { echo "missing $(DISK); run \`make boot\` or a *-fresh target first" >&2; exit 1; }
	$(QEMU) $(QEMU_RUN_ARGS) $(QEMU_STDIO_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-stack:
	./run-stack.sh

transport-info:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) info

transport-read:
	@test -n "$(OFFSET)" || { echo "set OFFSET=0x...." >&2; exit 1; }
	@test -n "$(LENGTH)" || { echo "set LENGTH=0x...." >&2; exit 1; }
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) read --offset $(OFFSET) --length $(LENGTH) $(if $(OUTPUT),--output $(OUTPUT),)

transport-write:
	@test -n "$(OFFSET)" || { echo "set OFFSET=0x...." >&2; exit 1; }
	@test -n "$(DATA)" || { echo "set DATA=\"FA 31 C0\"" >&2; exit 1; }
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) write --offset $(OFFSET) --hex "$(DATA)" $(if $(PERSIST),--persist,) $(if $(VERIFY),--verify,)

transport-persist:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) persist

transport-stream:
	@test -n "$(OFFSET)" || { echo "set OFFSET=0x...." >&2; exit 1; }
	@test -n "$(LENGTH)" || { echo "set LENGTH=0x...." >&2; exit 1; }
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) stream --offset $(OFFSET) --length $(LENGTH) --interval-ms $(or $(INTERVAL_MS),1000) --count $(or $(COUNT),0)

transport-shadow-info:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) shadow-info

transport-shadow-init:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) shadow-init --source $(or $(SHADOW_SOURCE),canonical)

transport-shadow-read:
	@test -n "$(OFFSET)" || { echo "set OFFSET=0x...." >&2; exit 1; }
	@test -n "$(LENGTH)" || { echo "set LENGTH=0x...." >&2; exit 1; }
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) shadow-read --offset $(OFFSET) --length $(LENGTH) $(if $(OUTPUT),--output $(OUTPUT),)

transport-shadow-write:
	@test -n "$(OFFSET)" || { echo "set OFFSET=0x...." >&2; exit 1; }
	@test -n "$(DATA)" || { echo "set DATA=\"AA BB\"" >&2; exit 1; }
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) shadow-write --offset $(OFFSET) --hex "$(DATA)"

transport-shadow-diff:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) shadow-diff --base $(or $(BASE),canonical) --limit-spans $(or $(LIMIT_SPANS),64)

transport-shadow-promote:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) shadow-promote $(if $(PERSIST),--persist,) $(if $(VERIFY),--verify,)

transport-rollback:
	$(PYTHON) $(TOOLS_DIR)/binary_transport.py --socket $(CONTROL_SOCKET) rollback-live $(if $(PERSIST),--persist,) $(if $(VERIFY),--verify,)

journal-replay:
	$(PYTHON) $(TOOLS_DIR)/journal_replay.py --journal $(JOURNAL) $(if $(JSON),--json,) $(if $(TIMELINE),--timeline $(TIMELINE),)

sync-binary-from-hex: $(TOOLS_DIR)/hex_to_bin.py $(STAGE1_HEX) $(STAGE2_HEX)
	mkdir -p $(SOURCE_DIR)
	$(PYTHON) $(TOOLS_DIR)/hex_to_bin.py $(STAGE1_HEX) $(STAGE1_SOURCE_BIN)
	$(PYTHON) $(TOOLS_DIR)/hex_to_bin.py $(STAGE2_HEX) $(STAGE2_SOURCE_BIN)

sync-hex-from-bin: $(TOOLS_DIR)/bin_to_hex.py $(STAGE1_SOURCE_BIN) $(STAGE2_SOURCE_BIN)
	mkdir -p $(HEX_DIR)
	$(PYTHON) $(TOOLS_DIR)/bin_to_hex.py $(STAGE1_SOURCE_BIN) $(STAGE1_HEX)
	$(PYTHON) $(TOOLS_DIR)/bin_to_hex.py $(STAGE2_SOURCE_BIN) $(STAGE2_HEX)

clean:
	rm -rf $(BUILD_DIR)
