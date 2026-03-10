"""Approval Handler — manages approval gates in the Feature Pipeline.

Handles approval requests, callback processing, and gate resolution.
"""

import logging
from typing import Optional

from . import db
from .config import APPROVAL_GATES, APPROVAL_TIMEOUT, get_runtime_int
from . import notifier
from . import pipeline_manager as pm

log = logging.getLogger("factory.approval")


def request_approval(
    task_id: int, title: str, gate_type: str,
    context: Optional[dict] = None,
) -> Optional[int]:
    """Send an approval request and track it.

    Args:
        context: task detail dict (description, priority, plan, test_runs 등).

    Returns the approval ID if successful, None otherwise.
    """
    if gate_type not in APPROVAL_GATES:
        log.error("Unknown gate type: %s", gate_type)
        return None

    # Check for existing pending approval for this task+gate
    existing = db.get_pending_approvals()
    for appr in existing:
        if appr.task_id == task_id and appr.gate_type == gate_type:
            log.info("Approval already pending for task %d gate %s", task_id, gate_type)
            return appr.id

    # Send Telegram notification
    msg_id = notifier.notify_approval_request(task_id, title, gate_type, context=context)
    if msg_id is None:
        log.error("Failed to send approval notification for task %d", task_id)
        return None

    # Record in factory DB
    approval_id = db.create_approval(task_id, gate_type, msg_id)
    db.log_event(task_id, "approval_req", {
        "gate_type": gate_type, "msgbus_msg_id": msg_id, "approval_id": approval_id,
    })

    log.info("Approval requested: task=%d, gate=%s, msg_id=%d", task_id, gate_type, msg_id)
    return approval_id


def handle_callback(msgbus_msg_id: int, action: str) -> bool:
    """Process an approval callback from Telegram.

    Args:
        msgbus_msg_id: The original MsgBus message ID (from reply_to)
        action: "approve" or "reject"

    Returns True if processed successfully.
    """
    approval = db.find_approval_by_msgbus_id(msgbus_msg_id)

    if approval is None:
        # Fallback: user may have acted on a timed_out (or otherwise resolved) approval
        approval = db.find_approval_by_msgbus_id_any_status(msgbus_msg_id)
        if approval is None:
            log.warning("No approval record for msgbus_msg_id=%d", msgbus_msg_id)
            return False

        if approval.status == "timed_out":
            log.info(
                "Late callback on timed_out approval: id=%d, task=%d, gate=%s, action=%s",
                approval.id, approval.task_id, approval.gate_type, action,
            )
        else:
            # Already approved/rejected/revise_requested — don't re-process
            log.warning(
                "Approval already resolved: id=%d, status=%s, msgbus_msg_id=%d",
                approval.id, approval.status, msgbus_msg_id,
            )
            return False

    task_id = approval.task_id
    gate_type = approval.gate_type

    log.info("Callback: task=%d, gate=%s, action=%s", task_id, gate_type, action)

    if action == "approve":
        return _process_approve(approval)
    elif action == "revise":
        return _process_revise(approval)
    elif action == "reject":
        return _process_reject(approval)
    else:
        log.warning("Unknown action: %s", action)
        return False


def _process_approve(approval: db.PendingApproval) -> bool:
    """Process an approval."""
    task_id = approval.task_id
    gate_type = approval.gate_type
    gate_config = APPROVAL_GATES.get(gate_type)

    if gate_config is None:
        log.error("Unknown gate type: %s", gate_type)
        return False

    cli_cmd = gate_config["cli_cmd"]

    # Call the appropriate dev-queue approval command
    if cli_cmd == "approve-to-queue":
        result = pm.approve_to_queue(task_id)
    elif cli_cmd == "approve-stable":
        result = pm.approve_stable(task_id)
    elif cli_cmd == "approve-plan":
        result = pm.approve_plan(task_id)
    else:
        log.error("Unknown CLI command: %s", cli_cmd)
        return False

    if not result.success:
        log.error("Approval CLI failed: %s", result.error)
        notifier.notify_error(task_id, f"Task #{task_id}", f"승인 처리 실패: {result.error}")
        return False

    # Resolve the approval record
    db.resolve_approval(approval.id, "approved")
    db.log_event(task_id, "approval_res", {
        "gate_type": gate_type, "resolution": "approved",
    })

    log.info("Approved: task=%d, gate=%s", task_id, gate_type)
    return True


def _process_revise(approval: db.PendingApproval) -> bool:
    """Process a revision request — keep worker alive, send connection info."""
    task_id = approval.task_id
    gate_type = approval.gate_type

    # Resolve as revise_requested (워커 assignment는 유지)
    db.resolve_approval(approval.id, "revise_requested")
    db.log_event(task_id, "approval_res", {
        "gate_type": gate_type, "resolution": "revise_requested",
    })

    # 활성 워커 찾아서 접속 안내 전송
    assignment = db.get_active_assignment_for_task(task_id)
    worker_id = assignment.worker_id if assignment else 0
    title = f"Task #{task_id}"
    notifier.notify_revision_request(task_id, title, gate_type, worker_id)

    log.info("Revise requested: task=%d, gate=%s, worker=%d", task_id, gate_type, worker_id)
    return True


def _process_reject(approval: db.PendingApproval) -> bool:
    """Process a rejection."""
    task_id = approval.task_id
    gate_type = approval.gate_type
    gate_config = APPROVAL_GATES.get(gate_type)

    if gate_config is None:
        log.error("Unknown gate type: %s", gate_type)
        return False

    cli_cmd = gate_config["cli_cmd"]

    # For plan approvals, reject the plan
    if cli_cmd == "approve-plan":
        result = pm.reject_plan(task_id, reason="Rejected via Telegram")
    else:
        # For stage transitions, we just mark as rejected and keep current stage
        result = pm.PipelineResult(success=True, data={"message": "Rejection noted"})

    db.resolve_approval(approval.id, "rejected")
    db.log_event(task_id, "approval_res", {
        "gate_type": gate_type, "resolution": "rejected",
    })

    log.info("Rejected: task=%d, gate=%s", task_id, gate_type)
    return True


def check_timeouts() -> int:
    """Check for timed-out approvals and send reminders. Returns count.

    Only sends a reminder if no reminder was sent in the last `approval_timeout` seconds
    (default 30 min) to avoid spamming.
    """
    approval_timeout = get_runtime_int("approval_timeout", APPROVAL_TIMEOUT)
    timed_out = db.get_timed_out_approvals(approval_timeout)
    reminded = 0

    for appr in timed_out:
        last = db.get_last_event_time(appr.task_id, "approval_reminder")
        if last is not None:
            from datetime import datetime, timezone
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < approval_timeout:
                continue

        result = pm.get_task_detail(appr.task_id)
        title = result.data.get("title", f"Task #{appr.task_id}") if result.success else f"Task #{appr.task_id}"
        notifier.notify_approval_timeout(appr.task_id, title, appr.gate_type)
        db.log_event(appr.task_id, "approval_reminder", {
            "gate_type": appr.gate_type, "approval_id": appr.id,
        })
        reminded += 1

    return reminded
