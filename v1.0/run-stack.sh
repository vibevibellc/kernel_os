#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
QEMU_BIN="${QEMU_BIN:-$(command -v qemu-system-x86_64)}"
MEMORY="${MEMORY:-512M}"
WEBHOOK_PORT="${WEBHOOK_PORT:-5005}"
SERIAL_SOCKET="${SERIAL_SOCKET:-${ROOT_DIR}/vm/com1.sock}"
QEMU_EXTRA_ARGS="${QEMU_EXTRA_ARGS:-}"
WEBHOOK_LOG="${WEBHOOK_LOG:-${ROOT_DIR}/vm/webhook.log}"
BRIDGE_LOG="${BRIDGE_LOG:-${ROOT_DIR}/vm/bridge.log}"
SESSION_STATE_PATH="${SESSION_STATE_PATH:-${ROOT_DIR}/vm/session_state.json}"
WEBHOOK_URL="http://127.0.0.1:${WEBHOOK_PORT}"
log_tail_pid=""

mkdir -p "${ROOT_DIR}/vm"
touch "${WEBHOOK_LOG}" "${BRIDGE_LOG}"
rm -f "${SESSION_STATE_PATH}"

webhook_pid=""
bridge_pid=""

cleanup() {
  local exit_code=$?
  if [[ -n "${bridge_pid}" ]]; then
    kill "${bridge_pid}" 2>/dev/null || true
    wait "${bridge_pid}" 2>/dev/null || true
  fi
  if [[ -n "${log_tail_pid}" ]]; then
    kill "${log_tail_pid}" 2>/dev/null || true
    wait "${log_tail_pid}" 2>/dev/null || true
  fi
  if [[ -n "${webhook_pid}" ]]; then
    kill "${webhook_pid}" 2>/dev/null || true
    wait "${webhook_pid}" 2>/dev/null || true
  fi
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

rm -f "${SERIAL_SOCKET}"

echo "starting webhook on ${WEBHOOK_URL}"
PYTHONUNBUFFERED=1 WEBHOOK_PORT="${WEBHOOK_PORT}" SESSION_STATE_PATH="${SESSION_STATE_PATH}" \
  "${PYTHON_BIN}" "${ROOT_DIR}/bridge/anthropic_webhook.py" \
  >"${WEBHOOK_LOG}" 2>&1 &
webhook_pid=$!

for _ in $(seq 1 40); do
  if ! kill -0 "${webhook_pid}" 2>/dev/null; then
    echo "webhook exited during startup; see ${WEBHOOK_LOG}" >&2
    wait "${webhook_pid}" || true
    exit 1
  fi
  if "${PYTHON_BIN}" - <<PY >/dev/null 2>&1
import socket
socket.create_connection(("127.0.0.1", ${WEBHOOK_PORT}), timeout=0.2).close()
PY
  then
    break
  fi
  sleep 0.25
done

if ! "${PYTHON_BIN}" - <<PY >/dev/null 2>&1
import socket
socket.create_connection(("127.0.0.1", ${WEBHOOK_PORT}), timeout=0.2).close()
PY
then
  echo "webhook failed to start; see ${WEBHOOK_LOG}" >&2
  exit 1
fi

echo "starting qemu with socket serial at ${SERIAL_SOCKET}"
(
  cd "${ROOT_DIR}"
  MEMORY="${MEMORY}" QEMU_BIN="${QEMU_BIN}" SERIAL_MODE=socket SERIAL_SOCKET="${SERIAL_SOCKET}" \
    ./run-vm.sh ${QEMU_EXTRA_ARGS}
) &
qemu_pid=$!

for _ in $(seq 1 40); do
  if [[ -S "${SERIAL_SOCKET}" ]]; then
    break
  fi
  if ! kill -0 "${qemu_pid}" 2>/dev/null; then
    echo "qemu exited before opening ${SERIAL_SOCKET}" >&2
    wait "${qemu_pid}"
    exit 1
  fi
  sleep 0.25
done

if [[ ! -S "${SERIAL_SOCKET}" ]]; then
  echo "serial socket ${SERIAL_SOCKET} was not created" >&2
  kill "${qemu_pid}" 2>/dev/null || true
  wait "${qemu_pid}" 2>/dev/null || true
  exit 1
fi

echo "starting serial bridge"
PYTHONUNBUFFERED=1 "${PYTHON_BIN}" "${ROOT_DIR}/bridge/serial_to_anthropic.py" \
  --socket "${SERIAL_SOCKET}" \
  --webhook "${WEBHOOK_URL}" \
  >"${BRIDGE_LOG}" 2>&1 &
bridge_pid=$!

sleep 0.5
if ! kill -0 "${bridge_pid}" 2>/dev/null; then
  echo "serial bridge exited during startup; see ${BRIDGE_LOG}" >&2
  wait "${bridge_pid}" || true
  exit 1
fi

echo "integrated stack ready"
echo "webhook log: ${WEBHOOK_LOG}"
echo "bridge log: ${BRIDGE_LOG}"
echo "streaming webhook + bridge logs below"

tail -n 0 -f "${WEBHOOK_LOG}" "${BRIDGE_LOG}" &
log_tail_pid=$!

wait "${qemu_pid}"
