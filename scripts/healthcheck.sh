#!/bin/bash
# healthcheck.sh — Liveness checker for memory-vault daemons.
#
# Called by launchd every 60 seconds. Checks tmux sessions and
# auto-restarts dead services. Logs to storage/logs/healthcheck.log.
#
# Compatible with macOS bash 3.2.
#
# Install via: daemon.sh install
# Manual run:  bash scripts/healthcheck.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${VAULT_DIR}/storage/logs"
LOG_FILE="${LOG_DIR}/healthcheck.log"

# launchd 환경은 PATH가 최소한이라 homebrew 도구를 못 찾는다.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# tmux 소켓을 명시적으로 지정 (launchd에서 자동 탐색 실패 방지)
TMUX_SOCKET="/private/tmp/tmux-$(id -u)/default"
TMUX="tmux -S $TMUX_SOCKET"

# tmux 서버 자체가 없으면 할 수 있는 게 없다 — 조용히 종료
if [ ! -S "$TMUX_SOCKET" ]; then
    exit 0
fi

mkdir -p "$LOG_DIR"

# Service definitions (must match daemon.sh)
# Format: "name session command"
SERVICES="
bridge cc-telegram-bridge python3 scripts/telegram_bridge.py
factory cc-factory python3 scripts/feature-factory.py
boss cc-boss-daemon python3 scripts/ai_boss/boss_daemon.py
"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

hc_log() {
    echo "$(ts) $*" >> "$LOG_FILE"
}

restarted=0

echo "$SERVICES" | while read -r svc session cmd; do
    # Skip empty lines
    [ -z "$svc" ] && continue

    if $TMUX has-session -t "$session" 2>/dev/null; then
        continue
    fi

    hc_log "[RESTART] $svc ($session) down — restarting"
    $TMUX new-session -d -s "$session" -c "$VAULT_DIR" "$cmd"
    sleep 2

    if $TMUX has-session -t "$session" 2>/dev/null; then
        hc_log "[OK] $svc restarted successfully"
    else
        hc_log "[FAIL] $svc failed to restart"
    fi

    # Notify via Telegram (best-effort)
    if [ -f "${SCRIPT_DIR}/notify.py" ]; then
        python3 "${SCRIPT_DIR}/notify.py" \
            "healthcheck: $svc auto-restarted" \
            --channel ops --sender healthcheck 2>/dev/null || true
    fi
done
