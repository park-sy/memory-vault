"""Production Report — auto-generate feature completion report.

When a feature reaches 'done', collects all events from factory_events
and generates a structured markdown report.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import db
from .config import WHOS_LIFE_DIR, FACTORY_DB_PATH

log = logging.getLogger("factory.report")


def _parse_timestamp(ts: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds / 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = int(minutes / 60)
    remaining_min = minutes % 60
    return f"{hours}h {remaining_min}m"


def generate_report(task_id: int, title: str) -> Optional[str]:
    """Generate a production report for a completed feature.

    Returns the file path of the generated report, or None on failure.
    """
    events = db.get_events_for_task(task_id)
    if not events:
        log.warning("No events for task %d, skipping report", task_id)
        return None

    # Parse events into timeline
    timeline = []
    approvals = []
    worker_assignments = []

    for event in events:
        detail = {}
        if event.detail:
            try:
                detail = json.loads(event.detail)
            except json.JSONDecodeError:
                pass

        if event.event_type == "stage_start":
            timeline.append({
                "event": "start",
                "stage": detail.get("stage", "?"),
                "at": event.created_at,
            })
        elif event.event_type == "stage_end":
            timeline.append({
                "event": "end",
                "stage": detail.get("stage", "?"),
                "at": event.created_at,
            })
        elif event.event_type == "approval_req":
            approvals.append({
                "gate": detail.get("gate_type", "?"),
                "requested_at": event.created_at,
                "resolution": None,
                "resolved_at": None,
            })
        elif event.event_type == "approval_res":
            # Match with last unresolved approval of same gate
            gate = detail.get("gate_type", "?")
            for appr in reversed(approvals):
                if appr["gate"] == gate and appr["resolution"] is None:
                    appr["resolution"] = detail.get("resolution", "?")
                    appr["resolved_at"] = event.created_at
                    break
        elif event.event_type == "worker_assign":
            worker_assignments.append({
                "worker_id": detail.get("worker_id"),
                "role": detail.get("role", "?"),
                "stage": detail.get("stage", "?"),
                "at": event.created_at,
            })

    # Calculate total duration
    first_event = _parse_timestamp(events[0].created_at)
    last_event = _parse_timestamp(events[-1].created_at)
    total_seconds = (last_event - first_event).total_seconds()

    # Build stage timeline table
    stage_rows = _build_stage_table(timeline)

    # Build approval log table
    approval_rows = _build_approval_table(approvals)

    # Build report markdown
    safe_name = title.lower().replace(" ", "-")
    report_lines = [
        f"# Production Report: {title}",
        "",
        "## Summary",
        f"- 총 소요: {_format_duration(total_seconds)}",
        f"- 워커 배정: {len(worker_assignments)}회",
        f"- 승인 게이트: {len(approvals)}회 "
        f"(reject {sum(1 for a in approvals if a.get('resolution') == 'rejected')}회)",
        "",
        "## Timeline",
        "| 단계 | 시작 | 완료 | 소요 | 워커 |",
        "|------|------|------|------|------|",
    ]

    for row in stage_rows:
        report_lines.append(
            f"| {row['stage']} | {row['start']} | {row['end']} | "
            f"{row['duration']} | {row['worker']} |"
        )

    report_lines.extend([
        "",
        "## Approval Log",
        "| 게이트 | 요청 시각 | 응답 시각 | 대기 | 결과 |",
        "|--------|----------|----------|------|------|",
    ])

    for row in approval_rows:
        report_lines.append(
            f"| {row['gate']} | {row['requested']} | {row['resolved']} | "
            f"{row['wait']} | {row['result']} |"
        )

    report_lines.extend([
        "",
        "## Worker Assignments",
    ])
    for wa in worker_assignments:
        report_lines.append(f"- pool-{wa['worker_id']} ({wa['role']}) → {wa['stage']} @ {wa['at']}")

    # Token Usage section
    token_records = db.get_tokens_for_task(task_id)
    if token_records:
        report_lines.extend([
            "",
            "## Token Usage",
            "| 단계 | 모델 | Input | Output | Cache Read | Cache Create | Duration |",
            "|------|------|-------|--------|------------|-------------|----------|",
        ])
        total_all = 0
        for tr in token_records:
            dur = _format_duration(tr.duration_ms / 1000) if tr.duration_ms > 0 else "-"
            report_lines.append(
                f"| {tr.stage} | {tr.model} | {tr.input_tokens:,} | {tr.output_tokens:,} "
                f"| {tr.cache_read_tokens:,} | {tr.cache_creation_tokens:,} | {dur} |"
            )
            total_all += tr.total_tokens
        report_lines.append(f"\n**Total tokens: {total_all:,}**")

    report_lines.extend([
        "",
        f"---",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ])

    report_content = "\n".join(report_lines) + "\n"

    # Write to whos-life skills directory
    report_path = _get_report_path(safe_name)
    if report_path:
        try:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            log.info("Production report written: %s", report_path)
            return report_path
        except OSError as e:
            log.error("Failed to write report: %s", e)

    # Fallback: write to storage
    fallback_path = str(
        Path(FACTORY_DB_PATH).parent / f"report-{task_id}-{safe_name}.md"
    )
    try:
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        log.info("Production report (fallback): %s", fallback_path)
        return fallback_path
    except OSError as e:
        log.error("Failed to write fallback report: %s", e)
        return None


def _get_report_path(safe_name: str) -> Optional[str]:
    """Get the report path in the whos-life skills directory."""
    skills_dir = WHOS_LIFE_DIR / "skills" / safe_name / "logs"
    if WHOS_LIFE_DIR.exists():
        return str(skills_dir / "production-report.md")
    return None


def _build_stage_table(timeline: list) -> list:
    """Build stage timeline rows from start/end events."""
    rows = []
    stage_starts = {}

    for entry in timeline:
        stage = entry["stage"]
        if entry["event"] == "start":
            stage_starts[stage] = entry["at"]
        elif entry["event"] == "end":
            start_time = stage_starts.pop(stage, None)
            if start_time:
                start_dt = _parse_timestamp(start_time)
                end_dt = _parse_timestamp(entry["at"])
                duration = _format_duration((end_dt - start_dt).total_seconds())
            else:
                start_time = "?"
                duration = "?"

            rows.append({
                "stage": stage,
                "start": start_time[:16] if start_time else "?",
                "end": entry["at"][:16],
                "duration": duration,
                "worker": "-",
            })

    return rows


def _build_approval_table(approvals: list) -> list:
    """Build approval log rows."""
    rows = []
    for appr in approvals:
        requested = appr["requested_at"][:16] if appr["requested_at"] else "?"
        resolved = appr.get("resolved_at", "")
        resolved_str = resolved[:16] if resolved else "-"
        result = appr.get("resolution", "pending") or "pending"

        wait = "-"
        if appr["requested_at"] and resolved:
            req_dt = _parse_timestamp(appr["requested_at"])
            res_dt = _parse_timestamp(resolved)
            wait = _format_duration((res_dt - req_dt).total_seconds())

        rows.append({
            "gate": appr["gate"],
            "requested": requested,
            "resolved": resolved_str,
            "wait": wait,
            "result": result,
        })

    return rows
