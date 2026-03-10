"""Dispatcher — event routing and pipeline tick logic.

The brain of Feature Factory. Routes MsgBus events to handlers
and drives pipeline state transitions.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import (
    DAEMON_ID, STAGE_ROLES, DEFAULT_PROJECT_DIR,
    MAX_CONCURRENT_FEATURES, STAGE_CONCURRENCY,
    get_runtime_int,
)
from . import db
from . import intent_parser
from . import pipeline_manager as pm
from . import worker_manager as wm
from . import approval_handler
from . import notifier
from . import report
from . import dashboard
from . import session_scanner

# Import msgbus
sys.path.insert(0, str(Path(__file__).parent.parent))
from msgbus import MsgBusConfig, init_db as init_msgbus, receive, ack, Message

log = logging.getLogger("factory.dispatch")


# ── Inbox Polling ────────────────────────────────────────────────────────────

def poll_inbox() -> List[Message]:
    """Poll MsgBus for messages addressed to cc-factory."""
    config = MsgBusConfig.default()
    init_msgbus(config)
    return receive(config, DAEMON_ID, limit=10)


def _ack_message(msg_id: int) -> None:
    """Acknowledge a processed message."""
    config = MsgBusConfig.default()
    ack(config, msg_id)


# ── Event Dispatch ───────────────────────────────────────────────────────────

def dispatch(msg: Message) -> None:
    """Route a MsgBus message to the appropriate handler."""
    payload = msg.payload_dict
    msg_type = msg.msg_type
    sender = msg.sender

    log.info("Dispatch: type=%s, sender=%s, payload=%s", msg_type, sender, str(payload)[:100])

    if msg_type == "command":
        _handle_command(msg, payload)
    elif msg_type == "callback":
        _handle_callback(msg, payload)
    elif msg_type == "notify":
        _handle_worker_notify(msg, payload)
    else:
        log.warning("Unknown msg_type: %s", msg_type)

    _ack_message(msg.id)


def _handle_command(msg: Message, payload: dict) -> None:
    """Handle /feature commands routed from telegram_bridge."""
    text = payload.get("text", "")

    # Parse intent
    intent = intent_parser.parse(text)
    log.info("Intent: action=%s, title=%s, task_id=%s", intent.action, intent.title, intent.task_id)

    if intent.action == "create":
        _create_feature(intent.title or "untitled")
    elif intent.action == "status":
        _send_status()
    elif intent.action == "list":
        _send_list()
    elif intent.action == "approve":
        _manual_approve(intent.task_id, intent.title)
    elif intent.action == "detail":
        _send_detail(intent.task_id)
    elif intent.action == "config":
        _update_config(intent.config_key, intent.config_value)
    elif intent.action == "help":
        _send_help()


def _handle_callback(msg: Message, payload: dict) -> None:
    """Handle approval callback from Telegram buttons."""
    action = payload.get("action", "")
    reply_to = msg.reply_to

    if not reply_to:
        # Try callback_prefix as the msgbus msg id
        prefix = payload.get("callback_prefix", "")
        if prefix and prefix.isdigit():
            reply_to = int(prefix)

    if not reply_to:
        log.warning("Callback without reply_to: %s", payload)
        return

    approval_handler.handle_callback(reply_to, action)


def _handle_worker_notify(msg: Message, payload: dict) -> None:
    """Handle completion notifications from workers."""
    try:
        # Worker sends: {"event":"stage_complete","stage":"spec","task_id":7}
        event_data = payload
        if isinstance(payload.get("text"), str):
            try:
                event_data = json.loads(payload["text"])
            except json.JSONDecodeError:
                event_data = payload

        event = event_data.get("event", "")
        task_id = event_data.get("task_id")
        stage = event_data.get("stage", "")

        if event == "stage_complete" and task_id:
            log.info("Worker complete: task=%d, stage=%s, sender=%s", task_id, stage, msg.sender)
            _handle_stage_complete(task_id, stage, msg.sender)
        else:
            log.debug("Unhandled worker notify: %s", event_data)
    except Exception as e:
        log.error("Error handling worker notify: %s", e)


# ── Command Handlers ─────────────────────────────────────────────────────────

def _create_feature(title: str) -> None:
    """Create a new feature idea and start the pipeline."""
    result = pm.register_idea(title)
    if not result.success:
        notifier.notify_error(0, title, f"아이디어 등록 실패: {result.error}")
        return

    task_id = result.data.get("id", 0)
    db.log_event(task_id, "stage_start", {"stage": "idea", "title": title})

    # Notify
    notifier.send_notification(
        f"[Feature Factory] 새 Feature 등록\n#{task_id}: {title}\nPipeline 시작됨",
        channel="report",
    )

    log.info("Feature created: #%d %s", task_id, title)

    # Immediately try to assign a worker for the idea stage
    _try_assign_worker(task_id, title, "idea")


def _send_status() -> None:
    """Send rich pipeline dashboard to Telegram."""
    result = pm.get_queue_status()
    if not result.success:
        notifier.send_notification(f"[Feature Factory] Status 조회 실패: {result.error}", channel="ops")
        return

    status_text = dashboard.render_status(result.data)
    notifier.send_notification(status_text, channel="report")


def _send_list() -> None:
    """Send active task list to Telegram."""
    result = pm.get_queue_status()
    if not result.success:
        notifier.send_notification(f"[Feature Factory] List 조회 실패: {result.error}", channel="ops")
        return

    items = result.data.get("items", [])
    active = [item for item in items if item.get("stage") != "done"]

    if not active:
        notifier.send_notification("[Feature Factory] 활성 태스크 없음", channel="report")
        return

    lines = ["[Feature Factory] Active Tasks"]
    for item in active:
        plan_info = f" (plan: {item.get('plan_status', 'none')})" if item.get("plan_status") else ""
        lines.append(f"  #{item['id']} [{item['stage']}] {item['title']}{plan_info}")

    notifier.send_notification("\n".join(lines), channel="report")


def _manual_approve(task_id: Optional[int], title: Optional[str]) -> None:
    """Handle manual approve command from Telegram."""
    if task_id:
        # Find the pending approval for this task
        approvals = db.get_pending_approvals()
        for appr in approvals:
            if appr.task_id == task_id:
                approval_handler.handle_callback(appr.msgbus_msg_id, "approve")
                return
        notifier.send_notification(
            f"[Feature Factory] Task #{task_id}에 대기 중인 승인 없음", channel="ops",
        )
    elif title:
        # Legacy: "approve planner" style
        notifier.send_notification(
            f"[Feature Factory] 'approve {title}' → /feature approve <id> 사용 필요",
            channel="ops",
        )


def _send_detail(task_id: Optional[int]) -> None:
    """Send task detail to Telegram."""
    if not task_id:
        notifier.send_notification("[Feature Factory] task_id 필요: /feature detail <id>", channel="ops")
        return

    result = pm.get_task_detail(task_id)
    if not result.success:
        notifier.send_notification(f"[Feature Factory] #{task_id} 조회 실패: {result.error}", channel="ops")
        return

    item = result.data
    lines = [
        f"[Feature Factory] #{item['id']}: {item['title']}",
        f"  Stage: {item['stage']}",
        f"  Status: {item['status']}",
        f"  Created: {item.get('created_at', 'N/A')}",
    ]
    if item.get("plan_status"):
        lines.append(f"  Plan: {item['plan_status']}")
    if item.get("test_runs"):
        lines.append(f"  Tests: {item.get('test_successes', 0)}/{item.get('test_runs', 0)} passed")

    # Assignment info from factory DB
    assignment = db.get_active_assignment_for_task(task_id)
    if assignment:
        lines.append(f"  Worker: pool-{assignment.worker_id} ({assignment.role})")

    notifier.send_notification("\n".join(lines), channel="report")


def _update_config(key: Optional[str], value: Optional[str]) -> None:
    """Update factory config."""
    if not key or not value:
        config = db.get_all_config()
        lines = ["[Feature Factory] Config"]
        for k, v in config.items():
            lines.append(f"  {k}: {v}")
        notifier.send_notification("\n".join(lines), channel="ops")
        return

    valid_keys = {
        "supervision", "paused",
        "base_pool_size", "max_pool_size", "idle_timeout",
        "stall_timeout", "approval_timeout", "max_concurrent_features",
    }
    if key not in valid_keys:
        notifier.send_notification(
            f"[Feature Factory] Unknown config key: {key}. Valid: {valid_keys}",
            channel="ops",
        )
        return

    db.set_config(key, value)
    notifier.send_notification(f"[Feature Factory] Config updated: {key} = {value}", channel="ops")


def _send_help() -> None:
    """Send help text to Telegram."""
    help_text = (
        "[Feature Factory] Commands:\n"
        "  /feature <제목>         새 Feature 생성\n"
        "  /feature status        파이프라인 현황\n"
        "  /feature list          활성 태스크 목록\n"
        "  /feature approve <id>  승인\n"
        "  /feature detail <id>   상세 조회\n"
        "  /feature config        설정 조회\n"
        "  /feature config supervision on|off"
    )
    notifier.send_notification(help_text, channel="ops")


# ── Stage Complete Handler ───────────────────────────────────────────────────

def _handle_stage_complete(task_id: int, stage: str, sender: str) -> None:
    """Handle a worker completing a pipeline stage."""
    # Idempotency guard — 이미 처리된 경우 (assignment 없음) 전체 skip
    assignment = db.get_active_assignment_for_task(task_id)
    if not assignment:
        log.info(
            "stage_complete ignored (no active assignment): task=%d stage=%s sender=%s",
            task_id, stage, sender,
        )
        return

    # Release the worker
    _scan_and_record_tokens(task_id, stage, assignment)
    wm.release_worker(assignment.id)

    db.log_event(task_id, "stage_end", {"stage": stage, "sender": sender})

    # Get task title
    result = pm.get_task_detail(task_id)
    title = result.data.get("title", f"Task #{task_id}") if result.success else f"Task #{task_id}"

    # Determine next action based on stage
    if stage == "idea":
        # idea → spec: assign planner
        pm.advance_stage(task_id, "spec")
        _try_assign_worker(task_id, title, "spec")

    elif stage == "spec":
        # spec done → request approval to queue
        notifier.notify_stage_complete(task_id, title, "spec")
        context = result.data if result.success else None
        approval_handler.request_approval(task_id, title, "spec_to_queued", context=context)

    elif stage == "designing":
        # designing done → advance to testing
        pm.advance_stage(task_id, "testing")
        _try_assign_worker(task_id, title, "testing")

    elif stage == "testing":
        # testing done → request approval to stable
        notifier.notify_stage_complete(task_id, title, "testing")
        context = result.data if result.success else None
        approval_handler.request_approval(task_id, title, "testing_to_stable", context=context)

    elif stage == "coding":
        # coding done → advance to done
        pm.advance_stage(task_id, "done")
        db.log_event(task_id, "feature_done", {"title": title})

        # Generate production report
        try:
            report_path = report.generate_report(task_id, title)
            if report_path:
                db.log_event(task_id, "report_generated", {"path": report_path})
        except Exception as e:
            log.error("Report generation failed for task %d: %s", task_id, e)

        notifier.notify_feature_done(task_id, title)


# ── Token Scanning ──────────────────────────────────────────────────────────

def _scan_and_record_tokens(task_id: int, stage: str, assignment) -> None:
    """워커 세션의 JSONL 파일을 스캔해서 토큰 사용량 기록."""
    try:
        assigned_ts = _parse_timestamp(assignment.assigned_at)
        result = session_scanner.scan_session_tokens(DEFAULT_PROJECT_DIR, assigned_ts)
        if result is None:
            return

        now_ts = time.time()
        duration_ms = int((now_ts - assigned_ts) * 1000)

        db.record_stage_tokens(
            task_id=task_id, stage=stage, model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_creation_tokens=result.cache_creation_tokens,
            cost_usd="0",
            duration_ms=duration_ms,
            session_id=result.session_id,
        )
        log.info("Token scan: task=%d stage=%s tokens=%d", task_id, stage, result.total_tokens)
    except Exception as e:
        log.warning("Token scan failed for task %d stage %s: %s", task_id, stage, e)


def _parse_timestamp(iso_str: str) -> float:
    """ISO 문자열 → Unix timestamp."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ── Pipeline Tick ────────────────────────────────────────────────────────────

def tick_pipeline() -> None:
    """Main pipeline tick — check for actionable items and drive transitions.

    Enforces concurrency limits:
    - MAX_CONCURRENT_FEATURES: total features with active workers
    - STAGE_CONCURRENCY: per-stage slot limits
    """
    # Check if paused
    if db.get_config("paused") == "true":
        return

    result = pm.get_queue_status()
    if not result.success:
        log.debug("Queue status unavailable: %s", result.error)
        return

    items = result.data.get("items", [])

    # Build concurrency snapshot
    stage_counts = _count_active_by_stage(items)
    active_feature_count = sum(1 for v in stage_counts.values() if v > 0)

    for item in items:
        task_id = item["id"]
        stage = item.get("stage", "")
        title = item.get("title", "")
        plan_status = item.get("plan_status")

        # Skip done/queued-waiting items
        if stage == "done":
            continue

        # Skip if worker already assigned
        assignment = db.get_active_assignment_for_task(task_id)
        if assignment:
            continue

        # Skip if approval already pending
        pending = db.get_pending_approvals()
        has_pending = any(a.task_id == task_id for a in pending)
        if has_pending:
            continue

        # Check stage-level concurrency before worker assignment
        stage_limit = STAGE_CONCURRENCY.get(stage, 1)
        current_in_stage = stage_counts.get(stage, 0)

        # Drive state machine
        if stage == "idea":
            # idea: assign worker to analyze and produce spec
            idea_limit = STAGE_CONCURRENCY.get("idea", 2)
            if stage_counts.get("idea", 0) >= idea_limit:
                continue
            if _try_assign_worker(task_id, title, "idea"):
                stage_counts["idea"] = stage_counts.get("idea", 0) + 1

        elif stage == "spec":
            # spec: assign planner to write spec with user
            spec_limit = STAGE_CONCURRENCY.get("spec", 2)
            if stage_counts.get("spec", 0) >= spec_limit:
                continue
            if _try_assign_worker(task_id, title, "spec"):
                stage_counts["spec"] = stage_counts.get("spec", 0) + 1

        elif stage == "queued":
            # queued → designing: check designing slot
            designing_limit = STAGE_CONCURRENCY.get("designing", 1)
            if stage_counts.get("designing", 0) >= designing_limit:
                log.debug("Task %d queued — designing slots full (%d/%d)", task_id, stage_counts.get("designing", 0), designing_limit)
                continue
            pm.advance_stage(task_id, "designing")
            if _try_assign_worker(task_id, title, "designing"):
                stage_counts["designing"] = stage_counts.get("designing", 0) + 1

        elif stage == "designing" and plan_status == "pending_review":
            approval_handler.request_approval(task_id, title, "design_plan", context=dict(item))

        elif stage in ("designing",) and plan_status in (None, "approved"):
            if current_in_stage >= stage_limit:
                continue
            if _try_assign_worker(task_id, title, "designing"):
                stage_counts["designing"] = current_in_stage + 1

        elif stage == "stable":
            coding_limit = STAGE_CONCURRENCY.get("coding", 1)
            if stage_counts.get("coding", 0) >= coding_limit:
                log.debug("Task %d stable — coding slots full", task_id)
                continue
            pm.advance_stage(task_id, "coding")
            if _try_assign_worker(task_id, title, "coding"):
                stage_counts["coding"] = stage_counts.get("coding", 0) + 1

        elif stage == "coding" and plan_status == "pending_review":
            approval_handler.request_approval(task_id, title, "coding_plan", context=dict(item))

        elif stage == "coding" and plan_status in (None, "approved"):
            if current_in_stage >= stage_limit:
                continue
            if _try_assign_worker(task_id, title, "coding"):
                stage_counts["coding"] = current_in_stage + 1


def _count_active_by_stage(items: list) -> dict:
    """Count items with active worker assignments per stage."""
    counts = {}
    for item in items:
        stage = item.get("stage", "")
        if stage == "done":
            continue
        task_id = item["id"]
        assignment = db.get_active_assignment_for_task(task_id)
        if assignment:
            counts[stage] = counts.get(stage, 0) + 1
    return counts


# ── Worker Assignment ────────────────────────────────────────────────────────

def _try_assign_worker(task_id: int, title: str, stage: str) -> bool:
    """Try to find/create a worker and assign the task."""
    role = wm.get_role_for_stage(stage)

    worker_id = wm.ensure_worker_available(DEFAULT_PROJECT_DIR)
    if worker_id is None:
        log.warning("No worker available for task %d stage %s", task_id, stage)
        return False

    supervision = db.get_config("supervision") == "on"

    # Build task message
    task_message = _build_task_message(task_id, title, stage, supervision)

    assignment_id = wm.assign_worker(worker_id, task_id, role, stage, task_message)
    if assignment_id is None:
        return False

    # Notify
    notifier.notify_worker_assigned(task_id, title, worker_id, role, stage)

    if supervision:
        notifier.notify_supervision_connect(task_id, title, worker_id, stage)

    return True


def _build_task_message(task_id: int, title: str, stage: str, supervision: bool) -> str:
    """Build the task message to send to a worker."""
    # Base completion notification command
    completion_cmd = (
        f'python3 scripts/notify.py \'{{"event":"stage_complete","stage":"{stage}","task_id":{task_id}}}\' '
        f'--sender cc-pool-$(echo $CC_SESSION | grep -o "[0-9]*") '
        f'--recipient {DAEMON_ID} --channel ops'
    )

    if stage == "idea":
        return (
            f"Task #{task_id}: {title}\n\n"
            f"이 아이디어의 도메인을 분석해줘. 어떤 프로젝트에 속하는지, "
            f"유사 기능이 있는지, 기술적 고려사항을 정리해.\n\n"
            f"완료 후 반드시 실행:\n{completion_cmd}"
        )

    elif stage == "spec":
        prefix = "plan-mode로 계획만 세워라. " if supervision else ""
        return (
            f"{prefix}Task #{task_id}: {title}\n\n"
            f"이 기능의 spec을 작성해줘. 3가지 관점 필수:\n"
            f"1. 사용자 관점 (UI/UX)\n"
            f"2. AI 에이전트 관점 (SKILL 실행)\n"
            f"3. 데이터 관점 (DB 설계)\n\n"
            f"spec 파일: ~/dev/whos-life/skills/{title.lower().replace(' ', '-')}/spec.md\n\n"
            f"완료 후 반드시 실행:\n{completion_cmd}"
        )

    elif stage == "designing":
        prefix = "plan-mode로 계획만 세워라. " if supervision else ""
        return (
            f"{prefix}Task #{task_id}: {title}\n\n"
            f"SKILL.md를 작성해줘. 7개 섹션 규격 필수:\n"
            f"1. CLI Command Specifications\n"
            f"2. DB Schema\n"
            f"3. Data Models\n"
            f"4. UI Screen Flow\n"
            f"5. Agent Orchestration\n"
            f"6. Test Scenarios\n"
            f"7. LLM Boundary Summary\n\n"
            f"완료 후 반드시 실행:\n{completion_cmd}"
        )

    elif stage == "testing":
        prefix = "plan-mode로 계획만 세워라. " if supervision else ""
        return (
            f"{prefix}Task #{task_id}: {title}\n\n"
            f"Command-Level Verification 수행:\n"
            f"1. DB Schema 검증\n"
            f"2. 각 CLI command 개별 테스트\n"
            f"3. Command 체이닝 통합 테스트\n"
            f"4. Codification 분석\n\n"
            f"완료 후 반드시 실행:\n{completion_cmd}"
        )

    elif stage == "coding":
        prefix = "plan-mode로 계획만 세워라. " if supervision else ""
        return (
            f"{prefix}Task #{task_id}: {title}\n\n"
            f"service.py + render.py 구현:\n"
            f"1. codification 분석 기반 구현\n"
            f"2. codifiable → service.py 순수 함수\n"
            f"3. hybrid → service.py + SKILL.md\n"
            f"4. render.py UI\n\n"
            f"완료 후 반드시 실행:\n{completion_cmd}"
        )

    return f"Task #{task_id}: {title}\nStage: {stage}"
