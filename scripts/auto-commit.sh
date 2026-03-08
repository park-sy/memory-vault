#!/bin/bash
# auto-commit.sh — memory-vault 자동 커밋 + 푸시
#
# storage/, .claude/ 등 런타임 파일 제외.
# 변경 없으면 커밋하지 않음.

set -euo pipefail

VAULT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$VAULT_DIR"

# 변경 확인 (untracked + modified, storage/ 제외)
changes=$(git status --porcelain | grep -v '^?? storage/' | grep -v '^?? \.claude/' || true)

if [[ -z "$changes" ]]; then
    echo "No changes to commit."
    exit 0
fi

# Stage all except storage/ and .claude/
git add --all
git reset -- storage/ .claude/ 2>/dev/null || true

# 다시 확인
staged=$(git diff --cached --name-only)
if [[ -z "$staged" ]]; then
    echo "No staged changes after filtering."
    exit 0
fi

file_count=$(echo "$staged" | wc -l | tr -d ' ')
timestamp=$(date '+%Y-%m-%d %H:%M')

git commit -m "chore: auto-commit ${timestamp} (${file_count} files)"
git push origin master 2>&1 || echo "[warn] push failed, will retry next cycle"

echo "Committed and pushed: ${file_count} files"
