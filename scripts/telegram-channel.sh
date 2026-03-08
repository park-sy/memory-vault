#!/bin/bash
# telegram-channel.sh — Telegram 채널(토픽) 통합 관리
#
# 기존 포럼 그룹에 토픽을 추가/조회/테스트하는 통합 CLI.
#
# Usage:
#   bash scripts/telegram-channel.sh add <name>        # 토픽 생성 + .env 등록 + bridge 재시작
#   bash scripts/telegram-channel.sh list               # 등록된 토픽 목록
#   bash scripts/telegram-channel.sh test <name>        # 토픽에 테스트 메시지 전송
#   bash scripts/telegram-channel.sh send <name> <msg>  # 토픽에 메시지 전송
#
# Examples:
#   bash scripts/telegram-channel.sh add boss
#   bash scripts/telegram-channel.sh add learning
#   bash scripts/telegram-channel.sh list
#   bash scripts/telegram-channel.sh test boss
#   bash scripts/telegram-channel.sh send boss "Hello from CLI"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${VAULT_DIR}/.env"

# ── Colors ──────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
err()   { echo -e "${RED}[err]${NC} $*" >&2; }

# ── Helpers ─────────────────────────────────────────────────────

_env_key() { echo "TELEGRAM_TOPIC_$(echo "$1" | tr '[:lower:]' '[:upper:]')"; }

_load_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        err ".env file not found: $ENV_FILE"
        exit 1
    fi
}

_get_topic_id() {
    local name="$1"
    local key
    key=$(_env_key "$name")
    grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2
}

# ── Commands ────────────────────────────────────────────────────

cmd_add() {
    local name="${1:-}"
    if [[ -z "$name" ]]; then
        err "Usage: telegram-channel.sh add <name>"
        exit 1
    fi

    _load_env
    local env_key
    env_key=$(_env_key "$name")

    # 중복 확인
    local existing
    existing=$(_get_topic_id "$name")
    if [[ -n "$existing" ]]; then
        ok "${env_key}=${existing} (already exists)"
        return 0
    fi

    # 토픽 생성
    info "Creating topic '${name}'..."
    local result
    result=$(python3 "${SCRIPT_DIR}/telegram_api.py" create-topic "$name" 2>/dev/null)
    local topic_id
    topic_id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['topic_id'])" 2>/dev/null)

    if [[ -z "$topic_id" || "$topic_id" == "None" ]]; then
        err "Failed to create topic. Response: ${result}"
        exit 1
    fi

    ok "Topic created: id=${topic_id}"

    # .env 등록
    echo "${env_key}=${topic_id}" >> "$ENV_FILE"
    ok "Added to .env: ${env_key}=${topic_id}"

    # bridge 재시작
    info "Restarting bridge..."
    bash "${SCRIPT_DIR}/daemon.sh" restart bridge 2>/dev/null || warn "Bridge restart failed"
    sleep 2

    # 테스트 메시지
    info "Sending test message..."
    python3 "${SCRIPT_DIR}/notify.py" "Channel '${name}' ready" --channel "$name" --sender "setup" 2>/dev/null \
        && ok "Test message sent" \
        || warn "Test message failed"

    echo
    ok "Channel '${name}' (topic_id=${topic_id}) ready!"
}

cmd_list() {
    _load_env
    echo -e "${BOLD}Registered Telegram Topics${NC}"
    echo "──────────────────────────────────"

    local found=0
    while IFS='=' read -r key value; do
        if [[ "$key" == TELEGRAM_TOPIC_* ]]; then
            local name="${key#TELEGRAM_TOPIC_}"
            name=$(echo "$name" | tr '[:upper:]' '[:lower:]')
            printf "  %-15s id=%s\n" "$name" "$value"
            found=1
        fi
    done < "$ENV_FILE"

    if [[ "$found" -eq 0 ]]; then
        echo "  (none)"
    fi
    echo
}

cmd_test() {
    local name="${1:-}"
    if [[ -z "$name" ]]; then
        err "Usage: telegram-channel.sh test <name>"
        exit 1
    fi

    _load_env
    local topic_id
    topic_id=$(_get_topic_id "$name")
    if [[ -z "$topic_id" ]]; then
        err "Topic '${name}' not found in .env"
        info "Available topics:"
        cmd_list
        exit 1
    fi

    info "Sending test to '${name}' (topic_id=${topic_id})..."
    python3 "${SCRIPT_DIR}/notify.py" "Test message for '${name}'" --channel "$name" --sender "test" 2>/dev/null \
        && ok "Sent" \
        || err "Send failed"
}

cmd_send() {
    local name="${1:-}"
    local msg="${2:-}"
    if [[ -z "$name" || -z "$msg" ]]; then
        err "Usage: telegram-channel.sh send <name> <message>"
        exit 1
    fi

    _load_env
    local topic_id
    topic_id=$(_get_topic_id "$name")
    if [[ -z "$topic_id" ]]; then
        err "Topic '${name}' not found in .env"
        exit 1
    fi

    python3 "${SCRIPT_DIR}/notify.py" "$msg" --channel "$name" --sender "cli" 2>/dev/null \
        && ok "Sent to '${name}'" \
        || err "Send failed"
}

cmd_help() {
    echo -e "${BOLD}telegram-channel.sh${NC} — Telegram 채널(토픽) 관리"
    echo
    echo "Commands:"
    echo "  add  <name>          토픽 생성 + .env 등록 + bridge 재시작"
    echo "  list                 등록된 토픽 목록"
    echo "  test <name>          토픽에 테스트 메시지 전송"
    echo "  send <name> <msg>    토픽에 메시지 전송"
    echo
    echo "Examples:"
    echo "  bash scripts/telegram-channel.sh add boss"
    echo "  bash scripts/telegram-channel.sh list"
    echo "  bash scripts/telegram-channel.sh send boss '안녕!'"
}

# ── Main ────────────────────────────────────────────────────────

CMD="${1:-help}"
shift || true

case "$CMD" in
    add)   cmd_add "$@" ;;
    list)  cmd_list "$@" ;;
    test)  cmd_test "$@" ;;
    send)  cmd_send "$@" ;;
    help)  cmd_help ;;
    *)     err "Unknown command: $CMD"; cmd_help; exit 1 ;;
esac
