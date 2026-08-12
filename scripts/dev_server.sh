#!/usr/bin/env bash

set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

run_dir="${TWINSTUDIO_RUN_DIR:-$project_root/.run}"
pid_file="${TWINSTUDIO_PID_FILE:-$run_dir/twinstudio.pid}"
log_file="${TWINSTUDIO_LOG_FILE:-$run_dir/twinstudio.log}"
action="${1:-help}"

fail() {
  printf 'TwinStudio: %s\n' "$*" >&2
  exit 1
}

resolve_binaries() {
  if [[ -n "${TWINSTUDIO_PYTHON_BIN:-}" ]]; then
    python_bin="$TWINSTUDIO_PYTHON_BIN"
  elif [[ -x "$project_root/.venv/bin/python" ]]; then
    python_bin="$project_root/.venv/bin/python"
  else
    python_bin="$(command -v python || true)"
  fi
  [[ -n "$python_bin" && -x "$python_bin" ]] || fail "Python not found; create .venv first"

  if [[ -n "${TWINSTUDIO_BIN:-}" ]]; then
    cli_bin="$TWINSTUDIO_BIN"
  elif [[ -x "$project_root/.venv/bin/twinstudio" ]]; then
    cli_bin="$project_root/.venv/bin/twinstudio"
  else
    cli_bin="$(command -v twinstudio || true)"
  fi
  [[ -n "$cli_bin" && -x "$cli_bin" ]] || fail "twinstudio CLI not found; run make install first"
}

resolve_address() {
  local settings
  settings="$($python_bin -c 'from twinstudio.settings import settings; print(settings.host, settings.port)')" || \
    fail "cannot read TwinStudio settings"
  read -r server_host server_port <<<"$settings"
  [[ "$server_port" =~ ^[0-9]+$ ]] || fail "invalid TWINSTUDIO_PORT: $server_port"
  case "$server_host" in
    0.0.0.0|::|'[::]') health_host="127.0.0.1" ;;
    *) health_host="$server_host" ;;
  esac
  health_url="http://$health_host:$server_port/health"
}

pid_command() {
  ps -p "$1" -o args= 2>/dev/null || true
}

pid_cwd() {
  readlink -f "/proc/$1/cwd" 2>/dev/null || true
}

is_owned_twinstudio_pid() {
  local pid="$1" command cwd
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  command="$(pid_command "$pid")"
  cwd="$(pid_cwd "$pid")"
  [[ "$cwd" == "$project_root" ]] || return 1
  [[ "$command" == *twinstudio* ]] || return 1
  [[ "$command" == *" serve"* || "$command" == *"twinstudio.api:app"* ]]
}

port_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -t -iTCP:"$server_port" -sTCP:LISTEN 2>/dev/null | sort -u || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$server_port" 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u || true
  else
    fail "lsof or fuser is required to identify the process on port $server_port"
  fi
}

known_pids() {
  local pid port_pid on_port=0
  local -a listeners=()
  mapfile -t listeners < <(port_pids)
  if [[ -f "$pid_file" ]]; then
    read -r pid <"$pid_file" || true
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      for port_pid in "${listeners[@]}"; do
        [[ "$pid" == "$port_pid" ]] && on_port=1
      done
      if is_owned_twinstudio_pid "$pid" || ((on_port == 1)); then
        printf '%s\n' "$pid"
      else
        rm -f -- "$pid_file"
      fi
    else
      rm -f -- "$pid_file"
    fi
  fi
  printf '%s\n' "${listeners[@]}"
}

stop_instance() {
  local pid command
  local -a candidates=() owned=() foreign=()
  declare -A seen=()
  while IFS= read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ -n "${seen[$pid]:-}" ]] && continue
    seen[$pid]=1
    candidates+=("$pid")
    if is_owned_twinstudio_pid "$pid"; then
      owned+=("$pid")
    elif kill -0 "$pid" 2>/dev/null; then
      foreign+=("$pid")
    fi
  done < <(known_pids)

  if ((${#foreign[@]})); then
    for pid in "${foreign[@]}"; do
      command="$(pid_command "$pid")"
      printf 'TwinStudio: refusing to kill unrelated PID %s on port %s: %s\n' \
        "$pid" "$server_port" "$command" >&2
    done
    return 1
  fi

  if ((${#owned[@]} == 0)); then
    rm -f -- "$pid_file"
    printf 'TwinStudio is already stopped on %s:%s\n' "$server_host" "$server_port"
    return 0
  fi

  printf 'Stopping TwinStudio PID(s): %s\n' "${owned[*]}"
  kill -TERM "${owned[@]}" 2>/dev/null || true
  for _ in $(seq 1 50); do
    local alive=0
    for pid in "${owned[@]}"; do
      kill -0 "$pid" 2>/dev/null && alive=1
    done
    ((alive == 0)) && break
    sleep 0.1
  done
  for pid in "${owned[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      printf 'TwinStudio: PID %s did not stop; sending SIGKILL\n' "$pid" >&2
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
  rm -f -- "$pid_file"
}

start_instance() {
  local pid payload
  mkdir -p -- "$run_dir"
  stop_instance
  : >"$log_file"
  nohup setsid "$cli_bin" serve >>"$log_file" 2>&1 </dev/null &
  pid=$!
  printf '%s\n' "$pid" >"$pid_file"

  for _ in $(seq 1 60); do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    payload="$(curl --fail --silent --show-error --max-time 2 "$health_url" 2>/dev/null || true)"
    if [[ "$payload" == *'"status":"ok"'* ]]; then
      printf 'TwinStudio started: PID=%s URL=http://%s:%s LOG=%s\n' \
        "$pid" "$health_host" "$server_port" "$log_file"
      return 0
    fi
    sleep 0.25
  done

  printf 'TwinStudio failed to become healthy at %s\n' "$health_url" >&2
  tail -n 80 "$log_file" >&2 || true
  is_owned_twinstudio_pid "$pid" && kill -TERM "$pid" 2>/dev/null || true
  rm -f -- "$pid_file"
  return 1
}

show_status() {
  local pid payload=""
  local -a pids=()
  mapfile -t pids < <(known_pids)
  pid="${pids[0]:-}"
  payload="$(curl --fail --silent --show-error --max-time 2 "$health_url" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && is_owned_twinstudio_pid "$pid" && [[ "$payload" == *'"status":"ok"'* ]]; then
    printf 'TwinStudio is running: PID=%s URL=http://%s:%s\n%s\n' \
      "$pid" "$health_host" "$server_port" "$payload"
    return 0
  fi
  printf 'TwinStudio is not running on %s:%s\n' "$server_host" "$server_port"
  return 1
}

show_help() {
  printf '%s\n' \
    'Usage: scripts/dev_server.sh start|restart|stop|status|health|logs|logs-follow|foreground' \
    '' \
    'start/restart replaces an existing TwinStudio process owned by this workspace.' \
    'An unrelated process using the configured port is never killed.'
}

resolve_binaries
resolve_address

case "$action" in
  start) start_instance ;;
  restart) start_instance ;;
  stop) stop_instance ;;
  status) show_status ;;
  health) curl --fail --silent --show-error "$health_url"; printf '\n' ;;
  logs)
    [[ -f "$log_file" ]] || fail "log file does not exist: $log_file"
    tail -n "${LINES:-100}" "$log_file"
    ;;
  logs-follow)
    [[ -f "$log_file" ]] || fail "log file does not exist: $log_file"
    tail -n "${LINES:-100}" -f "$log_file"
    ;;
  foreground)
    stop_instance
    exec "$cli_bin" serve
    ;;
  help|-h|--help) show_help ;;
  *) show_help >&2; exit 2 ;;
esac
