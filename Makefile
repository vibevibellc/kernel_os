QEMU ?= qemu-system-x86_64
QEMU_IMG ?= qemu-img
NASM ?= nasm
PYTHON ?= python3

VM_DIR := vm
BUILD_DIR := build
BOOT_DIR := boot
BRIDGE_DIR := bridge

DISK := $(VM_DIR)/os-disk.img
DISK_SIZE := 8G
MEMORY := 512M
SERIAL_SOCKET := $(VM_DIR)/com1.sock
WEBHOOK_PORT := 5005

STAGE1_SRC := $(BOOT_DIR)/stage1.asm
STAGE2_SRC := $(BOOT_DIR)/stage2.asm
STAGE1_BIN := $(BUILD_DIR)/stage1.bin
STAGE2_BIN := $(BUILD_DIR)/stage2.bin
STAGE2_MAX_BYTES := 31744

.PHONY: disk boot run run-headless run-chat webhook bridge operator clean

disk:
	mkdir -p $(VM_DIR)
	test -f $(DISK) || $(QEMU_IMG) create -f raw $(DISK) $(DISK_SIZE)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(STAGE1_BIN): $(STAGE1_SRC) | $(BUILD_DIR)
	$(NASM) -f bin -o $(STAGE1_BIN) $(STAGE1_SRC)

$(STAGE2_BIN): $(STAGE2_SRC) | $(BUILD_DIR)
	$(NASM) -f bin -o $(STAGE2_BIN) $(STAGE2_SRC)

boot: disk $(STAGE1_BIN) $(STAGE2_BIN)
	@stage2_size=$$(stat -f%z $(STAGE2_BIN)); \
	if [ "$$stage2_size" -gt "$(STAGE2_MAX_BYTES)" ]; then \
		echo "stage2 is $$stage2_size bytes; limit is $(STAGE2_MAX_BYTES) bytes" >&2; \
		exit 1; \
	fi
	dd if=/dev/zero of=$(DISK) bs=512 count=64 conv=notrunc
	dd if=$(STAGE1_BIN) of=$(DISK) bs=512 count=1 conv=notrunc
	dd if=$(STAGE2_BIN) of=$(DISK) bs=512 seek=1 conv=notrunc

run: boot
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
