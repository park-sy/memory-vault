#!/bin/bash
# pool.sh — Worker Pool Management
#
# 워커 tmux 세션을 관리한다. 오케스트레이터(claude 세션)가 이 스크립트를 호출.
# tmux 자체가 상태 저장소 (별도 DB 불필요).
#
# Usage:
#   pool.sh init [size]        워커 세션 생성 (default: 3)
#   pool.sh status             전체 상태 출력
#   pool.sh send <N> <msg>     워커 N에 메시지 전송
#   pool.sh capture <N> [lines] 워커 N의 최근 출력 캡처
#   pool.sh teardown           전체 종료
#   pool.sh reset <N>          워커 N 재시작

set -euo pipefail

VAULT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_ROLE="${VAULT_DIR}/01-org/engineering/worker.md"
PREFIX="cc-pool"
PROJECT_DIR="/Users/hiyeop/dev/whos-life"

# ── Helpers ──────────────────────────────────────────────────

_build_worker_cmd() {
    local cmd="env -u CLAUDECODE claude --dangerously-skip-permissions"
    if [[ -f "$WORKER_ROLE" ]]; then
        cmd="${cmd} --append-system-prompt \"\$(cat '${WORKER_ROLE}')\""
    fi
    echo "$cmd"
}

_send_text() {
    local session="$1"
    local text="$2"

    if [[ ${#text} -gt 500 ]]; then
        local tmp
        tmp=$(mktemp /tmp/cc-pool-XXXXXX.txt)
        printf '%s' "$text" > "$tmp"
        tmux load-buffer "$tmp"
        tmux paste-buffer -t "$session"
        tmux send-keys -t "$session" Enter
        rm -f "$tmp"
    else
        tmux send-keys -t "$session" "$text" Enter
    fi
}

# ── Commands ─────────────────────────────────────────────────

cmd_init() {
    local size="${1:-3}"
    echo "Initializing ${size} workers..."
    local created=0

    for i in $(seq 1 "$size"); do
        local name="${PREFIX}-${i}"
        if tmux has-session -t "$name" 2>/dev/null; then
            echo "  [skip] $name already exists"
            continue
        fi

        tmux new-session -d -s "$name" -c "$PROJECT_DIR"
        sleep 0.5
        tmux send-keys -t "$name" "$(_build_worker_cmd)" Enter
        echo "  [ok] $name created"
        created=$((created + 1))
    done

    echo "Done: ${created} workers created"
}

cmd_status() {
    local sessions
    sessions=$(tmux ls -F '#{session_name}' 2>/dev/null | grep "^${PREFIX}-" | sort || true)

    if [[ -z "$sessions" ]]; then
        echo "No workers running."
        return
    fi

    printf "%-14s %s\n" "SESSION" "LAST OUTPUT"
    printf "%-14s %s\n" "──────────────" "────────────────────────────────────────"

    for name in $sessions; do
        local last_line
        last_line=$(tmux capture-pane -t "$name" -p 2>/dev/null | grep -v '^$' | tail -1 || echo "(empty)")
        # 80자 초과 시 잘라냄
        if [[ ${#last_line} -gt 60 ]]; then
            last_line="${last_line:0:57}..."
        fi
        printf "%-14s %s\n" "$name" "$last_line"
    done

    echo ""
    echo "Total: $(echo "$sessions" | wc -l | tr -d ' ') workers"
}

cmd_send() {
    local num="$1"
    shift
    local msg="$*"
    local name="${PREFIX}-${num}"

    if ! tmux has-session -t "$name" 2>/dev/null; then
        echo "[err] $name not found"
        return 1
    fi

    _send_text "$name" "$msg"
    echo "[sent] → $name"
}

cmd_capture() {
    local num="$1"
    local lines="${2:-30}"
    local name="${PREFIX}-${num}"

    if ! tmux has-session -t "$name" 2>/dev/null; then
        echo "[err] $name not found"
        return 1
    fi

    tmux capture-pane -t "$name" -p -S "-${lines}"
}

cmd_teardown() {
    local sessions
    sessions=$(tmux ls -F '#{session_name}' 2>/dev/null | grep "^${PREFIX}-" | sort || true)

    if [[ -z "$sessions" ]]; then
        echo "No workers to tear down."
        return
    fi

    # graceful exit
    for name in $sessions; do
        tmux send-keys -t "$name" "/exit" Enter 2>/dev/null || true
    done

    echo "Waiting 3s for graceful exit..."
    sleep 3

    # force kill
    local count=0
    for name in $sessions; do
        if tmux has-session -t "$name" 2>/dev/null; then
            tmux kill-session -t "$name" 2>/dev/null || true
        fi
        echo "  [killed] $name"
        count=$((count + 1))
    done

    echo "Teardown: ${count} workers terminated"
}

cmd_reset() {
    local num="$1"
    local name="${PREFIX}-${num}"

    echo "Resetting $name..."

    if tmux has-session -t "$name" 2>/dev/null; then
        tmux send-keys -t "$name" "/exit" Enter 2>/dev/null || true
        sleep 2
        if tmux has-session -t "$name" 2>/dev/null; then
            tmux kill-session -t "$name" 2>/dev/null || true
        fi
    fi

    tmux new-session -d -s "$name" -c "$PROJECT_DIR"
    sleep 0.5
    tmux send-keys -t "$name" "$(_build_worker_cmd)" Enter
    echo "  [ok] $name restarted"
}

# ── Main ─────────────────────────────────────────────────────

case "${1:-help}" in
    init)      cmd_init "${2:-3}" ;;
    status)    cmd_status ;;
    send)
        if [[ -z "${2:-}" || -z "${3:-}" ]]; then
            echo "Usage: pool.sh send <N> <message>"
            exit 1
        fi
        cmd_send "$2" "${@:3}" ;;
    capture)
        if [[ -z "${2:-}" ]]; then
            echo "Usage: pool.sh capture <N> [lines]"
            exit 1
        fi
        cmd_capture "$2" "${3:-30}" ;;
    teardown)  cmd_teardown ;;
    reset)
        if [[ -z "${2:-}" ]]; then
            echo "Usage: pool.sh reset <N>"
            exit 1
        fi
        cmd_reset "$2" ;;
    *)
        echo "pool.sh — Worker Pool Management"
        echo ""
        echo "Commands:"
        echo "  init [size]        Create worker sessions (default: 3)"
        echo "  status             Show pool status"
        echo "  send <N> <msg>     Send message to worker N"
        echo "  capture <N> [lines] Capture worker N output"
        echo "  teardown           Kill all workers"
        echo "  reset <N>          Restart worker N"
        ;;
esac
