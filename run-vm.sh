#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISK_PATH="${DISK_PATH:-${ROOT_DIR}/vm/os-disk.img}"
QEMU_BIN="${QEMU_BIN:-$(command -v qemu-system-x86_64)}"
MEMORY="${MEMORY:-512M}"
SERIAL_MODE="${SERIAL_MODE:-stdio}"
SERIAL_SOCKET="${SERIAL_SOCKET:-${ROOT_DIR}/vm/com1.sock}"
SERIAL_WAIT="${SERIAL_WAIT:-off}"
KEYBOARD_LAYOUT="${KEYBOARD_LAYOUT:-en-us}"
VIDEO_ADAPTER="${VIDEO_ADAPTER:-std}"
DISPLAY_BACKEND="${DISPLAY_BACKEND:-auto}"
DISPLAY_ZOOM_TO_FIT="${DISPLAY_ZOOM_TO_FIT:-on}"
DISPLAY_SHOW_CURSOR="${DISPLAY_SHOW_CURSOR:-on}"
DISPLAY_FULL_SCREEN="${DISPLAY_FULL_SCREEN:-off}"
DISK_LOCKING="${DISK_LOCKING:-off}"

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
    SERIAL_ARGS=(-chardev "socket,id=com1,path=${SERIAL_SOCKET},server=on,wait=${SERIAL_WAIT}" -serial chardev:com1)
    ;;
  *)
    echo "Unsupported SERIAL_MODE=${SERIAL_MODE}. Use stdio or socket." >&2
    exit 1
    ;;
esac

resolve_display_backend() {
  case "${DISPLAY_BACKEND}" in
    auto)
      case "$(uname -s)" in
        Darwin)
          printf 'cocoa,show-cursor=%s,zoom-to-fit=%s,full-screen=%s' \
            "${DISPLAY_SHOW_CURSOR}" "${DISPLAY_ZOOM_TO_FIT}" "${DISPLAY_FULL_SCREEN}"
          ;;
        *)
          printf 'default'
          ;;
      esac
      ;;
    *)
      printf '%s' "${DISPLAY_BACKEND}"
      ;;
  esac
}

DISPLAY_ARGS=()
HAS_DISPLAY_OVERRIDE=0
for arg in "$@"; do
  if [[ "${arg}" == "-display" ]] || [[ "${arg}" == "-nographic" ]]; then
    HAS_DISPLAY_OVERRIDE=1
    break
  fi
done

if [[ "${HAS_DISPLAY_OVERRIDE}" -eq 0 ]]; then
  RESOLVED_DISPLAY_BACKEND="$(resolve_display_backend)"
  if [[ -n "${RESOLVED_DISPLAY_BACKEND}" ]]; then
    DISPLAY_ARGS=(-display "${RESOLVED_DISPLAY_BACKEND}")
  fi
fi

exec "${QEMU_BIN}" \
  -machine pc,accel=tcg \
  -cpu qemu64 \
  -k "${KEYBOARD_LAYOUT}" \
  -vga "${VIDEO_ADAPTER}" \
  -m "${MEMORY}" \
  -smp 1 \
  -drive file="${DISK_PATH}",file.locking="${DISK_LOCKING}",format=raw,if=ide \
  -boot order=c \
  "${SERIAL_ARGS[@]}" \
  "${DISPLAY_ARGS[@]}" \
  -monitor none \
  -net none \
  "$@"
