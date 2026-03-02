#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISK_PATH="${ROOT_DIR}/vm/os-disk.img"
QEMU_BIN="${QEMU_BIN:-$(command -v qemu-system-x86_64)}"
MEMORY="${MEMORY:-512M}"
SERIAL_MODE="${SERIAL_MODE:-stdio}"
SERIAL_SOCKET="${SERIAL_SOCKET:-${ROOT_DIR}/vm/com1.sock}"
KEYBOARD_LAYOUT="${KEYBOARD_LAYOUT:-en-us}"
VIDEO_ADAPTER="${VIDEO_ADAPTER:-std}"
DISPLAY_BACKEND="${DISPLAY_BACKEND:-cocoa,zoom-to-fit=on}"

if [[ ! -f "${DISK_PATH}" ]]; then
  echo "Missing disk image at ${DISK_PATH}. Run 'make disk' first." >&2
  exit 1
fi

case "${SERIAL_MODE}" in
  stdio)
    SERIAL_ARGS=(-serial stdio)
    ;;
  socket)
    rm -f "${SERIAL_SOCKET}"
    SERIAL_ARGS=(-chardev "socket,id=com1,path=${SERIAL_SOCKET},server=on,wait=off" -serial chardev:com1)
    ;;
  *)
    echo "Unsupported SERIAL_MODE=${SERIAL_MODE}. Use stdio or socket." >&2
    exit 1
    ;;
esac

DISPLAY_ARGS=()
HAS_DISPLAY_OVERRIDE=0
for arg in "$@"; do
  if [[ "${arg}" == "-display" ]] || [[ "${arg}" == "-nographic" ]]; then
    HAS_DISPLAY_OVERRIDE=1
    break
  fi
done

if [[ "${HAS_DISPLAY_OVERRIDE}" -eq 0 ]] && [[ -n "${DISPLAY_BACKEND}" ]]; then
  DISPLAY_ARGS=(-display "${DISPLAY_BACKEND}")
fi

exec "${QEMU_BIN}" \
  -machine pc,accel=tcg \
  -cpu qemu64 \
  -k "${KEYBOARD_LAYOUT}" \
  -vga "${VIDEO_ADAPTER}" \
  -m "${MEMORY}" \
  -smp 1 \
  -drive file="${DISK_PATH}",format=raw,if=ide \
  -boot order=c \
  "${SERIAL_ARGS[@]}" \
  "${DISPLAY_ARGS[@]}" \
  -monitor none \
  -net none \
  "$@"
