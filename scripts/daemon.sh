#!/bin/bash
# daemon.sh — Unified service management CLI for memory-vault daemons.
#
# Manages tmux-based daemon sessions (bridge, factory) and launchd healthcheck.
# All state detection uses `tmux has-session` for compatibility with
# vault-ui, health_check, and pool.sh.
#
# Compatible with macOS bash 3.2 (no associative arrays).
#
# Usage:
#   daemon.sh start [all|bridge|factory]
#   daemon.sh stop [all|bridge|factory]
#   daemon.sh restart [all|bridge|factory]
#   daemon.sh status
#   daemon.sh logs <service> [lines]
#   daemon.sh install      # Install launchd healthcheck plist
#   daemon.sh uninstall    # Remove launchd healthcheck plist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${VAULT_DIR}/storage/logs"
PLIST_LABEL="com.memoryvault.healthcheck"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

# ── Service Definitions ──────────────────────────────────────────────────────
# Bash 3.2 compatible — no associative arrays.

ALL_SERVICES="bridge factory"

_session_name() {
    case "$1" in
        bridge)  echo "cc-telegram-bridge" ;;
        factory) echo "cc-factory" ;;
        *) echo ""; return 1 ;;
    esac
}

_command() {
    case "$1" in
        bridge)  echo "python3 scripts/telegram_bridge.py" ;;
        factory) echo "python3 scripts/feature-factory.py" ;;
        *) echo ""; return 1 ;;
    esac
}

_is_known_service() {
    case "$1" in
        bridge|factory) return 0 ;;
        *) return 1 ;;
    esac
}

# ── Helpers ──────────────────────────────────────────────────────────────────

_is_running() {
    local session
    session="$(_session_name "$1")"
    tmux has-session -t "$session" 2>/dev/null
}

_get_pid() {
    local session
    session="$(_session_name "$1")"
    tmux list-panes -t "$session" -F '#{pane_pid}' 2>/dev/null | head -1
}

_get_uptime() {
    local session created now elapsed h m
    session="$(_session_name "$1")"
    created=$(tmux display-message -t "$session" -p '#{session_created}' 2>/dev/null) || return 1
    now=$(date +%s)
    elapsed=$(( now - created ))
    h=$(( elapsed / 3600 ))
    m=$(( (elapsed % 3600) / 60 ))
    if [ "$h" -gt 0 ]; then
        echo "${h}h ${m}m"
    else
        echo "${m}m"
    fi
}

_last_log_line() {
    local svc="$1"
    case "$svc" in
        bridge)
            if [ -f "${LOG_DIR}/bridge.log" ]; then
                tail -1 "${LOG_DIR}/bridge.log" 2>/dev/null | cut -c1-60
            else
                tmux capture-pane -t "$(_session_name bridge)" -p 2>/dev/null | grep -v '^$' | tail -1 | cut -c1-60
            fi
            ;;
        factory)
            if [ -f "${LOG_DIR}/feature-factory.jsonl" ]; then
                tail -1 "${LOG_DIR}/feature-factory.jsonl" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.readline())
    print('{} [{}] {}'.format(d.get('ts','')[:19], d.get('level','?'), d.get('msg','')[:40]))
except: print('(parse error)')
" 2>/dev/null
            fi
            ;;
    esac
}

_ensure_log_dir() {
    mkdir -p "$LOG_DIR"
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_start() {
    local target="${1:-all}"
    _ensure_log_dir

    if [ "$target" = "all" ]; then
        for svc in $ALL_SERVICES; do
            _start_one "$svc"
        done
    elif _is_known_service "$target"; then
        _start_one "$target"
    else
        echo "[err] Unknown service: $target"
        echo "Available: $ALL_SERVICES"
        exit 1
    fi
}

_kill_orphan_procs() {
    # tmux 세션 밖에서 돌고 있는 좀비 프로세스 정리
    local svc="$1"
    local cmd session pane_pid
    cmd="$(_command "$svc")"
    session="$(_session_name "$svc")"

    # tmux 세션의 정상 PID (있으면)
    pane_pid=""
    if _is_running "$svc"; then
        pane_pid="$(_get_pid "$svc" 2>/dev/null || echo "")"
    fi

    # cmd 패턴으로 모든 프로세스 검색, 정상 PID 제외하고 kill
    local pids
    pids=$(pgrep -f "$cmd" 2>/dev/null || true)
    for pid in $pids; do
        [ -z "$pid" ] && continue
        [ "$pid" = "$$" ] && continue
        [ -n "$pane_pid" ] && [ "$pid" = "$pane_pid" ] && continue
        echo "[cleanup] Killing orphan $svc process (PID $pid)"
        kill "$pid" 2>/dev/null || true
    done
}

_start_one() {
    local svc="$1"
    local session cmd
    session="$(_session_name "$svc")"
    cmd="$(_command "$svc")"

    # 좀비 프로세스 정리 (tmux 세션 밖에서 도는 잔여 프로세스)
    _kill_orphan_procs "$svc"

    if _is_running "$svc"; then
        echo "[skip] $svc already running (session: $session)"
        return 0
    fi

    printf "Starting %s..." "$svc"
    tmux new-session -d -s "$session" -c "$VAULT_DIR" "$cmd"
    sleep 2

    if _is_running "$svc"; then
        echo " ok (session: $session)"
    else
        echo " FAILED"
        return 1
    fi
}

cmd_stop() {
    local target="${1:-all}"

    if [ "$target" = "all" ]; then
        for svc in $ALL_SERVICES; do
            _stop_one "$svc"
        done
    elif _is_known_service "$target"; then
        _stop_one "$target"
    else
        echo "[err] Unknown service: $target"
        exit 1
    fi
}

_stop_one() {
    local svc="$1"
    local session
    session="$(_session_name "$svc")"

    if ! _is_running "$svc"; then
        echo "[skip] $svc not running"
        return 0
    fi

    printf "Stopping %s..." "$svc"

    # Graceful: send Ctrl-C (SIGINT)
    tmux send-keys -t "$session" C-c 2>/dev/null || true
    sleep 3

    # If still alive, force kill
    if _is_running "$svc"; then
        tmux kill-session -t "$session" 2>/dev/null || true
        sleep 1
    fi

    if _is_running "$svc"; then
        echo " FAILED (session still exists)"
        return 1
    else
        echo " ok"
    fi
}

cmd_restart() {
    local target="${1:-all}"
    cmd_stop "$target"
    cmd_start "$target"
}

cmd_status() {
    printf "%-16s %-12s %-7s %-9s %s\n" "Service" "State" "PID" "Uptime" "Last Output"
    printf "%-16s %-12s %-7s %-9s %s\n" "────────────────" "────────────" "───────" "─────────" "────────────────────"

    for svc in $ALL_SERVICES; do
        local session state pid uptime last_line
        session="$(_session_name "$svc")"

        if _is_running "$svc"; then
            state="● running"
            pid="$(_get_pid "$svc" 2>/dev/null || echo "?")"
            uptime="$(_get_uptime "$svc" 2>/dev/null || echo "?")"
            last_line="$(_last_log_line "$svc" 2>/dev/null || echo "")"
        else
            state="○ stopped"
            pid="-"
            uptime="-"
            last_line=""
        fi

        printf "%-16s %-12s %-7s %-9s %s\n" "$svc" "$state" "$pid" "$uptime" "$last_line"
    done

    # Healthcheck (launchd) status
    local hc_state
    if launchctl list "$PLIST_LABEL" 2>/dev/null | grep -q "$PLIST_LABEL"; then
        hc_state="● installed (launchd, 60s interval)"
    else
        hc_state="○ not installed"
    fi
    printf "%-16s %s\n" "healthcheck" "$hc_state"
}

cmd_logs() {
    local svc="${1:-}"
    local lines="${2:-30}"

    if [ -z "$svc" ]; then
        echo "Usage: daemon.sh logs <service> [lines]"
        echo "Services: bridge, factory, healthcheck"
        exit 1
    fi

    case "$svc" in
        bridge)
            if [ -f "${LOG_DIR}/bridge.log" ]; then
                tail -n "$lines" "${LOG_DIR}/bridge.log"
            else
                echo "(no bridge.log yet — showing tmux pane)"
                tmux capture-pane -t "$(_session_name bridge)" -p 2>/dev/null | tail -n "$lines"
            fi
            ;;
        factory)
            if [ -f "${LOG_DIR}/feature-factory.jsonl" ]; then
                tail -n "$lines" "${LOG_DIR}/feature-factory.jsonl"
            else
                echo "(no factory log found)"
            fi
            ;;
        healthcheck)
            if [ -f "${LOG_DIR}/healthcheck.log" ]; then
                tail -n "$lines" "${LOG_DIR}/healthcheck.log"
            else
                echo "(no healthcheck.log yet)"
            fi
            ;;
        *)
            echo "[err] Unknown service: $svc"
            exit 1
            ;;
    esac
}

cmd_install() {
    _ensure_log_dir
    mkdir -p "$(dirname "$PLIST_PATH")"

    cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${VAULT_DIR}/scripts/healthcheck.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/healthcheck-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/healthcheck-stderr.log</string>
</dict>
</plist>
PLIST

    launchctl load "$PLIST_PATH" 2>/dev/null || true

    if launchctl list "$PLIST_LABEL" 2>/dev/null | grep -q "$PLIST_LABEL"; then
        echo "[ok] Healthcheck installed and loaded"
        echo "  Plist: $PLIST_PATH"
        echo "  Interval: 60s"
        echo "  Logs: ${LOG_DIR}/healthcheck*.log"
    else
        echo "[err] Failed to load plist"
        exit 1
    fi
}

cmd_uninstall() {
    if launchctl list "$PLIST_LABEL" 2>/dev/null | grep -q "$PLIST_LABEL"; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        echo "[ok] Healthcheck unloaded"
    else
        echo "[skip] Healthcheck not loaded"
    fi

    if [ -f "$PLIST_PATH" ]; then
        rm "$PLIST_PATH"
        echo "[ok] Plist removed: $PLIST_PATH"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: daemon.sh <command> [args]

Commands:
  start [all|bridge|factory]   Start service(s) in tmux
  stop [all|bridge|factory]    Graceful stop + tmux kill
  restart [all|bridge|factory] Stop then start
  status                       Show all service states
  logs <service> [lines]       Tail service logs
  install                      Install launchd healthcheck
  uninstall                    Remove launchd healthcheck
EOF
}

case "${1:-}" in
    start)    cmd_start "${2:-all}" ;;
    stop)     cmd_stop "${2:-all}" ;;
    restart)  cmd_restart "${2:-all}" ;;
    status)   cmd_status ;;
    logs)     cmd_logs "${2:-}" "${3:-30}" ;;
    install)  cmd_install ;;
    uninstall) cmd_uninstall ;;
    -h|--help|help) usage ;;
    *)
        usage
        exit 1
        ;;
esac
