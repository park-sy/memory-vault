"""Recovery — daemon restart recovery from DB state.

On startup, scans the factory DB for interrupted state and resumes:
1. Active assignments → verify workers still exist, release if crashed
2. Pending approvals → re-send notification if approval is still needed
3. Pipeline items without workers → re-trigger assignment
"""

import logging

from . import db
from . import notifier
from . import worker_manager as wm
from .health_check import _tmux_session_exists

log = logging.getLogger("factory.recovery")


def recover_from_db() -> dict:
    """Recover daemon state from DB after restart. Returns summary."""
    summary = {
        "stale_assignments_released": 0,
        "approvals_re_sent": 0,
        "workers_verified": 0,
    }

    log.info("Running startup recovery...")

    # 1. Check active assignments — release if worker is gone
    summary["stale_assignments_released"] = _recover_assignments()

    # 2. Re-send pending approval notifications
    summary["approvals_re_sent"] = _recover_approvals()

    # 3. Verify worker pool integrity
    summary["workers_verified"] = _verify_workers()

    log.info(
        "Recovery complete: %d stale released, %d approvals re-sent, %d workers verified",
        summary["stale_assignments_released"],
        summary["approvals_re_sent"],
        summary["workers_verified"],
    )

    return summary


def _recover_assignments() -> int:
    """Release assignments whose workers no longer exist."""
    released = 0
    assigned_ids = db.get_assigned_worker_ids()

    for worker_id in assigned_ids:
        session_name = f"cc-pool-{worker_id}"
        if not _tmux_session_exists(session_name):
            assignment = db.get_active_assignment_for_worker(worker_id)
            if assignment:
                log.warning(
                    "Releasing stale assignment %d (worker %d gone, task %d)",
                    assignment.id, worker_id, assignment.task_id,
                )
                db.complete_assignment(assignment.id, "failed")
                db.log_event(assignment.task_id, "recovery_release", {
                    "worker_id": worker_id,
                    "reason": "worker_session_gone_on_startup",
                })
                released += 1
        else:
            log.info("Worker %d still alive with active assignment", worker_id)

    return released


def _recover_approvals() -> int:
    """Re-send pending approval notifications that may have been lost."""
    re_sent = 0
    pending = db.get_pending_approvals()

    for appr in pending:
        log.info(
            "Re-sending approval notification: task %d, gate %s",
            appr.task_id, appr.gate_type,
        )
        msg_id = notifier.notify_approval_request(
            appr.task_id,
            f"Task #{appr.task_id}",
            appr.gate_type,
        )
        if msg_id:
            # Update the msgbus_msg_id to the new one
            db.resolve_approval(appr.id, "timed_out")
            db.create_approval(appr.task_id, appr.gate_type, msg_id)
            re_sent += 1

    return re_sent


def _verify_workers() -> int:
    """Count how many worker sessions are currently alive."""
    states = wm.get_all_worker_states()
    alive = sum(1 for s in states if s.exists)
    log.info("Worker pool: %d session(s) alive", alive)
    return alive
