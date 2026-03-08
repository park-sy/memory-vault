"""Completion Detector — tmux scrollback 스캔으로 워커 완료 자동 감지.

Stop hook의 안전망. housekeep tick(60초)마다 실행되어,
활성 assignment의 워커가 idle 상태면 stage_complete를 발동.
"""

import logging
import subprocess
import time
from datetime import datetime, timezone

from . import db
from . import dispatcher

log = logging.getLogger("factory.completion")

# 감지 완료된 assignment ID — 중복 감지 방지
_detected: set = set()

# idle 판정 전 최소 경과 시간 (초)
MIN_ELAPSED_SECONDS = 120

# Claude Code 입력 대기 패턴 — 이 상태면 작업이 아직 진행 중
_SKIP_PATTERNS = [
    "Enter to select",    # AskUserQuestion 선택지
    "Type something",     # 자유 입력
    "Tab/Arrow keys",     # 네비게이션
    "Plan mode",          # plan 작성 중
    "Waiting for",        # plan 승인 대기
]


def check_completions() -> int:
    """활성 assignment를 스캔하여 완료된 워커를 감지. Returns 감지 수."""
    detected_count = 0
    now = datetime.now(timezone.utc)

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM worker_assignments WHERE status = 'assigned'"
        ).fetchall()

    active_ids = set()
    for row in rows:
        assignment = db._row_to_assignment(row)
        active_ids.add(assignment.id)

        if assignment.id in _detected:
            continue

        # 최소 경과 시간 확인
        elapsed = (now - _parse_timestamp(assignment.assigned_at)).total_seconds()
        if elapsed < MIN_ELAPSED_SECONDS:
            continue

        # tmux scrollback 스캔
        session_name = f"cc-pool-{assignment.worker_id}"
        output = _capture_tmux(session_name)
        if not output:
            continue

        # skip 패턴 확인
        if any(p in output for p in _SKIP_PATTERNS):
            continue

        # idle 프롬프트 확인 (Claude Code가 입력 대기 중)
        if not _is_idle(output):
            continue

        # 완료 감지 — dispatcher로 직접 전달
        _detected.add(assignment.id)
        log.info(
            "Completion detected: assignment=%d, worker=%d, task=%d, stage=%s, elapsed=%ds",
            assignment.id, assignment.worker_id, assignment.task_id,
            assignment.stage, int(elapsed),
        )
        dispatcher._handle_stage_complete(
            assignment.task_id, assignment.stage, "completion_detector",
        )
        detected_count += 1

    # 완료된 assignment는 set에서 정리
    _detected.intersection_update(active_ids)

    return detected_count


def _capture_tmux(session: str):
    """tmux scrollback 캡처 (마지막 100줄). Returns stdout or None."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p", "-S", "-100"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _is_idle(output: str) -> bool:
    """출력 하단에 idle 프롬프트(❯)가 있는지 확인.

    Claude Code tmux UI 구조:
      ... 출력 ...
      ─── 구분선 ───
      ❯                      ← idle 프롬프트 (여기를 감지)
      ─── 구분선 ───
      ⏵⏵ bypass permissions  ← statusbar (마지막 줄)
    """
    lines = output.rstrip().split("\n")
    # 하단 5줄 안에 ❯가 있으면 idle (statusbar, 구분선 감안)
    tail = lines[-5:] if len(lines) >= 5 else lines
    return any("❯" in line for line in tail)


def _parse_timestamp(ts: str) -> datetime:
    """DB timestamp 문자열 → datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)
