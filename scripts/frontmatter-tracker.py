#!/usr/bin/env python3
"""PostToolUse hook — Read 도구 사용 시 memory-vault .md 파일의 frontmatter를 자동 갱신.

Claude Code가 stdin으로 전달하는 JSON:
{
  "tool_name": "Read",
  "tool_input": { "file_path": "/Users/.../02-knowledge/patterns/x.md" },
  "tool_response": "..."
}

갱신 대상:
- last_accessed → 오늘 날짜
- access_count += 1

대상 디렉토리:
- 01-org/core/*/memory.md
- 01-org/enabling/*/memory.md
- 02-knowledge/**/*.md
- 03-projects/**/*.md (overview, context, developer-memory)
- 04-decisions/**/*.md
- 05-sessions/**/*.md
- 06-skills/**/*.md
- 07-clone/**/*.md

제외:
- CLAUDE.md (진입점, frontmatter 없음)
- templates/ (템플릿은 추적 안 함)
- 00-MOC/ (MOC는 추적 안 함)
- role.md (역할 정의, frontmatter 없음)
- head.md, identity.md, user.md (SOUL 파일)

Exit 0: 정상 (block하지 않음)
"""

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

VAULT_DIR = Path(__file__).resolve().parent.parent

# 추적 대상 디렉토리 (vault root 기준 상대 경로)
TRACKED_PREFIXES = (
    "01-org/core/",
    "01-org/enabling/",
    "02-knowledge/",
    "03-projects/",
    "04-decisions/",
    "05-sessions/",
    "06-skills/",
    "07-clone/",
)

# 추적 제외 파일 패턴
EXCLUDED_NAMES = {
    "CLAUDE.md",
    "_team.md",
}

EXCLUDED_SUFFIXES = (
    "/role.md",
    "/head.md",
    "/identity.md",
    "/user.md",
    "/orchestrator.md",
    "/developer.md",
)


def _is_tracked(file_path: Path) -> bool:
    """추적 대상 파일인지 판별."""
    if not file_path.suffix == ".md":
        return False

    try:
        rel = file_path.relative_to(VAULT_DIR)
    except ValueError:
        return False

    rel_str = str(rel)

    # 제외 패턴 확인
    if file_path.name in EXCLUDED_NAMES:
        return False

    for suffix in EXCLUDED_SUFFIXES:
        if rel_str.endswith(suffix):
            return False

    # templates, 00-MOC 제외
    if rel_str.startswith("templates/") or rel_str.startswith("00-MOC/"):
        return False

    # 추적 대상 확인
    return any(rel_str.startswith(prefix) for prefix in TRACKED_PREFIXES)


def _has_frontmatter(content: str) -> bool:
    """YAML frontmatter가 있는지 확인."""
    return content.startswith("---\n")


def _update_frontmatter(content: str, today: str) -> Optional[str]:
    """frontmatter의 last_accessed와 access_count를 갱신. 변경 없으면 None."""
    if not _has_frontmatter(content):
        return None

    # frontmatter 범위 추출
    end_idx = content.index("\n---", 3)
    fm_block = content[4:end_idx]  # --- 이후부터 다음 --- 이전까지
    rest = content[end_idx:]

    changed = False

    # last_accessed 갱신
    if "last_accessed:" in fm_block:
        new_fm, count = re.subn(
            r'last_accessed:\s*"[^"]*"',
            f'last_accessed: "{today}"',
            fm_block,
        )
        if count > 0 and new_fm != fm_block:
            fm_block = new_fm
            changed = True
    else:
        # last_accessed 필드가 없으면 추가
        fm_block = fm_block.rstrip("\n") + f'\nlast_accessed: "{today}"\n'
        changed = True

    # access_count 갱신
    match = re.search(r"access_count:\s*(\d+)", fm_block)
    if match:
        old_count = int(match.group(1))
        new_count = old_count + 1
        new_fm = fm_block.replace(
            f"access_count: {old_count}",
            f"access_count: {new_count}",
            1,
        )
        if new_fm != fm_block:
            fm_block = new_fm
            changed = True
    else:
        # access_count 필드가 없으면 추가
        fm_block = fm_block.rstrip("\n") + "\naccess_count: 1\n"
        changed = True

    if not changed:
        return None

    return "---\n" + fm_block + rest


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        payload = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return

    # Read 도구인지 확인 (settings.json matcher로도 필터링되지만 이중 확인)
    tool_name = payload.get("tool_name", "")
    if tool_name != "Read":
        return

    file_path_str = payload.get("tool_input", {}).get("file_path", "")
    if not file_path_str:
        return

    file_path = Path(file_path_str).resolve()

    if not _is_tracked(file_path):
        return

    if not file_path.exists():
        return

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    today = date.today().isoformat()
    updated = _update_frontmatter(content, today)

    if updated is None:
        return

    try:
        file_path.write_text(updated, encoding="utf-8")
    except OSError:
        return


if __name__ == "__main__":
    main()
