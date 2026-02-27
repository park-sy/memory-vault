#!/bin/bash
# pool.sh — Worker Pool Management
#
# 워커 tmux 세션을 관리한다. 오케스트레이터(claude 세션)가 이 스크립트를 호출.
# tmux 자체가 상태 저장소 (별도 DB 불필요).
#
# Usage:
#   pool.sh init [size] [--role NAME] [--dir PATH]
#                              워커 세션 생성 (default: 3, role: worker)
#   pool.sh status             전체 상태 출력
#   pool.sh send <N> <msg>     워커 N에 메시지 전송
#   pool.sh capture <N> [lines] 워커 N의 최근 출력 캡처
#   pool.sh teardown           전체 종료
#   pool.sh reset <N> [--role NAME]  워커 N 재시작 (선택: 역할 변경)

set -euo pipefail

VAULT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="cc-pool"
DEFAULT_PROJECT_DIR="${HOME}/dev"

# ── Role Resolution ────────────────────────────────────────

_resolve_role() {
    local role_name="${1:-worker}"

    case "$role_name" in
        worker)
            echo "${VAULT_DIR}/01-org/engineering/worker.md"
            ;;
        planner)
            echo "${VAULT_DIR}/01-org/product/planner.md"
            ;;
        orchestrator)
            echo "${VAULT_DIR}/01-org/ops/orchestrator.md"
            ;;
        /*)
            # 절대 경로 직접 지정
            echo "$role_name"
            ;;
        *)
            # 상대 경로 또는 vault 내 경로 시도
            if [[ -f "${VAULT_DIR}/${role_name}" ]]; then
                echo "${VAULT_DIR}/${role_name}"
            elif [[ -f "$role_name" ]]; then
                echo "$role_name"
            else
                echo "[err] Unknown role: $role_name" >&2
                return 1
            fi
            ;;
    esac
}

# ── Helpers ──────────────────────────────────────────────────

_build_worker_cmd() {
    local role_file="$1"
    local cmd="env -u CLAUDECODE claude --dangerously-skip-permissions"
    if [[ -f "$role_file" ]]; then
        cmd="${cmd} --append-system-prompt \"\$(cat '${role_file}')\""
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

# ── Flag Parsing ─────────────────────────────────────────────

_parse_flags() {
    # Sets: FLAG_ROLE, FLAG_DIR
    FLAG_ROLE=""
    FLAG_DIR=""
    local args=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --role)
                FLAG_ROLE="$2"
                shift 2
                ;;
            --dir)
                FLAG_DIR="$2"
                shift 2
                ;;
            *)
                args+=("$1")
                shift
                ;;
        esac
    done

    # 남은 positional args를 REMAINING_ARGS에 저장
    REMAINING_ARGS=("${args[@]+"${args[@]}"}")
}

# ── Commands ─────────────────────────────────────────────────

cmd_init() {
    _parse_flags "$@"
    local size="${REMAINING_ARGS[0]:-3}"
    local role_name="${FLAG_ROLE:-worker}"
    local project_dir="${FLAG_DIR:-$DEFAULT_PROJECT_DIR}"

    local role_file
    role_file=$(_resolve_role "$role_name") || exit 1

    echo "Initializing ${size} workers (role: ${role_name}, dir: ${project_dir})..."
    local created=0

    for i in $(seq 1 "$size"); do
        local name="${PREFIX}-${i}"
        if tmux has-session -t "$name" 2>/dev/null; then
            echo "  [skip] $name already exists"
            continue
        fi

        tmux new-session -d -s "$name" -c "$project_dir"
        sleep 0.5
        tmux send-keys -t "$name" "$(_build_worker_cmd "$role_file")" Enter
        echo "  [ok] $name created (role: ${role_name})"
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
    _parse_flags "$@"
    local num="${REMAINING_ARGS[0]}"
    local name="${PREFIX}-${num}"

    # role 지정 없으면 기존 worker 기본값
    local role_name="${FLAG_ROLE:-worker}"
    local project_dir="${FLAG_DIR:-$DEFAULT_PROJECT_DIR}"

    local role_file
    role_file=$(_resolve_role "$role_name") || exit 1

    echo "Resetting $name (role: ${role_name})..."

    if tmux has-session -t "$name" 2>/dev/null; then
        tmux send-keys -t "$name" "/exit" Enter 2>/dev/null || true
        sleep 2
        if tmux has-session -t "$name" 2>/dev/null; then
            tmux kill-session -t "$name" 2>/dev/null || true
        fi
    fi

    tmux new-session -d -s "$name" -c "$project_dir"
    sleep 0.5
    tmux send-keys -t "$name" "$(_build_worker_cmd "$role_file")" Enter
    echo "  [ok] $name restarted (role: ${role_name})"
}

# ── Main ─────────────────────────────────────────────────────

case "${1:-help}" in
    init)
        shift
        cmd_init "$@" ;;
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
            echo "Usage: pool.sh reset <N> [--role NAME]"
            exit 1
        fi
        shift
        cmd_reset "$@" ;;
    *)
        echo "pool.sh — Worker Pool Management"
        echo ""
        echo "Commands:"
        echo "  init [size] [--role NAME] [--dir PATH]"
        echo "                        Create worker sessions (default: 3, role: worker)"
        echo "  status                Show pool status"
        echo "  send <N> <msg>        Send message to worker N"
        echo "  capture <N> [lines]   Capture worker N output"
        echo "  teardown              Kill all workers"
        echo "  reset <N> [--role NAME]  Restart worker N (optionally change role)"
        echo ""
        echo "Roles: worker (default), planner, orchestrator, or absolute path"
        echo ""
        echo "Examples:"
        echo "  pool.sh init 3                          # 3 workers (default)"
        echo "  pool.sh init 2 --role planner            # 2 planners"
        echo "  pool.sh init 1 --role worker --dir ~/dev/myproject"
        echo "  pool.sh reset 2 --role planner           # restart as planner"
        ;;
esac
