"""Artifact Validator — 스테이지별 산출물 검증.

워커가 스테이지를 완료했다고 보고할 때,
실제로 의미 있는 산출물이 존재하는지 검증한다.
검증 실패 시 스테이지 전진을 차단하고 재할당을 유도.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from .config import WHOS_LIFE_DIR

log = logging.getLogger("factory.validator")


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    stage: str
    checks: Tuple[Tuple[str, bool, str], ...]  # (name, passed, detail)
    summary: str


def validate_stage_artifacts(
    task_id: int, stage: str, title: str,
) -> ValidationResult:
    """스테이지 산출물을 검증한다. designing/testing/coding만 검증, 나머지는 항상 valid."""
    if stage == "designing":
        return _validate_designing(task_id, title)
    elif stage == "testing":
        return _validate_testing(task_id, title)
    elif stage == "coding":
        return _validate_coding(task_id, title)
    return ValidationResult(valid=True, stage=stage, checks=(), summary="")


def _validate_designing(task_id: int, title: str) -> ValidationResult:
    """designing: SKILL.md 존재 확인."""
    slug = title_to_slug(title)
    skill_path = WHOS_LIFE_DIR / "skills" / slug / "SKILL.md"
    exists = skill_path.exists()

    checks = (
        ("SKILL.md 존재", exists, str(skill_path)),
    )
    summary = "" if exists else f"SKILL.md 미생성: {skill_path}"
    return ValidationResult(valid=exists, stage="designing", checks=checks, summary=summary)


def _validate_testing(task_id: int, title: str) -> ValidationResult:
    """testing: test_runs > 0 확인 (pipeline_manager 호출)."""
    from . import pipeline_manager as pm

    result = pm.get_task_detail(task_id)
    if not result.success:
        checks = (("task 조회", False, result.error or "조회 실패"),)
        return ValidationResult(
            valid=False, stage="testing", checks=checks,
            summary=f"Task #{task_id} 조회 실패",
        )

    test_runs = result.data.get("test_runs") or 0
    passed = test_runs > 0

    checks = (
        ("test_runs > 0", passed, f"test_runs={test_runs}"),
    )
    summary = "" if passed else f"테스트 실행 0회 (task #{task_id})"
    return ValidationResult(valid=passed, stage="testing", checks=checks, summary=summary)


def _validate_coding(task_id: int, title: str) -> ValidationResult:
    """coding: whos-life 디렉토리에 변경 파일이 있는지 확인."""
    changed_files = get_git_changed_files()
    passed = len(changed_files) > 0

    detail = ", ".join(changed_files[:5]) if changed_files else "변경 파일 없음"
    checks = (
        ("git diff 변경 파일 존재", passed, detail),
    )
    summary = "" if passed else "코드 변경 없음 (files_changed=0)"
    return ValidationResult(valid=passed, stage="coding", checks=checks, summary=summary)


def get_git_changed_files() -> list:
    """whos-life 디렉토리에서 변경 파일 목록 조회 (unstaged + staged + 최근 커밋)."""
    all_files: set = set()

    # unstaged changes
    all_files.update(_run_git_diff(["git", "diff", "--name-only"]))
    # staged changes
    all_files.update(_run_git_diff(["git", "diff", "--cached", "--name-only"]))
    # 최근 커밋 (워커가 이미 commit 했을 수 있음)
    all_files.update(_run_git_diff(["git", "diff", "--name-only", "HEAD~1", "HEAD"]))

    return sorted(all_files)


def _run_git_diff(cmd: list) -> list:
    """git diff 명령 실행 → 파일 이름 리스트 반환."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            cwd=str(WHOS_LIFE_DIR),
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def title_to_slug(title: str) -> str:
    """Feature title -> directory slug."""
    return title.lower().replace(" ", "-")
