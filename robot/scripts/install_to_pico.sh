#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/micropython"
PICO_PORT="${PICO_PORT:-}"
MPREMOTE_TIMEOUT_SECONDS="${MPREMOTE_TIMEOUT_SECONDS:-20}"
SELECTED_PORT=""

log() {
  printf '[install_to_pico] %s\n' "$1" >&2
}

fail() {
  printf '[install_to_pico] ERROR: %s\n' "$1" >&2
  exit 1
}

run_step() {
  local label="$1"
  shift

  log "$label"
  if command -v timeout >/dev/null 2>&1; then
    timeout "${MPREMOTE_TIMEOUT_SECONDS}s" "$@"
  else
    "$@"
  fi
  log "Completed: $label"
}

collect_candidate_ports() {
  local port
  local -a candidates=()

  for port in /dev/ttyACM* /dev/ttyUSB* /dev/cu.usbmodem* /dev/cu.usbserial*; do
    if [ -e "$port" ]; then
      candidates+=("$port")
    fi
  done

  printf '%s\n' "${candidates[@]}"
}

print_candidates() {
  local -a ports=("$@")

  if [ "${#ports[@]}" -eq 0 ]; then
    log "No candidate serial devices were found under /dev/ttyACM*, /dev/ttyUSB*, /dev/cu.usb*."
  else
    log "Detected serial devices:"
    printf '  %s\n' "${ports[@]}" >&2
  fi

  if command -v mpremote >/dev/null 2>&1; then
    log "mpremote connect list output:"
    mpremote connect list || true
  fi
}

prompt_for_port() {
  local -a ports=("$@")
  local index
  local choice

  [ -t 0 ] || fail "Multiple serial devices detected and no interactive terminal is available. Re-run with PICO_PORT=/dev/ttyACM0 ./scripts/install_to_pico.sh"

  log "Select the Pico serial device:"
  for index in "${!ports[@]}"; do
    printf '  [%s] %s\n' "$((index + 1))" "${ports[$index]}" >&2
  done
  printf '  [q] Quit\n' >&2

  while true; do
    printf 'Enter selection: ' >&2
    IFS= read -r choice

    if [ "$choice" = "q" ] || [ "$choice" = "Q" ]; then
      fail "Cancelled by user."
    fi

    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#ports[@]}" ]; then
      SELECTED_PORT="${ports[$((choice - 1))]}"
      return
    fi

    log "Invalid selection. Choose a number from the list or 'q' to quit."
  done
}

resolve_port() {
  if [ -n "$PICO_PORT" ]; then
    [ -e "$PICO_PORT" ] || fail "PICO_PORT '$PICO_PORT' does not exist."
    SELECTED_PORT="$PICO_PORT"
    return
  fi

  mapfile -t detected_ports < <(collect_candidate_ports)

  if [ "${#detected_ports[@]}" -eq 1 ]; then
    SELECTED_PORT="${detected_ports[0]}"
    return
  fi

  print_candidates "${detected_ports[@]}"

  if [ "${#detected_ports[@]}" -gt 1 ]; then
    prompt_for_port "${detected_ports[@]}"
    return
  fi

  fail "No Pico serial device detected. Make sure the board is connected and running MicroPython."
}

check_prereqs() {
  command -v mpremote >/dev/null 2>&1 || fail "mpremote is not installed in this environment."
  [ -f "$SOURCE_DIR/main.py" ] || fail "Missing $SOURCE_DIR/main.py"
  [ -f "$SOURCE_DIR/boot.py" ] || fail "Missing $SOURCE_DIR/boot.py"
  [ -f "$SOURCE_DIR/secrets.py" ] || fail "Create robot/micropython/secrets.py from secrets.example.py first."
}

main() {
  check_prereqs

  resolve_port
  local port="$SELECTED_PORT"

  log "Using serial port: $port"
  log "mpremote timeout: ${MPREMOTE_TIMEOUT_SECONDS}s"
  log "If this hangs or fails, first confirm the board is running MicroPython and no other tool has the port open."

  # Use 'resume' to skip soft-reset when entering raw REPL. This avoids
  # re-running boot.py which re-enumerates USB (dual CDC) and kills the
  # serial connection mid-operation.
  run_step "Checking raw REPL access on $port" \
    mpremote connect "$port" resume fs ls

  run_step "Installing usb-device-cdc package on Pico" \
    mpremote connect "$port" resume mip install usb-device-cdc

  run_step "Copying boot.py to the Pico" \
    mpremote connect "$port" resume fs cp "$SOURCE_DIR/boot.py" :boot.py

  run_step "Copying main.py to the Pico" \
    mpremote connect "$port" resume fs cp "$SOURCE_DIR/main.py" :main.py

  run_step "Copying secrets.py to the Pico" \
    mpremote connect "$port" resume fs cp "$SOURCE_DIR/secrets.py" :secrets.py

  run_step "Resetting the Pico so the new code starts" \
    mpremote connect "$port" resume reset

  log "MicroPython files copied successfully."
  log "After reset the Pico exposes two USB serial ports (with VID 2e8a):"
  log "  First port  = MicroPython REPL (mpremote / interactive use)"
  log "  Second port = Data channel (used by speech-app for USB communication)"
  log "Run 'mpremote connect list' to see which /dev/ttyACM* ports belong to the Pico."
}

main "$@"
