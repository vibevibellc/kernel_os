QEMU ?= qemu-system-i386
QEMU_IMG ?= qemu-img
NASM ?= nasm
NASMFLAGS ?= -w+all -w-reloc-abs-word

VM_DIR := vm
BUILD_DIR := build
BOOT_DIR := boot

DISK := $(VM_DIR)/os-disk.img
MEMORY := 4096M
DISK_SIZE := 4G
MODEL_BLOB := model.safetensors
MODEL_BLOB_LBA ?= 4096
MODEL_STATE_LBA ?= 256
MODEL_BLOB_PRESENT := $(shell test -f "$(MODEL_BLOB)" && echo 1 || echo 0)
MODEL_BLOB_SECTORS := $(shell python3 -c 'import os; path="$(MODEL_BLOB)"; print((os.path.getsize(path) + 511) // 512 if os.path.exists(path) else 0)')
SMP ?= 8
CPU_MODEL ?= qemu32
QEMU_ACCEL ?= tcg,thread=multi
HEADLESS_PORT ?= 5555
QEMU_RUN_ARGS := -machine q35,i8042=off,usb=on -cpu $(CPU_MODEL) -accel $(QEMU_ACCEL) -smp $(SMP) -device usb-kbd -no-reboot
QEMU_HEADLESS_ARGS := -display none -serial tcp:127.0.0.1:$(HEADLESS_PORT),server,nowait
QEMU_STDIO_ARGS := -display none -serial mon:stdio

STAGE1_SRC := $(BOOT_DIR)/stage1.asm
STAGE2_SRC := $(BOOT_DIR)/stage2.asm
STAGE2_PARTS := $(wildcard $(BOOT_DIR)/stage1/*.asm) $(wildcard $(BOOT_DIR)/stage2/*.asm)
STAGE1_BIN := $(BUILD_DIR)/stage1.bin
STAGE2_BIN := $(BUILD_DIR)/stage2.bin
STAGE2_LOAD_SECTORS := 64
BOOT_REGION_SECTORS := 65
STAGE2_MAX_BYTES := 32768
DISK_TOTAL_SECTORS := 8388608
DEFAULT_DISK_SCAN_LBA := 96
DEFAULT_DISK_SCAN_PAGES := 2048

ifeq ($(MODEL_BLOB_PRESENT),1)
DEFAULT_DISK_SCAN_LBA := $(MODEL_BLOB_LBA)
DEFAULT_DISK_SCAN_PAGES := $(MODEL_BLOB_SECTORS)
endif

STAGE2_NASMFLAGS := $(NASMFLAGS) \
	-DDEFAULT_DISK_SCAN_LBA=$(DEFAULT_DISK_SCAN_LBA) \
	-DDEFAULT_DISK_SCAN_PAGES=$(DEFAULT_DISK_SCAN_PAGES) \
	-DMODEL_STATE_LBA=$(MODEL_STATE_LBA)

.PHONY: disk boot run run-headless run-stdio clean

disk:
	mkdir -p $(VM_DIR)
	@if [ ! -f "$(DISK)" ]; then \
		$(QEMU_IMG) create -f raw $(DISK) $(DISK_SIZE); \
	else \
		$(QEMU_IMG) resize -f raw $(DISK) $(DISK_SIZE); \
	fi

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(STAGE1_BIN): $(STAGE1_SRC) $(wildcard $(BOOT_DIR)/stage1/*.asm) Makefile | $(BUILD_DIR)
	$(NASM) $(NASMFLAGS) -DSTAGE2_SECTORS=$(STAGE2_LOAD_SECTORS) -f bin -o $(STAGE1_BIN) $(STAGE1_SRC)

$(STAGE2_BIN): $(STAGE2_SRC) $(wildcard $(BOOT_DIR)/stage2/*.asm) Makefile | $(BUILD_DIR)
	$(NASM) $(STAGE2_NASMFLAGS) -f bin -o $(STAGE2_BIN) $(STAGE2_SRC)

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
	fi; \
	if [ "$(MODEL_BLOB_PRESENT)" = "1" ]; then \
		blob_end=$$(( $(MODEL_BLOB_LBA) + $(MODEL_BLOB_SECTORS) )); \
		if [ "$$blob_end" -gt "$(DISK_TOTAL_SECTORS)" ]; then \
			echo "model blob ends at sector $$blob_end; disk only has $(DISK_TOTAL_SECTORS) sectors" >&2; \
			exit 1; \
		fi; \
	fi
	dd if=/dev/zero of=$(DISK) bs=512 count=$(BOOT_REGION_SECTORS) conv=notrunc
	dd if=$(STAGE1_BIN) of=$(DISK) bs=512 count=1 conv=notrunc
	dd if=$(STAGE2_BIN) of=$(DISK) bs=512 seek=1 conv=notrunc
	@if [ "$(MODEL_BLOB_PRESENT)" = "1" ]; then \
		dd if=$(MODEL_BLOB) of=$(DISK) bs=512 seek=$(MODEL_BLOB_LBA) conv=notrunc; \
	fi

run: boot
	$(QEMU) $(QEMU_RUN_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-headless: boot
	$(QEMU) $(QEMU_RUN_ARGS) $(QEMU_HEADLESS_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

run-stdio: boot
	$(QEMU) $(QEMU_RUN_ARGS) $(QEMU_STDIO_ARGS) -m $(MEMORY) -drive format=raw,file=$(DISK)

clean:
	rm -rf $(BUILD_DIR)
