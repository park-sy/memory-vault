#!/usr/bin/env python3
"""S-2: memory-archiver — cold memory 식별 + 아카이브 제안/실행.

frontmatter의 importance, access_count, last_accessed를 기반으로
cold memory를 식별하고 아카이브를 제안하거나 실행한다.

사용법:
    python3 scripts/memory-archiver.py suggest           # 아카이브 후보 목록 (JSON)
    python3 scripts/memory-archiver.py suggest --human    # 사람 읽기용 출력
    python3 scripts/memory-archiver.py archive            # 실제 이동 (--dry-run 가능)
    python3 scripts/memory-archiver.py archive --dry-run  # 이동하지 않고 미리보기
    python3 scripts/memory-archiver.py report             # 전체 메모리 건강도 리포트
    python3 scripts/memory-archiver.py report --notify    # 리포트를 Telegram으로 전송

임계값 기본값:
    --max-importance 3    # importance 이하
    --max-access 2        # access_count 이하
    --min-cold-days 60    # last_accessed 이후 경과 일수 이상

세 조건이 모두 충족되면 아카이브 후보.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from access_tracker import get_all_access_info, get_role_baselines

VAULT_DIR = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = VAULT_DIR / "archive"

# 스캔 대상 디렉토리 (vault root 기준)
SCAN_DIRS = [
    "01-org/core",
    "02-knowledge",
    "03-projects",
    "04-decisions",
    "05-sessions",
    "06-skills",
    "07-clone",
]

# 스캔 제외 패턴
EXCLUDE_NAMES = {"CLAUDE.md", "_team.md", "_distill-queue.md"}


@dataclass(frozen=True)
class MemoryFile:
    path: str                       # vault root 기준 상대 경로
    importance: int
    total_count: int                # 역할 합산 총 읽기
    max_reference_rate: float       # 역할별 최대 비율
    role_counts: dict               # {"coder": 10, "planner": 5}
    last_accessed: Optional[str]    # ISO date string or None
    cold_days: int                  # last_accessed 이후 경과 일수
    tags: List[str]


def _parse_frontmatter(file_path: Path) -> Optional[dict]:
    """YAML frontmatter를 딕셔너리로 파싱. frontmatter 없으면 None."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    if not content.startswith("---\n"):
        return None

    try:
        end_idx = content.index("\n---", 3)
    except ValueError:
        return None

    fm_text = content[4:end_idx]
    result = {}

    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r'^(\w[\w_-]*):\s*(.+)$', line)
        if match:
            key = match.group(1)
            val = match.group(2).strip().strip('"').strip("'")
            result[key] = val

    return result


def _days_since(date_str: str) -> int:
    """ISO date 문자열로부터 경과 일수 계산."""
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (date.today() - target).days
    except (ValueError, TypeError):
        return 9999  # 파싱 실패 시 매우 오래된 것으로 간주


def _parse_tags(raw: str) -> List[str]:
    """frontmatter tags 파싱. [a, b, c] 또는 a, b, c 형식."""
    raw = raw.strip("[]")
    return [t.strip() for t in raw.split(",") if t.strip()]


def _calc_max_rate(role_counts: dict, baselines: dict) -> float:
    """역할별 최대 reference_rate 계산."""
    max_rate = 0.0
    for role, count in role_counts.items():
        baseline = baselines.get(role, 1)
        max_rate = max(max_rate, count / max(baseline, 1))
    return max_rate


def scan_vault(db_path=None) -> List[MemoryFile]:
    """vault 내 모든 추적 대상 .md 파일을 스캔하여 MemoryFile 리스트 반환."""
    access_info = get_all_access_info(db_path)
    baselines = get_role_baselines(db_path)
    files = []

    for scan_dir in SCAN_DIRS:
        dir_path = VAULT_DIR / scan_dir
        if not dir_path.exists():
            continue

        for md_file in dir_path.rglob("*.md"):
            if md_file.name in EXCLUDE_NAMES:
                continue

            fm = _parse_frontmatter(md_file)
            if fm is None:
                continue

            rel_path = str(md_file.relative_to(VAULT_DIR))
            importance = int(fm.get("importance", "5"))

            # total_count, last_accessed, role_counts는 DB에서 조회
            info = access_info.get(rel_path, {})
            total_count = info.get("total_count", 0)
            role_counts = info.get("role_counts", {})
            last_accessed = info.get("last_accessed")

            max_rate = _calc_max_rate(role_counts, baselines)
            cold_days = _days_since(last_accessed) if last_accessed else 9999
            tags = _parse_tags(fm.get("tags", ""))

            files.append(MemoryFile(
                path=rel_path,
                importance=importance,
                total_count=total_count,
                max_reference_rate=max_rate,
                role_counts=role_counts,
                last_accessed=last_accessed,
                cold_days=cold_days,
                tags=tags,
            ))

    return files


def find_archive_candidates(
    files: List[MemoryFile],
    max_importance: int = 3,
    max_rate: float = 0.1,
    min_cold_days: int = 60,
) -> List[MemoryFile]:
    """아카이브 후보 필터링. 세 조건 모두 충족해야 함.

    Args:
        max_importance: importance 이하
        max_rate: max_reference_rate 이하 (비율 기준)
        min_cold_days: last_accessed 이후 경과 일수 이상
    """
    return [
        f for f in files
        if f.importance <= max_importance
        and f.max_reference_rate <= max_rate
        and f.cold_days >= min_cold_days
    ]


def generate_report(files: List[MemoryFile]) -> dict:
    """전체 메모리 건강도 리포트 생성."""
    today = date.today()
    hot = [f for f in files if f.cold_days <= 7]
    warm = [f for f in files if 7 < f.cold_days <= 30]
    cold = [f for f in files if f.cold_days > 30]

    high_importance = [f for f in files if f.importance >= 8]
    low_importance = [f for f in files if f.importance <= 3]

    return {
        "date": today.isoformat(),
        "total_files": len(files),
        "hot": len(hot),
        "warm": len(warm),
        "cold": len(cold),
        "high_importance_count": len(high_importance),
        "low_importance_count": len(low_importance),
        "avg_access_count": round(sum(f.total_count for f in files) / max(len(files), 1), 1),
        "cold_high_importance": [
            f.path for f in files
            if f.cold_days > 30 and f.importance >= 7
        ],
    }


def cmd_suggest(args: argparse.Namespace) -> None:
    """아카이브 후보 제안."""
    files = scan_vault()
    candidates = find_archive_candidates(
        files, args.max_importance, args.max_rate, args.min_cold_days,
    )

    if args.human:
        if not candidates:
            print("아카이브 후보가 없습니다.")
            return
        print(f"아카이브 후보: {len(candidates)}건\n")
        print(f"{'파일':<60} {'imp':>3} {'rate':>5} {'cold':>5}")
        print("-" * 75)
        for f in sorted(candidates, key=lambda x: x.cold_days, reverse=True):
            print(f"{f.path:<60} {f.importance:>3} {f.max_reference_rate:>5.0%} {f.cold_days:>5}d")
    else:
        # frozen dataclass의 dict 변환 시 role_counts 직렬화를 위해 수동 변환
        result = []
        for c in candidates:
            d = asdict(c)
            result.append(d)
        print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_archive(args: argparse.Namespace) -> None:
    """아카이브 실행 (또는 dry-run)."""
    files = scan_vault()
    candidates = find_archive_candidates(
        files, args.max_importance, args.max_rate, args.min_cold_days,
    )

    if not candidates:
        print("아카이브 후보가 없습니다.")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for f in candidates:
        src = VAULT_DIR / f.path
        dst = ARCHIVE_DIR / f.path
        dst.parent.mkdir(parents=True, exist_ok=True)

        if args.dry_run:
            print(f"[dry-run] {f.path} → archive/{f.path}")
        else:
            shutil.move(str(src), str(dst))
            print(f"[archived] {f.path} → archive/{f.path}")

    if not args.dry_run:
        print(f"\n{len(candidates)}건 아카이브 완료.")


def cmd_report(args: argparse.Namespace) -> None:
    """전체 메모리 건강도 리포트."""
    files = scan_vault()
    report = generate_report(files)
    candidates = find_archive_candidates(files, 3, 0.1, 60)
    report["archive_candidates"] = len(candidates)

    if args.human:
        print("=== Memory Health Report ===\n")
        print(f"총 파일: {report['total_files']}")
        print(f"Hot (7일 이내): {report['hot']}")
        print(f"Warm (7-30일): {report['warm']}")
        print(f"Cold (30일+): {report['cold']}")
        print(f"평균 접근 횟수: {report['avg_access_count']}")
        print(f"아카이브 후보: {report['archive_candidates']}건")
        if report["cold_high_importance"]:
            print(f"\n⚠ Cold + 높은 중요도 (재접근 필요):")
            for p in report["cold_high_importance"]:
                print(f"  - {p}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.notify:
        _send_telegram_report(report)


def _send_telegram_report(report: dict) -> None:
    """Telegram으로 리포트 전송."""
    msg_lines = [
        "📊 Memory Health Report",
        f"총 {report['total_files']}건: Hot {report['hot']} / Warm {report['warm']} / Cold {report['cold']}",
        f"아카이브 후보: {report['archive_candidates']}건",
    ]
    if report["cold_high_importance"]:
        msg_lines.append(f"⚠ Cold+High: {len(report['cold_high_importance'])}건 재접근 필요")

    notify_script = VAULT_DIR / "scripts" / "notify.py"
    if notify_script.exists():
        subprocess.run(
            [sys.executable, str(notify_script), "\n".join(msg_lines),
             "--channel", "report", "--sender", "memory-archiver"],
            capture_output=True,
            timeout=10,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="S-2: Memory Archiver")
    sub = parser.add_subparsers(dest="command", required=True)

    # suggest
    p_suggest = sub.add_parser("suggest", help="아카이브 후보 제안")
    p_suggest.add_argument("--human", action="store_true", help="사람 읽기용 출력")
    p_suggest.add_argument("--max-importance", type=int, default=3)
    p_suggest.add_argument("--max-rate", type=float, default=0.1, help="max reference_rate 이하")
    p_suggest.add_argument("--min-cold-days", type=int, default=60)

    # archive
    p_archive = sub.add_parser("archive", help="아카이브 실행")
    p_archive.add_argument("--dry-run", action="store_true", help="이동 없이 미리보기")
    p_archive.add_argument("--max-importance", type=int, default=3)
    p_archive.add_argument("--max-rate", type=float, default=0.1, help="max reference_rate 이하")
    p_archive.add_argument("--min-cold-days", type=int, default=60)

    # report
    p_report = sub.add_parser("report", help="메모리 건강도 리포트")
    p_report.add_argument("--human", action="store_true", help="사람 읽기용 출력")
    p_report.add_argument("--notify", action="store_true", help="Telegram으로 리포트 전송")

    args = parser.parse_args()

    if args.command == "suggest":
        cmd_suggest(args)
    elif args.command == "archive":
        cmd_archive(args)
    elif args.command == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
