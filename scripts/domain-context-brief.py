#!/usr/bin/env python3
"""K-3: domain-context-brief — 도메인 컨텍스트 압축 요약 생성.

context.md를 읽어서 코어팀 주입용 최소 요약(brief)을 생성하거나 캐시에서 반환.
요약은 content hash 기반으로 캐시되며, context.md가 변경되면 자동 갱신.

사용법:
    # 특정 프로젝트 brief 생성/캐시 조회
    python3 scripts/domain-context-brief.py whos-life

    # 강제 갱신
    python3 scripts/domain-context-brief.py whos-life --refresh

    # 전체 프로젝트 brief 목록
    python3 scripts/domain-context-brief.py --list

    # brief 내용 출력 (코어팀 주입용)
    python3 scripts/domain-context-brief.py whos-life --output

출력:
    {project}/.context-brief.md — 캐시 파일 (gitignored)
"""

import argparse
import hashlib
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = VAULT_DIR / "03-projects"
BRIEF_FILENAME = ".context-brief.md"

# brief 생성 시 추출할 섹션 헤더 (우선순위 순)
PRIORITY_SECTIONS = [
    "프로젝트 요약",
    "스택",
    "아키텍처",
    "Key Paths",
    "기존 기능 목록",
    "주요 컨벤션",
]

# brief 최대 줄 수 (토큰 절약 목표: ~200 토큰)
MAX_LINES = 50


def _content_hash(content: str) -> str:
    """SHA-256 기반 content hash (첫 12자)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _read_brief_cache(project_dir: Path) -> tuple:
    """캐시된 brief 읽기. (hash, content) 반환. 없으면 (None, None)."""
    brief_path = project_dir / BRIEF_FILENAME
    if not brief_path.exists():
        return None, None

    content = brief_path.read_text(encoding="utf-8")
    # 첫 줄에서 hash 추출: <!-- hash:abcdef123456 -->
    first_line = content.split("\n", 1)[0]
    if first_line.startswith("<!-- hash:") and first_line.endswith(" -->"):
        cached_hash = first_line[10:-4]
        return cached_hash, content
    return None, content


def _extract_sections(content: str) -> dict:
    """마크다운 H2 섹션별로 내용 추출."""
    sections = {}
    current_section = None
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines)
            current_section = line[3:].strip()
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines)

    return sections


def _compress_table(table_text: str, max_rows: int = 10) -> str:
    """마크다운 테이블의 행 수를 제한."""
    lines = table_text.strip().split("\n")
    # 헤더(2줄) + 데이터
    if len(lines) <= max_rows + 2:
        return table_text

    header = lines[:2]
    data = lines[2:max_rows + 2]
    remaining = len(lines) - max_rows - 2
    return "\n".join(header + data + [f"... +{remaining}건 (전체: context.md 참조)"])


def generate_brief(project_name: str) -> str:
    """context.md에서 핵심 섹션만 추출하여 brief 생성."""
    project_dir = PROJECTS_DIR / project_name
    context_path = project_dir / "context.md"

    if not context_path.exists():
        return f"[K-3] context.md 없음: {project_name}"

    full_content = context_path.read_text(encoding="utf-8")

    # frontmatter 제거
    body = full_content
    if body.startswith("---\n"):
        try:
            end_idx = body.index("\n---", 3)
            body = body[end_idx + 4:].strip()
        except ValueError:
            pass

    # 제목 추출
    title = ""
    for line in body.split("\n"):
        if line.startswith("# "):
            title = line
            break

    # 섹션 추출
    sections = _extract_sections(body)

    # 우선순위 섹션만 brief에 포함
    brief_lines = [
        f"<!-- hash:{_content_hash(full_content)} -->",
        f"# {project_name} — Context Brief",
        "",
        "> 자동 생성 요약. 전체: `03-projects/{project_name}/context.md`",
        "",
    ]

    for section_name in PRIORITY_SECTIONS:
        if section_name in sections:
            section_content = sections[section_name].strip()
            # 테이블이 포함된 섹션은 행 수 제한
            if "|" in section_content:
                section_content = _compress_table(section_content)
            brief_lines.append(f"## {section_name}")
            brief_lines.append(section_content)
            brief_lines.append("")

    # 줄 수 제한
    result = "\n".join(brief_lines)
    lines = result.split("\n")
    if len(lines) > MAX_LINES:
        result = "\n".join(lines[:MAX_LINES]) + f"\n\n... (truncated, 전체: context.md)"

    return result


def get_brief(project_name: str, refresh: bool = False) -> str:
    """brief를 캐시에서 가져오거나 생성."""
    project_dir = PROJECTS_DIR / project_name
    context_path = project_dir / "context.md"

    if not context_path.exists():
        return f"[K-3] context.md 없음: {project_name}"

    full_content = context_path.read_text(encoding="utf-8")
    current_hash = _content_hash(full_content)

    if not refresh:
        cached_hash, cached_content = _read_brief_cache(project_dir)
        if cached_hash == current_hash and cached_content:
            return cached_content

    # 생성 + 캐시
    brief = generate_brief(project_name)
    brief_path = project_dir / BRIEF_FILENAME
    brief_path.write_text(brief, encoding="utf-8")

    return brief


def list_projects() -> list:
    """context.md가 있는 프로젝트 목록."""
    projects = []
    if not PROJECTS_DIR.exists():
        return projects

    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if proj_dir.is_dir() and (proj_dir / "context.md").exists():
            brief_path = proj_dir / BRIEF_FILENAME
            cached = brief_path.exists()
            projects.append({
                "name": proj_dir.name,
                "cached": cached,
                "context_lines": len((proj_dir / "context.md").read_text().split("\n")),
            })

    return projects


def main() -> None:
    parser = argparse.ArgumentParser(description="K-3: Domain Context Brief")
    parser.add_argument("project", nargs="?", help="프로젝트 이름 (03-projects/ 하위)")
    parser.add_argument("--refresh", action="store_true", help="캐시 무시, 강제 갱신")
    parser.add_argument("--output", action="store_true", help="brief 내용 stdout 출력")
    parser.add_argument("--list", action="store_true", help="전체 프로젝트 brief 상태")

    args = parser.parse_args()

    if args.list:
        projects = list_projects()
        if not projects:
            print("context.md가 있는 프로젝트가 없습니다.")
            return
        print(f"{'프로젝트':<20} {'캐시':>5} {'context.md 줄수':>15}")
        print("-" * 45)
        for p in projects:
            cached = "O" if p["cached"] else "-"
            print(f"{p['name']:<20} {cached:>5} {p['context_lines']:>15}")
        return

    if not args.project:
        parser.print_help()
        return

    brief = get_brief(args.project, refresh=args.refresh)

    if args.output:
        print(brief)
    else:
        # 상태 메시지만 출력
        project_dir = PROJECTS_DIR / args.project
        brief_path = project_dir / BRIEF_FILENAME
        context_path = project_dir / "context.md"

        if context_path.exists():
            ctx_lines = len(context_path.read_text().split("\n"))
            brief_lines = len(brief.split("\n"))
            ratio = round(brief_lines / ctx_lines * 100)
            print(f"[K-3] {args.project}: context.md {ctx_lines}줄 → brief {brief_lines}줄 ({ratio}%)")
            print(f"       캐시: {brief_path}")


if __name__ == "__main__":
    main()
