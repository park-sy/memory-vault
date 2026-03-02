"""Dashboard — rich /feature status formatting.

Generates a comprehensive pipeline dashboard view combining:
- Pipeline stage overview with feature cards
- Worker pool status
- Pending approvals
- Token budget
- Recent events
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from . import db
from . import worker_manager as wm
from . import token_gate
from .config import STAGES, MAX_CONCURRENT_FEATURES, STAGE_CONCURRENCY

log = logging.getLogger("factory.dashboard")


def render_status(pipeline_data: dict) -> str:
    """Render a full dashboard view for Telegram.

    Args:
        pipeline_data: Result from pipeline_manager.get_queue_status().data

    Returns:
        Formatted multi-line string for Telegram.
    """
    items = pipeline_data.get("items", [])
    active = [i for i in items if i.get("stage") != "done"]
    done_count = sum(1 for i in items if i.get("stage") == "done")

    lines = ["[Feature Factory] Dashboard"]
    lines.append(f"{'─' * 36}")

    # Pipeline overview
    lines.append("")
    lines.append(_render_pipeline(active))

    # Feature cards
    if active:
        lines.append("")
        lines.append("Features:")
        for item in active:
            lines.append(_render_feature_card(item))

    # Workers
    lines.append("")
    lines.append(_render_workers())

    # Approvals
    approvals_str = _render_approvals()
    if approvals_str:
        lines.append("")
        lines.append(approvals_str)

    # Token budget
    lines.append("")
    lines.append(_render_token_budget())

    # Recent events
    lines.append("")
    lines.append(_render_recent_events())

    # Footer
    lines.append("")
    lines.append(f"{'─' * 36}")
    supervision = db.get_config("supervision") or "on"
    paused = db.get_config("paused") == "true"
    status_icon = "⏸" if paused else "▶"
    lines.append(f"{status_icon} supervision={supervision} | done={done_count}")

    return "\n".join(lines)


def render_compact_status(pipeline_data: dict) -> str:
    """Render a compact one-line status for quick checks."""
    items = pipeline_data.get("items", [])
    active = [i for i in items if i.get("stage") != "done"]

    if not active:
        return "[Feature Factory] Pipeline empty"

    stage_map = {}
    for item in active:
        stage = item.get("stage", "?")
        stage_map.setdefault(stage, []).append(item.get("title", "?")[:10])

    parts = []
    for stage in STAGES:
        if stage in stage_map:
            names = ", ".join(stage_map[stage])
            parts.append(f"{stage}({names})")

    workers = wm.get_all_worker_states()
    busy = sum(1 for w in workers if w.assignment)
    pending = len(db.get_pending_approvals())

    return f"[FF] {' > '.join(parts)} | W:{busy}/{len(workers)} | A:{pending}"


def _render_pipeline(active: list) -> str:
    """Render pipeline stage bar."""
    stage_items = {}
    for item in active:
        stage = item.get("stage", "?")
        stage_items.setdefault(stage, []).append(item)

    parts = []
    for stage in STAGES:
        if stage == "done":
            continue
        count = len(stage_items.get(stage, []))
        limit = STAGE_CONCURRENCY.get(stage, "-")
        if count > 0:
            parts.append(f"[{stage} {count}/{limit}]")
        else:
            parts.append(f" {stage} ")

    return " > ".join(parts)


def _render_feature_card(item: dict) -> str:
    """Render a single feature as a compact card."""
    task_id = item.get("id", "?")
    title = item.get("title", "?")
    stage = item.get("stage", "?")
    plan_status = item.get("plan_status")

    assignment = db.get_active_assignment_for_task(task_id) if isinstance(task_id, int) else None
    worker_str = f"pool-{assignment.worker_id}({assignment.role})" if assignment else "unassigned"

    parts = [f"  #{task_id} {title}"]
    parts.append(f"    {stage}")
    if plan_status:
        parts.append(f" plan={plan_status}")
    parts.append(f" | {worker_str}")

    return "".join(parts)


def _render_workers() -> str:
    """Render worker pool status."""
    workers = wm.get_all_worker_states()
    if not workers:
        return "Workers: none"

    busy = sum(1 for w in workers if w.assignment)
    idle = sum(1 for w in workers if w.is_idle)
    down = sum(1 for w in workers if not w.exists)

    lines = [f"Workers: {len(workers)} (busy={busy} idle={idle}" + (f" down={down}" if down else "") + ")"]

    for w in workers:
        if w.assignment:
            status = f"#{w.assignment.task_id} {w.assignment.stage}"
        elif w.exists:
            status = "idle"
        else:
            status = "DOWN"
        lines.append(f"  pool-{w.worker_id}: {status}")

    return "\n".join(lines)


def _render_approvals() -> str:
    """Render pending approvals."""
    approvals = db.get_pending_approvals()
    if not approvals:
        return ""

    lines = [f"Pending Approvals: {len(approvals)}"]
    for a in approvals:
        lines.append(f"  #{a.task_id}: {a.gate_type} (since {a.created_at[:16]})")

    return "\n".join(lines)


def _render_token_budget() -> str:
    """Render token budget info."""
    workers = wm.get_all_worker_states()
    budget = token_gate.check_budget(len(workers))

    if budget.source == "token_monitor":
        return (
            f"Tokens: {budget.utilization_pct:.0f}% used | "
            f"headroom={budget.headroom_pct:.0f}% | "
            f"max_workers={budget.max_workers}"
        )
    return f"Tokens: N/A (fallback cap={budget.max_workers})"


def _render_recent_events(limit: int = 5) -> str:
    """Render most recent factory events."""
    events = db.get_recent_events(limit)
    if not events:
        return "Events: none"

    lines = ["Recent:"]
    for e in events:
        ts = e.created_at[11:16] if len(e.created_at) > 11 else e.created_at
        lines.append(f"  {ts} #{e.task_id} {e.event_type}")

    return "\n".join(lines)
