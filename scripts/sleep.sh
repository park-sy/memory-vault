#!/usr/bin/env bash
# sleep.sh — Memory Vault 유지보수 스크립트
# LLM 호출 없이 순수 bash. 세션 종료 후 실행.
#
# Usage:
#   bash scripts/sleep.sh report     # 전체 리포트
#   bash scripts/sleep.sh archive    # archive 후보를 archive/로 이동
#   bash scripts/sleep.sh sync-moc   # MOC 링크 자동 추가

set -euo pipefail

VAULT_DIR="${VAULT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
TODAY=$(date +%Y-%m-%d)

# ─── Colors ───
RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Helpers ───

# frontmatter에서 필드 값 추출 (단순 YAML 파서)
get_field() {
    local file="$1" field="$2"
    local result
    result=$(sed -n '/^---$/,/^---$/p' "$file" 2>/dev/null \
        | grep "^${field}:" \
        | head -1 \
        | sed "s/^${field}:[[:space:]]*//" \
        | sed 's/^"\(.*\)"$/\1/') || true
    echo "$result"
}

# 날짜 차이 (일 단위)
days_since() {
    local date_str="$1"
    # 빈 문자열 또는 템플릿 변수({{...}}) 건너뛰기
    if [[ -z "$date_str" ]] || [[ "$date_str" == *"{{"* ]]; then
        echo "999"
        return
    fi
    # YYYY-MM-DD 형식 검증
    if ! [[ "$date_str" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo "999"
        return
    fi
    local then_epoch now_epoch
    if date --version &>/dev/null 2>&1; then
        # GNU date
        then_epoch=$(date -d "$date_str" +%s 2>/dev/null || echo 0)
        now_epoch=$(date +%s)
    else
        # macOS date
        then_epoch=$(date -j -f "%Y-%m-%d" "$date_str" +%s 2>/dev/null || echo 0)
        now_epoch=$(date +%s)
    fi
    if [[ "$then_epoch" -eq 0 ]]; then
        echo "999"
        return
    fi
    echo $(( (now_epoch - then_epoch) / 86400 ))
}

# vault 내 모든 md 파일 목록 (시스템/템플릿 디렉토리 제외)
list_vault_files() {
    find "$VAULT_DIR" -name "*.md" \
        -not -path "*/.obsidian/*" \
        -not -path "*/.git/*" \
        -not -path "*/archive/*" \
        -not -path "*/templates/*" \
        2>/dev/null || true
}

# ─── 1. 미증류 세션 리포트 ───
report_undistilled() {
    echo -e "${BOLD}${CYAN}=== 미증류 세션 ===${NC}"
    local count=0
    for f in "$VAULT_DIR"/05-sessions/20*.md; do
        [[ -f "$f" ]] || continue
        local distilled
        distilled=$(get_field "$f" "distilled")
        if [[ "$distilled" == "false" ]]; then
            local created days
            created=$(get_field "$f" "created")
            days=$(days_since "$created")
            echo -e "  ${YELLOW}$(basename "$f")${NC} — ${days}일 전 작성"
            count=$((count + 1))
        fi
    done
    if [[ $count -eq 0 ]]; then
        echo -e "  ${GREEN}모두 증류 완료!${NC}"
    else
        echo -e "  → ${count}개 세션 증류 필요"
    fi
    echo
}

# ─── 2. Archive 후보 탐지 ───
report_archive_candidates() {
    echo -e "${BOLD}${CYAN}=== Archive 후보 (importance <= 3, access_count <= 2, 60일+ 미접근) ===${NC}"
    local count=0
    local files
    files=$(list_vault_files)

    while IFS= read -r f; do
        [[ -n "$f" && -f "$f" ]] || continue
        local importance
        importance=$(get_field "$f" "importance")
        [[ -z "$importance" ]] && continue
        local access_count last_accessed
        access_count=$(get_field "$f" "access_count")
        last_accessed=$(get_field "$f" "last_accessed")

        if [[ "$importance" -le 3 ]] && [[ "${access_count:-0}" -le 2 ]]; then
            local days
            days=$(days_since "$last_accessed")
            if [[ "$days" -ge 60 ]]; then
                local rel_path="${f#"$VAULT_DIR"/}"
                echo -e "  ${YELLOW}${rel_path}${NC} — importance:${importance}, access:${access_count:-0}, ${days}일 미접근"
                count=$((count + 1))
            fi
        fi
    done <<< "$files"

    if [[ $count -eq 0 ]]; then
        echo -e "  ${GREEN}archive 후보 없음${NC}"
    else
        echo -e "  → ${count}개 파일 archive 후보"
    fi
    echo
}

# ─── 3. Cold 기억 경고 ───
report_cold_important() {
    echo -e "${BOLD}${CYAN}=== Cold 경고 (importance >= 7, 30일+ 미접근) ===${NC}"
    local count=0
    local files
    files=$(list_vault_files)

    while IFS= read -r f; do
        [[ -n "$f" && -f "$f" ]] || continue
        local importance
        importance=$(get_field "$f" "importance")
        [[ -z "$importance" ]] && continue
        local last_accessed
        last_accessed=$(get_field "$f" "last_accessed")

        if [[ "$importance" -ge 7 ]]; then
            local days
            days=$(days_since "$last_accessed")
            if [[ "$days" -ge 30 ]]; then
                local rel_path="${f#"$VAULT_DIR"/}"
                echo -e "  ${RED}${rel_path}${NC} — importance:${importance}, ${days}일 미접근"
                count=$((count + 1))
            fi
        fi
    done <<< "$files"

    if [[ $count -eq 0 ]]; then
        echo -e "  ${GREEN}중요 기억 모두 활성 상태${NC}"
    else
        echo -e "  → ${RED}${count}개 중요 기억이 잊혀지고 있음!${NC}"
    fi
    echo
}

# ─── 4. MOC 인덱스 동기화 ───
report_moc_sync() {
    echo -e "${BOLD}${CYAN}=== MOC 링크 동기화 ===${NC}"
    local moc_file="$VAULT_DIR/00-MOC/knowledge-map.md"
    if [[ ! -f "$moc_file" ]]; then
        echo -e "  ${YELLOW}knowledge-map.md 없음, 스킵${NC}"
        echo
        return
    fi

    local missing=()
    for f in "$VAULT_DIR"/02-knowledge/patterns/*.md "$VAULT_DIR"/02-knowledge/conventions/*.md "$VAULT_DIR"/04-decisions/*.md; do
        [[ -f "$f" ]] || continue
        local basename_no_ext
        basename_no_ext=$(basename "$f" .md)
        if ! grep -q "$basename_no_ext" "$moc_file" 2>/dev/null; then
            missing+=("$(echo "$f" | sed "s|$VAULT_DIR/||")")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        echo -e "  ${GREEN}모든 파일이 MOC에 링크됨${NC}"
    else
        echo -e "  ${YELLOW}MOC에 누락된 링크:${NC}"
        for m in "${missing[@]}"; do
            echo -e "    - ${m}"
        done
    fi
    echo
}

# ─── 5. 전체 통계 ───
report_stats() {
    echo -e "${BOLD}${CYAN}=== Vault 통계 ===${NC}"
    local total_md tracked_md
    total_md=$(find "$VAULT_DIR" -name "*.md" -not -path "*/.obsidian/*" -not -path "*/.git/*" 2>/dev/null | wc -l | tr -d ' ')
    tracked_md=$(grep -rl "^importance:" "$VAULT_DIR" --include="*.md" 2>/dev/null | grep -v .obsidian | grep -v '.git/' | wc -l | tr -d ' ')
    echo -e "  전체 .md 파일: ${total_md}"
    echo -e "  추적 중 (importance 있음): ${tracked_md}"
    echo -e "  미추적: $((total_md - tracked_md))"
    echo
}

# ─── Archive 실행 ───
do_archive() {
    echo -e "${BOLD}${CYAN}=== Archive 실행 ===${NC}"
    local archive_dir="$VAULT_DIR/archive"
    mkdir -p "$archive_dir"

    local count=0
    local files
    files=$(list_vault_files)

    while IFS= read -r f; do
        [[ -n "$f" && -f "$f" ]] || continue
        # 템플릿은 archive 안 함
        [[ "$f" == *"/templates/"* ]] && continue
        local importance
        importance=$(get_field "$f" "importance")
        [[ -z "$importance" ]] && continue
        local access_count last_accessed
        access_count=$(get_field "$f" "access_count")
        last_accessed=$(get_field "$f" "last_accessed")

        if [[ "$importance" -le 3 ]] && [[ "${access_count:-0}" -le 2 ]]; then
            local days
            days=$(days_since "$last_accessed")
            if [[ "$days" -ge 60 ]]; then
                local rel_path="${f#"$VAULT_DIR"/}"
                echo -e "  ${YELLOW}Moving: ${rel_path} → archive/${NC}"
                mv "$f" "$archive_dir/"
                count=$((count + 1))
            fi
        fi
    done <<< "$files"

    if [[ $count -eq 0 ]]; then
        echo -e "  ${GREEN}archive 대상 없음${NC}"
    else
        echo -e "  → ${count}개 파일 archive 완료"
    fi
    echo
}

# ─── MOC 동기화 실행 ───
do_sync_moc() {
    echo -e "${BOLD}${CYAN}=== MOC 링크 동기화 실행 ===${NC}"
    local moc_file="$VAULT_DIR/00-MOC/knowledge-map.md"
    if [[ ! -f "$moc_file" ]]; then
        echo -e "  ${RED}knowledge-map.md 없음${NC}"
        return
    fi

    local added=0
    for f in "$VAULT_DIR"/02-knowledge/patterns/*.md "$VAULT_DIR"/02-knowledge/conventions/*.md "$VAULT_DIR"/04-decisions/*.md; do
        [[ -f "$f" ]] || continue
        local rel_path basename_no_ext
        rel_path=$(echo "$f" | sed "s|$VAULT_DIR/||" | sed 's/\.md$//')
        basename_no_ext=$(basename "$f" .md)

        if ! grep -q "$basename_no_ext" "$moc_file" 2>/dev/null; then
            echo "- [[${rel_path}]]" >> "$moc_file"
            echo -e "  ${GREEN}Added: [[${rel_path}]]${NC}"
            added=$((added + 1))
        fi
    done

    if [[ $added -eq 0 ]]; then
        echo -e "  ${GREEN}모든 링크가 이미 존재${NC}"
    else
        echo -e "  → ${added}개 링크 추가됨"
    fi
    echo
}

# ─── Main ───
main() {
    local cmd="${1:-report}"

    echo -e "${BOLD}Memory Vault Maintenance — ${TODAY}${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo

    case "$cmd" in
        report)
            report_stats
            report_undistilled
            report_cold_important
            report_archive_candidates
            report_moc_sync
            ;;
        archive)
            do_archive
            ;;
        sync-moc)
            do_sync_moc
            ;;
        *)
            echo "Usage: bash scripts/sleep.sh {report|archive|sync-moc}"
            exit 1
            ;;
    esac
}

main "$@"
