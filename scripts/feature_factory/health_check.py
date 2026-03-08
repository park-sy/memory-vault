"""Health Check — worker stall detection and assignment timeout handling.

Periodically checks:
1. Workers with active assignments that have gone silent (stall)
2. Assignments that exceeded max duration (timeout)
3. tmux sessions that crashed (worker disappeared)
"""

import logging
import subprocess
from datetime import datetime, timezone
from typing import List

from . import db
from . import notifier
from .config import STALL_TIMEOUT, DAEMON_ID, get_runtime_int

log = logging.getLogger("factory.health")

# 같은 assignment에 대한 반복 알림 억제 (assignment.id 기준)
_notified_stalls: set = set()


def _is_awaiting_input(worker_id: int) -> bool:
    """워커의 tmux pane에 사용자 입력 대기 패턴이 있는지 확인."""
    session_name = f"cc-pool-{worker_id}"
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        output = result.stdout
        input_patterns = [
            "Enter to select",
            "Type something",
            "Tab/Arrow keys",
        ]
        return any(p in output for p in input_patterns)
    except subprocess.SubprocessError:
        return False


def _tmux_session_exists(name: str) -> bool:
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except subprocess.SubprocessError:
        return False


def _parse_timestamp(ts: str) -> datetime:
    """Parse a DB timestamp string to datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def check_worker_health() -> dict:
    """Run all health checks. Returns summary dict."""
    results = {
        "crashed": _check_crashed_workers(),
        "stalled": _check_stalled_assignments(),
    }

    total_issues = results["crashed"] + results["stalled"]
    if total_issues > 0:
        log.warning("Health check: %d issue(s) found", total_issues)

    return results


def _check_crashed_workers() -> int:
    """Detect assignments to workers whose tmux sessions no longer exist."""
    assigned_ids = db.get_assigned_worker_ids()
    crashed = 0

    for worker_id in assigned_ids:
        session_name = f"cc-pool-{worker_id}"
        if not _tmux_session_exists(session_name):
            # Worker crashed — release assignment as failed
            assignment = db.get_active_assignment_for_worker(worker_id)
            if assignment:
                log.error(
                    "Worker %d crashed (session gone). Releasing assignment %d (task %d)",
                    worker_id, assignment.id, assignment.task_id,
                )
                db.complete_assignment(assignment.id, "failed")
                db.log_event(assignment.task_id, "worker_crashed", {
                    "worker_id": worker_id,
                    "assignment_id": assignment.id,
                    "stage": assignment.stage,
                })
                notifier.notify_error(
                    assignment.task_id,
                    f"Task #{assignment.task_id}",
                    f"워커 pool-{worker_id} 세션 종료됨. 재배정 필요.",
                )
                crashed += 1

    return crashed


def _check_stalled_assignments() -> int:
    """Detect assignments that exceeded stall timeout without completion."""
    stalled = 0
    now = datetime.now(timezone.utc)
    stall_timeout = get_runtime_int("stall_timeout", STALL_TIMEOUT)

    with db.connect() as conn:
        rows = conn.execute(
            """SELECT * FROM worker_assignments
               WHERE status = 'assigned'
               AND julianday('now') - julianday(assigned_at) > ? / 86400.0""",
            (stall_timeout,),
        ).fetchall()

        # 완료/해제된 assignment는 set에서 제거
        active_ids = {db._row_to_assignment(r).id for r in rows}
        _notified_stalls.difference_update(_notified_stalls - active_ids)

        for row in rows:
            assignment = db._row_to_assignment(row)
            elapsed_seconds = (now - _parse_timestamp(assignment.assigned_at)).total_seconds()
            elapsed_min = int(elapsed_seconds / 60)

            # 이미 처리한 assignment → Telegram 알림 절대 재발송 안 함
            if assignment.id in _notified_stalls:
                if _is_awaiting_input(assignment.worker_id):
                    log.info(
                        "Worker %d still awaiting user input (assignment %d, %d min)",
                        assignment.worker_id, assignment.id, elapsed_min,
                    )
                else:
                    log.warning(
                        "Stalled assignment %d (suppressed): worker %d, task %d, %d min",
                        assignment.id, assignment.worker_id, assignment.task_id, elapsed_min,
                    )
                    stalled += 1
                continue

            # 첫 감지 — 무조건 set에 등록 (입력 대기든 stall이든)
            _notified_stalls.add(assignment.id)

            if _is_awaiting_input(assignment.worker_id):
                log.info(
                    "Worker %d awaiting user input (assignment %d, task %d, %d min)",
                    assignment.worker_id, assignment.id, assignment.task_id, elapsed_min,
                )
                continue

            # 진짜 stall — 최초 1회만 Telegram 알림
            log.warning(
                "Stalled assignment %d: worker %d, task %d, %d min elapsed",
                assignment.id, assignment.worker_id, assignment.task_id, elapsed_min,
            )
            notifier.notify_error(
                assignment.task_id,
                f"Task #{assignment.task_id}",
                f"워커 pool-{assignment.worker_id} 응답 없음 ({elapsed_min}분). "
                f"Stage: {assignment.stage}",
            )
            stalled += 1

    return stalled
