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
    NOTIFY_PY, WHOS_LIFE_DIR,
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
    """Send an approval request with approve/reject buttons.

    gate별 artifact 파일이 있으면 먼저 파일을 전송한 뒤 승인 버튼 메시지를 보냄.
    """
    gate_labels = {
        "spec_to_queued": "Spec 승인",
        "design_plan": "설계 계획 승인",
        "testing_to_stable": "Testing → Stable 승인",
        "coding_plan": "구현 계획 승인",
    }
    label = gate_labels.get(gate_type, gate_type)

    # artifact 파일 첨부 (있으면)
    artifact = _find_artifact(title, gate_type)
    if artifact:
        _send_artifact_file(task_id, title, label, artifact)

    message = f"[Feature Factory] {label}\nTask #{task_id}: {title}\n\n승인하시겠습니까?"
    return send_notification(
        message,
        channel=CHANNEL_APPROVAL,
        actions=["approve", "revise", "reject"],
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
    links = _worker_action_links(worker_id)
    message = (
        f"[Feature Factory] 워커 배정\n"
        f"Task #{task_id}: {title}\n"
        f"pool-{worker_id} ({role}) → {stage}\n\n"
        f"{links}"
    )
    return send_notification(message, channel=CHANNEL_OPS)


def notify_supervision_connect(
    task_id: int, title: str, worker_id: int, stage: str,
) -> Optional[int]:
    """Notify user to connect to worker in supervision mode."""
    links = _worker_action_links(worker_id)
    message = (
        f"[Feature Factory] {stage} 계획 준비됨\n"
        f"Task #{task_id}: {title}\n\n"
        f"{links}"
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


def notify_revision_request(
    task_id: int, title: str, gate_type: str, worker_id: int,
) -> Optional[int]:
    """수정 요청 시 워커 접속 안내 메시지 전송."""
    gate_labels = {
        "spec_to_queued": "Spec 수정",
        "design_plan": "설계 계획 수정",
        "testing_to_stable": "Testing 수정",
        "coding_plan": "구현 계획 수정",
    }
    label = gate_labels.get(gate_type, gate_type)
    links = _worker_action_links(worker_id)
    message = (
        f"[Feature Factory] {label} 요청\n"
        f"Task #{task_id}: {title}\n\n"
        f"워커에 수정 지시:\n"
        f"  /pool{worker_id} <수정 내용>\n\n"
        f"{links}"
    )
    return send_notification(message, channel=CHANNEL_APPROVAL, priority=3)


# ── Worker action links ──────────────────────────────────────────────────────

# Claude 앱 Code 탭을 여는 Universal Link (앱 내에서 세션 목록 접근 가능)
_CLAUDE_CODE_LINK = "https://claude.ai/code/open"


def _worker_action_links(worker_id: int) -> str:
    """워커 접속 링크 텍스트 생성."""
    session = f"cc-pool-{worker_id}"
    return (
        f"`tmux attach -t {session}`\n"
        f"[Claude 앱 열기]({_CLAUDE_CODE_LINK})"
    )


# ── Artifact helpers ──────────────────────────────────────────────────────────

# gate → artifact 파일 패턴
_GATE_ARTIFACTS = {
    "spec_to_queued": "spec.md",
    "design_plan": "SKILL.md",
    "coding_plan": "SKILL.md",
}


def _title_to_slug(title: str) -> str:
    """Feature title → 디렉토리 slug."""
    return title.lower().replace(" ", "-")


def _find_artifact(title: str, gate_type: str) -> Optional[str]:
    """gate 종류에 맞는 artifact 파일 경로를 찾는다. 없으면 None."""
    filename = _GATE_ARTIFACTS.get(gate_type)
    if not filename:
        return None

    slug = _title_to_slug(title)
    path = WHOS_LIFE_DIR / "skills" / slug / filename
    if path.exists():
        return str(path)

    log.debug("Artifact not found: %s", path)
    return None


def _send_artifact_file(
    task_id: int, title: str, label: str, file_path: str,
) -> None:
    """Telegram API로 artifact 파일을 직접 전송."""
    try:
        from telegram_api import load_config, send_document

        config = load_config()
        caption = f"[FF] #{task_id} {title}\n{label}"
        send_document(config, file_path, caption=caption, topic="approval")
        log.info("Artifact sent: task=%d file=%s", task_id, file_path)
    except Exception as e:
        log.warning("Artifact send failed (task=%d): %s", task_id, e)


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
