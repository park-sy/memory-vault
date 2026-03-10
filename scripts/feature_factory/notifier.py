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
    context: Optional[dict] = None,
) -> Optional[int]:
    """Send an approval request with approve/reject buttons.

    gate별 artifact 파일이 있으면 먼저 파일을 전송한 뒤 승인 버튼 메시지를 보냄.
    context가 있으면 gate별 요약을 메시지 본문에 포함.
    """
    gate_labels = {
        "spec_to_queued": "Spec 승인",
        "design_plan": "설계 계획 승인",
        "testing_to_stable": "Testing → Stable 승인",
        "coding_plan": "구현 계획 승인",
        "coding_to_done": "구현 완료 승인",
    }
    label = gate_labels.get(gate_type, gate_type)

    # artifact 파일 첨부 (있으면)
    artifact = _find_artifact(title, gate_type)
    if artifact:
        _send_artifact_file(task_id, title, label, artifact)

    # testing_to_stable: 테스트 로그 파일도 첨부
    if gate_type == "testing_to_stable":
        test_log = _find_latest_test_log(title)
        if test_log:
            _send_artifact_file(task_id, title, label, test_log)

    # 요약 텍스트 생성
    summary = _build_approval_summary(gate_type, context) if context else ""
    parts = [f"[Feature Factory] {label}", f"Task #{task_id}: {title}"]
    if summary:
        parts.append(summary)
    parts.append("승인하시겠습니까?")
    message = "\n\n".join(parts)
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
    gate_labels = {
        "spec_to_queued": "Spec 승인",
        "design_plan": "설계 계획 승인",
        "testing_to_stable": "Testing → Stable 승인",
        "coding_plan": "구현 계획 승인",
        "coding_to_done": "구현 완료 승인",
    }
    label = gate_labels.get(gate_type, gate_type)
    message = (
        f"[Feature Factory] 승인 대기 중 (30분+)\n"
        f"Task #{task_id}: {title}\n"
        f"Gate: {label}"
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
        "coding_to_done": "구현 수정",
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


def notify_validation_failure(task_id: int, title: str, validation) -> Optional[int]:
    """산출물 검증 실패 알림 — APPROVAL 채널로 전송 (승인자 인지 필요)."""
    message = (
        f"[Feature Factory] 검증 실패\n"
        f"Task #{task_id}: {title}\n"
        f"Stage: {validation.stage}\n\n"
        f"{validation.summary}"
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


# ── Approval Summary ─────────────────────────────────────────────────────────

def _build_approval_summary(gate_type: str, context: dict) -> str:
    """gate 종류에 따라 승인 메시지에 포함할 요약 텍스트를 생성한다."""
    try:
        if gate_type == "spec_to_queued":
            return _summary_spec(context)
        elif gate_type in ("design_plan", "coding_plan"):
            return _summary_plan(context)
        elif gate_type == "testing_to_stable":
            return _summary_testing(context)
        elif gate_type == "coding_to_done":
            return _summary_coding(context)
    except Exception as e:
        log.warning("Failed to build approval summary for gate %s: %s", gate_type, e, exc_info=True)
    return ""


def _summary_spec(ctx: dict) -> str:
    """spec_to_queued: description + priority + category."""
    desc = ctx.get("description", "")
    if len(desc) > 200:
        desc = desc[:197] + "..."
    priority = ctx.get("priority", "-")
    category = ctx.get("category") or "-"

    if not desc and priority == "-":
        return ""

    lines = []
    if desc:
        lines.append(f"\U0001F4CB {desc}")
    lines.append(f"우선순위: {priority} | 카테고리: {category}")
    return "\n".join(lines)


def _summary_plan(ctx: dict) -> str:
    """design_plan / coding_plan: plan 요약 (단계 수, 주요 파일)."""
    plan = ctx.get("plan")
    if not plan:
        return ""

    # plan이 문자열이면 파싱 시도
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (json.JSONDecodeError, TypeError):
            return ""

    if not isinstance(plan, dict):
        return ""

    steps = plan.get("steps") or plan.get("phases") or plan.get("tasks") or []
    if not isinstance(steps, list):
        return ""
    step_count = len(steps)
    if step_count == 0:
        return ""

    lines = [f"\U0001F4D0 계획: {step_count}단계"]
    for i, step in enumerate(steps[:6], 1):
        name = ""
        if isinstance(step, dict):
            name = step.get("name") or step.get("title") or step.get("description", "")
        elif isinstance(step, str):
            name = step
        if name:
            lines.append(f"   {i}. {name}")

    # 주요 파일 추출
    files = plan.get("files") or plan.get("key_files") or plan.get("affected_files") or []
    if files:
        file_list = ", ".join(str(f) for f in files[:5])
        lines.append(f"주요 파일: {file_list}")

    return "\n".join(lines)


def _summary_testing(ctx: dict) -> str:
    """testing_to_stable: 테스트 결과 요약."""
    runs = ctx.get("test_runs") or 0
    successes = ctx.get("test_successes") or 0
    last_at = ctx.get("last_test_at") or ""

    if not runs:
        return "\u26a0\ufe0f 테스트 실행 0회 — 테스트가 수행되지 않았습니다!"

    pct = round(successes / runs * 100)
    lines = [f"\U0001F9EA 테스트: {runs}회 실행, {successes}회 성공 ({pct}%)"]
    if last_at:
        # ISO → 사람 읽기 좋은 형태 (초 제거)
        display_at = last_at[:16].replace("T", " ") if "T" in last_at else last_at
        lines.append(f"   마지막 실행: {display_at}")

    return "\n".join(lines)


def _summary_coding(ctx: dict) -> str:
    """coding_to_done: 변경 파일 목록 + 테스트 결과."""
    from .artifact_validator import get_git_changed_files

    lines = []
    files = get_git_changed_files()
    if files:
        lines.append(f"\U0001f4e6 변경 파일: {len(files)}개")
        for f in files[:8]:
            lines.append(f"   {f}")
        if len(files) > 8:
            lines.append(f"   ... 외 {len(files) - 8}개")
    else:
        lines.append("\u26a0\ufe0f 변경 파일 없음")

    test_runs = ctx.get("test_runs") or 0
    test_successes = ctx.get("test_successes") or 0
    if test_runs:
        pct = round(test_successes / test_runs * 100)
        lines.append(f"\U0001f9ea 테스트: {test_runs}회 실행, {test_successes}회 성공 ({pct}%)")

    return "\n".join(lines)


def _find_latest_test_log(title: str) -> Optional[str]:
    """testing 게이트용: 가장 최근 테스트 로그 파일 경로를 찾는다."""
    slug = _title_to_slug(title)
    logs_dir = WHOS_LIFE_DIR / "skills" / slug / "logs"
    if not logs_dir.exists():
        return None

    test_files = sorted(logs_dir.glob("test-*.md"), reverse=True)
    if test_files:
        return str(test_files[0])
    return None


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
