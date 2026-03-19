#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QEMU_BIN="${QEMU_BIN:-$(command -v qemu-system-i386)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERIAL_SOCKET="${SERIAL_SOCKET:-${ROOT_DIR}/vm/com1.sock}"
CONTROL_SOCKET="${CONTROL_SOCKET:-${ROOT_DIR}/vm/bridge_control.sock}"
MEMORY="${MEMORY:-64M}"
SMP="${SMP:-1}"
QEMU_DISPLAY="${QEMU_DISPLAY:-}"
bridge_pid=""
qemu_pid=""

if [[ -z "${QEMU_BIN}" ]]; then
  echo "qemu-system-i386 was not found in PATH" >&2
  exit 1
fi

cleanup() {
  local exit_code=$?
  if [[ -n "${bridge_pid}" ]]; then
    kill "${bridge_pid}" 2>/dev/null || true
    wait "${bridge_pid}" 2>/dev/null || true
  fi
  if [[ -n "${qemu_pid}" ]]; then
    kill "${qemu_pid}" 2>/dev/null || true
    wait "${qemu_pid}" 2>/dev/null || true
  fi
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

mkdir -p "${ROOT_DIR}/vm"
rm -f "${SERIAL_SOCKET}"
rm -f "${CONTROL_SOCKET}"

(
  cd "${ROOT_DIR}"
  make boot >/dev/null
)

QEMU_ARGS=(
  -machine q35,i8042=off,usb=on
  -cpu qemu32
  -accel tcg,thread=multi
  -smp "${SMP}"
  -device usb-kbd
  -no-reboot
  -m "${MEMORY}"
  -drive "format=raw,file=${ROOT_DIR}/vm/os-disk.img"
  -chardev "socket,id=com1,path=${SERIAL_SOCKET},server=on,wait=off"
  -serial chardev:com1
)

if [[ -n "${QEMU_DISPLAY}" ]]; then
  QEMU_ARGS+=(-display "${QEMU_DISPLAY}")
fi

"${QEMU_BIN}" "${QEMU_ARGS[@]}" &
qemu_pid=$!

for _ in $(seq 1 40); do
  if [[ -S "${SERIAL_SOCKET}" ]]; then
    break
  fi
  if ! kill -0 "${qemu_pid}" 2>/dev/null; then
    echo "qemu exited before opening ${SERIAL_SOCKET}" >&2
    wait "${qemu_pid}" || true
    exit 1
  fi
  sleep 0.25
done

if [[ ! -S "${SERIAL_SOCKET}" ]]; then
  echo "serial socket ${SERIAL_SOCKET} was not created" >&2
  exit 1
fi

echo "starting bridge on ${SERIAL_SOCKET}"
PYTHONUNBUFFERED=1 "${PYTHON_BIN}" "${ROOT_DIR}/bridge/openai_serial_bridge.py" --socket "${SERIAL_SOCKET}" --control-socket "${CONTROL_SOCKET}" &
bridge_pid=$!

sleep 0.5
if ! kill -0 "${bridge_pid}" 2>/dev/null; then
  echo "bridge exited during startup" >&2
  wait "${bridge_pid}" || true
  exit 1
fi

echo "stack ready"
echo "control socket: ${CONTROL_SOCKET}"
echo "set OPENAI_MOCK=1 for local stub replies or export OPENAI_API_KEY for live model calls"

wait "${qemu_pid}"
