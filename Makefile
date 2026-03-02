QEMU ?= qemu-system-x86_64
QEMU_IMG ?= qemu-img
NASM ?= nasm
NASMFLAGS ?= -w+all -w-reloc-abs-word
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

VM_DIR := vm
BUILD_DIR := build
BOOT_DIR := boot
BRIDGE_DIR := bridge

DISK := $(VM_DIR)/os-disk.img
MEMORY := 512M
DISK_SIZE := $(MEMORY)
SERIAL_SOCKET := $(VM_DIR)/com1.sock
WEBHOOK_PORT := 5005

STAGE1_SRC := $(BOOT_DIR)/stage1.asm
STAGE2_SRC := $(BOOT_DIR)/stage2.asm
STAGE2_PARTS := $(wildcard $(BOOT_DIR)/stage2/*.asm)
STAGE1_BIN := $(BUILD_DIR)/stage1.bin
STAGE2_BIN := $(BUILD_DIR)/stage2.bin
STAGE2_LOAD_SECTORS := 1024
BOOT_REGION_SECTORS := 1025
STAGE2_MAX_BYTES := 524288

.PHONY: disk boot run run-raw run-headless run-chat webhook bridge operator clean

disk:
	mkdir -p $(VM_DIR)
	@if [ ! -f "$(DISK)" ]; then \
		$(QEMU_IMG) create -f raw $(DISK) $(DISK_SIZE); \
	else \
		$(QEMU_IMG) resize --shrink -f raw $(DISK) $(DISK_SIZE); \
	fi

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(STAGE1_BIN): $(STAGE1_SRC) | $(BUILD_DIR)
	$(NASM) $(NASMFLAGS) -DSTAGE2_SECTORS=$(STAGE2_LOAD_SECTORS) -f bin -o $(STAGE1_BIN) $(STAGE1_SRC)

$(STAGE2_BIN): $(STAGE2_SRC) $(STAGE2_PARTS) | $(BUILD_DIR)
	$(NASM) $(NASMFLAGS) -f bin -o $(STAGE2_BIN) $(STAGE2_SRC)

boot: disk $(STAGE1_BIN) $(STAGE2_BIN)
	@stage2_size=$$(stat -f%z $(STAGE2_BIN)); \
	if [ "$$stage2_size" -gt "$(STAGE2_MAX_BYTES)" ]; then \
		echo "stage2 is $$stage2_size bytes; limit is $(STAGE2_MAX_BYTES) bytes" >&2; \
		exit 1; \
	fi
	dd if=/dev/zero of=$(DISK) bs=512 count=$(BOOT_REGION_SECTORS) conv=notrunc
	dd if=$(STAGE1_BIN) of=$(DISK) bs=512 count=1 conv=notrunc
	dd if=$(STAGE2_BIN) of=$(DISK) bs=512 seek=1 conv=notrunc

run: boot
	chmod +x ./run-stack.sh
	PYTHON_BIN=$(PYTHON) MEMORY=$(MEMORY) QEMU_BIN=$(QEMU) WEBHOOK_PORT=$(WEBHOOK_PORT) SERIAL_SOCKET=$(SERIAL_SOCKET) ./run-stack.sh

run-raw: boot
	MEMORY=$(MEMORY) QEMU_BIN=$(QEMU) ./run-vm.sh

run-headless: boot
	MEMORY=$(MEMORY) QEMU_BIN=$(QEMU) ./run-vm.sh -display none

run-chat: boot
	MEMORY=$(MEMORY) QEMU_BIN=$(QEMU) SERIAL_MODE=socket SERIAL_SOCKET=$(SERIAL_SOCKET) ./run-vm.sh

webhook:
	$(PYTHON) $(BRIDGE_DIR)/anthropic_webhook.py

bridge:
	$(PYTHON) $(BRIDGE_DIR)/serial_to_anthropic.py --socket $(SERIAL_SOCKET) --webhook http://127.0.0.1:$(WEBHOOK_PORT)

operator:
	$(PYTHON) $(BRIDGE_DIR)/operator_cli.py --webhook http://127.0.0.1:$(WEBHOOK_PORT) list-sessions

clean:
	rm -rf $(BUILD_DIR)
