#!/bin/bash
# pool.sh — Worker Pool Management
#
# 워커 tmux 세션을 관리한다. 오케스트레이터(claude 세션)가 이 스크립트를 호출.
# tmux 자체가 상태 저장소 (별도 DB 불필요).
#
# Usage:
#   pool.sh init [size] [--role NAME] [--dir PATH]
#                              워커 세션 생성 (default: 3, role: coder)
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
    local role_name="${1:-coder}"

    case "$role_name" in
        planner)
            echo "${VAULT_DIR}/01-org/core/planner/role.md"
            ;;
        researcher)
            echo "${VAULT_DIR}/01-org/core/researcher/role.md"
            ;;
        reviewer)
            echo "${VAULT_DIR}/01-org/core/reviewer/role.md"
            ;;
        qa)
            echo "${VAULT_DIR}/01-org/core/qa/role.md"
            ;;
        coder)
            echo "${VAULT_DIR}/01-org/core/coder/role.md"
            ;;
        web-searcher)
            echo "${VAULT_DIR}/01-org/core/web-searcher/role.md"
            ;;
        orchestrator)
            echo "${VAULT_DIR}/01-org/enabling/orchestrator/role.md"
            ;;
        learning-specialist)
            echo "${VAULT_DIR}/03-projects/learning/specialist.md"
            ;;
        worker)
            echo "[warn] 'worker' is deprecated. Use: planner, researcher, reviewer, qa, coder" >&2
            echo ""
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

# ── Remote Control Naming ────────────────────────────────────

_rename_worker() {
    local name="$1"
    # Claude Code 초기화 대기 후 /rename 전송
    sleep 15
    if tmux has-session -t "$name" 2>/dev/null; then
        tmux send-keys -t "$name" "/rename ${name}" Enter
    fi
}

_schedule_rename() {
    local size="$1"
    sleep 15
    for i in $(seq 1 "$size"); do
        local name="${PREFIX}-${i}"
        if tmux has-session -t "$name" 2>/dev/null; then
            tmux send-keys -t "$name" "/rename ${name}" Enter
            sleep 1
        fi
    done
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
    local role_name="${FLAG_ROLE:-coder}"
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

        tmux new-session -d -s "$name" -e "CC_SESSION=$name" -c "$project_dir"
        sleep 0.5
        tmux send-keys -t "$name" "$(_build_worker_cmd "$role_file")" Enter
        echo "  [ok] $name created (role: ${role_name})"
        created=$((created + 1))
    done

    # Remote Control 세션 이름 자동 설정 (백그라운드)
    if [[ $created -gt 0 ]]; then
        _schedule_rename "$size" &
    fi

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

    # Check for --direct flag
    local direct=false
    local msg_args=()
    for arg in "$@"; do
        if [[ "$arg" == "--direct" ]]; then
            direct=true
        else
            msg_args+=("$arg")
        fi
    done
    local msg="${msg_args[*]}"
    local name="${PREFIX}-${num}"

    if ! tmux has-session -t "$name" 2>/dev/null; then
        echo "[err] $name not found"
        return 1
    fi

    if [[ "$direct" == true ]]; then
        # Direct tmux injection (no DB record)
        _send_text "$name" "$msg"
        echo "[sent:direct] → $name"
    else
        # MsgBus: record in DB + direct tmux delivery + mark processed
        local msg_id
        msg_id=$(python3 "${VAULT_DIR}/scripts/msgbus.py" send \
            --from cc-orchestration \
            --to "$name" \
            --type task \
            --payload "$msg" 2>/dev/null)

        if [[ -n "$msg_id" && "$msg_id" =~ ^[0-9]+$ ]]; then
            _send_text "$name" "$msg"
            # Mark as processed (delivered directly)
            python3 "${VAULT_DIR}/scripts/msgbus.py" ack "$msg_id" 2>/dev/null || true
            echo "[sent] → $name (msgbus #${msg_id})"
        else
            # Fallback: msgbus failed, send directly
            echo "[warn] msgbus unavailable, falling back to direct send" >&2
            _send_text "$name" "$msg"
            echo "[sent:direct] → $name"
        fi
    fi
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
    local role_name="${FLAG_ROLE:-coder}"
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

    tmux new-session -d -s "$name" -e "CC_SESSION=$name" -c "$project_dir"
    sleep 0.5
    tmux send-keys -t "$name" "$(_build_worker_cmd "$role_file")" Enter

    # Remote Control 세션 이름 자동 설정 (백그라운드)
    _rename_worker "$name" &

    echo "  [ok] $name restarted (role: ${role_name})"
}

cmd_watch() {
    echo "[deprecated] watch is no longer needed. Messages are delivered via Stop hook (inbox-deliver.py)."
    echo "Use 'python3 scripts/msgbus.py status' to check message bus state."
}

cmd_watch_once() {
    python3 "${VAULT_DIR}/scripts/msgbus.py" status
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
    watch)
        cmd_watch "${2:-120}" ;;
    watch-once)
        cmd_watch_once ;;
    *)
        echo "pool.sh — Worker Pool Management"
        echo ""
        echo "Commands:"
        echo "  init [size] [--role NAME] [--dir PATH]"
        echo "                        Create worker sessions (default: 3, role: coder)"
        echo "  status                Show pool status"
        echo "  send <N> <msg>        Send via msgbus + tmux delivery"
        echo "  send <N> --direct <msg> Send directly via tmux (no DB record)"
        echo "  capture <N> [lines]   Capture worker N output"
        echo "  teardown              Kill all workers"
        echo "  reset <N> [--role NAME]  Restart worker N (optionally change role)"
        echo "  watch-once            Show msgbus status"
        echo ""
        echo "Roles: planner, researcher, reviewer, qa, coder (default), web-searcher, orchestrator, learning-specialist"
        echo "       or absolute path to role file"
        echo ""
        echo "Examples:"
        echo "  pool.sh init 3                          # 3 coders (default)"
        echo "  pool.sh init 2 --role planner            # 2 planners"
        echo "  pool.sh init 1 --role coder --dir ~/dev/myproject"
        echo "  pool.sh reset 2 --role researcher        # restart as researcher"
        ;;
esac
