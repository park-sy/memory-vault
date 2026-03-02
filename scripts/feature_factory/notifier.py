"""Notifier — wrapper around notify.py for outbound Telegram messages.

Sends messages via MsgBus → telegram_bridge → Telegram.
Also supports sending MsgBus messages directly to other recipients (e.g., workers).
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .config import (
    DAEMON_ID, CHANNEL_APPROVAL, CHANNEL_OPS, CHANNEL_REPORT,
    NOTIFY_PY,
)

# Import msgbus for direct MsgBus operations
sys.path.insert(0, str(Path(__file__).parent.parent))
from msgbus import MsgBusConfig, init_db as init_msgbus, send as msgbus_send

log = logging.getLogger("factory.notifier")


def send_notification(
    message: str,
    channel: Optional[str] = None,
    actions: Optional[List[str]] = None,
    priority: int = 5,
    recipient: str = "telegram",
) -> Optional[int]:
    """Send a notification via notify.py. Returns MsgBus message ID or None."""
    cmd = [sys.executable, NOTIFY_PY, message, "--sender", DAEMON_ID, "--recipient", recipient]

    if channel:
        cmd.extend(["--channel", channel])
    if actions:
        cmd.extend(["--actions", *actions])
    if priority != 5:
        cmd.extend(["--priority", str(priority)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            log.error("notify.py failed: %s", result.stderr)
            return None
        data = json.loads(result.stdout)
        return data.get("msg_id")
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        log.error("Notification error: %s", e)
        return None


# ── High-level notification functions ────────────────────────────────────────

def notify_approval_request(
    task_id: int, title: str, gate_type: str,
) -> Optional[int]:
    """Send an approval request with approve/reject buttons."""
    gate_labels = {
        "spec_to_queued": "Spec 승인",
        "design_plan": "설계 계획 승인",
        "testing_to_stable": "Testing → Stable 승인",
        "coding_plan": "구현 계획 승인",
    }
    label = gate_labels.get(gate_type, gate_type)
    message = f"[Feature Factory] {label}\nTask #{task_id}: {title}\n\n승인하시겠습니까?"
    return send_notification(
        message,
        channel=CHANNEL_APPROVAL,
        actions=["approve", "reject"],
        priority=3,
    )


def notify_stage_complete(task_id: int, title: str, stage: str) -> Optional[int]:
    """Notify that a pipeline stage has completed."""
    message = f"[Feature Factory] {title}\n{stage} 완료"
    return send_notification(message, channel=CHANNEL_REPORT)


def notify_feature_done(task_id: int, title: str) -> Optional[int]:
    """Notify that a feature is fully done."""
    message = f"[Feature Factory] {title} feature 완성!"
    return send_notification(message, channel=CHANNEL_REPORT, priority=3)


def notify_worker_assigned(
    task_id: int, title: str, worker_id: int, role: str, stage: str,
) -> Optional[int]:
    """Notify that a worker has been assigned."""
    message = f"[Feature Factory] 워커 배정\nTask #{task_id}: {title}\npool-{worker_id} ({role}) → {stage}"
    return send_notification(message, channel=CHANNEL_OPS)


def notify_supervision_connect(
    task_id: int, title: str, worker_id: int, stage: str,
) -> Optional[int]:
    """Notify user to connect to worker in supervision mode."""
    message = (
        f"[Feature Factory] {stage} 계획 준비됨\n"
        f"Task #{task_id}: {title}\n\n"
        f"연결: tmux attach-session -t cc-pool-{worker_id}"
    )
    return send_notification(message, channel=CHANNEL_APPROVAL, priority=3)


def notify_error(task_id: int, title: str, error: str) -> Optional[int]:
    """Notify about an error in the pipeline."""
    message = f"[Feature Factory] ERROR\nTask #{task_id}: {title}\n{error}"
    return send_notification(message, channel=CHANNEL_OPS, priority=1)


def notify_approval_timeout(task_id: int, title: str, gate_type: str) -> Optional[int]:
    """Remind user about pending approval."""
    message = (
        f"[Feature Factory] 승인 대기 중 (30분+)\n"
        f"Task #{task_id}: {title}\n"
        f"Gate: {gate_type}"
    )
    return send_notification(message, channel=CHANNEL_APPROVAL, priority=2)


def send_to_worker(worker_id: int, message: str) -> Optional[int]:
    """Send a message directly to a worker via MsgBus."""
    config = MsgBusConfig.default()
    init_msgbus(config)
    try:
        msg_id = msgbus_send(
            config,
            sender=DAEMON_ID,
            recipient=f"cc-pool-{worker_id}",
            msg_type="task",
            payload={"text": message},
        )
        return msg_id
    except Exception as e:
        log.error("Failed to send to worker %d: %s", worker_id, e)
        return None
