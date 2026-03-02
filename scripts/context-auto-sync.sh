#!/bin/bash
# H-1: context-auto-sync — PostToolUse(Write|Edit) hook
#
# 프로젝트 핵심 파일이 변경되면 context.md 갱신을 제안한다.
# Claude Code가 CLAUDE_FILE_PATH 환경변수로 변경된 파일 경로를 전달.
#
# 감지 패턴:
#   whos-life: features/*/service.py, features/*/manifest.json, config.yaml
#   memory-vault: 01-org/core/*/role.md, 06-skills/*.md, CLAUDE.md
#
# Exit 0: 정상 (block하지 않음)

set -euo pipefail

FILE_PATH="${CLAUDE_FILE_PATH:-}"
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# --- whos-life 프로젝트 감지 ---
if [[ "$FILE_PATH" == */dev/whos-life/* ]]; then
    CONTEXT_MD="$VAULT_DIR/03-projects/whos-life/context.md"

    # service.py 또는 manifest.json 변경 → feature 목록 갱신 필요
    if [[ "$FILE_PATH" == */features/*/service.py ]] || \
       [[ "$FILE_PATH" == */features/*/manifest.json ]] || \
       [[ "$FILE_PATH" == */config.yaml ]]; then

        # sync_context.py가 있으면 자동 실행
        SYNC_SCRIPT="$(dirname "$FILE_PATH")"
        while [[ "$SYNC_SCRIPT" != "/" ]]; do
            if [[ -f "$SYNC_SCRIPT/scripts/sync_context.py" ]]; then
                python3 "$SYNC_SCRIPT/scripts/sync_context.py" --dry-run 2>/dev/null || true
                echo "[H-1] whos-life context.md 갱신 제안: $FILE_PATH 변경됨. 'python3 scripts/sync_context.py' 실행 권장."
                exit 0
            fi
            SYNC_SCRIPT="$(dirname "$SYNC_SCRIPT")"
        done

        echo "[H-1] whos-life context.md 갱신 제안: $FILE_PATH 변경됨."
    fi
fi

# --- memory-vault 프로젝트 감지 ---
if [[ "$FILE_PATH" == "$VAULT_DIR"/* ]]; then
    CONTEXT_MD="$VAULT_DIR/03-projects/memory-vault/context.md"

    # 코어팀 역할 변경
    if [[ "$FILE_PATH" == */01-org/core/*/role.md ]]; then
        echo "[H-1] memory-vault context.md 갱신 제안: 코어팀 역할 정의 변경됨 ($FILE_PATH)."
    fi

    # 스킬 변경
    if [[ "$FILE_PATH" == */06-skills/*.md ]]; then
        echo "[H-1] memory-vault context.md 갱신 제안: 스킬 파일 변경됨 ($FILE_PATH)."
    fi

    # CLAUDE.md 변경
    if [[ "$FILE_PATH" == */CLAUDE.md ]]; then
        echo "[H-1] memory-vault context.md 갱신 제안: CLAUDE.md 변경됨."
    fi

    # 인프라 문서 변경
    if [[ "$FILE_PATH" == */02-knowledge/infrastructure/*.md ]]; then
        echo "[H-1] memory-vault context.md 갱신 제안: 인프라 문서 변경됨 ($FILE_PATH)."
    fi
fi

exit 0
