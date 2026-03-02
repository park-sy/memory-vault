"""Tests for Feature Factory modules — Phase 1 + Phase 2 + Phase 3."""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.harness import Suite, run_suite, write_jsonl


# ── intent_parser tests ──────────────────────────────────────────────────────

def test_intent_parser(s: Suite) -> None:
    from feature_factory.intent_parser import parse

    # Create feature
    intent = parse("여행 기능")
    s.check_eq("create: action", "create", intent.action)
    s.check_eq("create: title", "여행 기능", intent.title)

    # Status
    intent = parse("status")
    s.check_eq("status: action", "status", intent.action)

    intent = parse("상태")
    s.check_eq("status korean: action", "status", intent.action)

    # List
    intent = parse("list")
    s.check_eq("list: action", "list", intent.action)

    # Approve by ID
    intent = parse("approve 7")
    s.check_eq("approve id: action", "approve", intent.action)
    s.check_eq("approve id: task_id", 7, intent.task_id)

    # Approve by name
    intent = parse("approve planner")
    s.check_eq("approve name: action", "approve", intent.action)
    s.check_eq("approve name: title", "planner", intent.title)

    # Korean approve
    intent = parse("승인 7")
    s.check_eq("approve korean: action", "approve", intent.action)
    s.check_eq("approve korean: task_id", 7, intent.task_id)

    # Detail
    intent = parse("detail 7")
    s.check_eq("detail: action", "detail", intent.action)
    s.check_eq("detail: task_id", 7, intent.task_id)

    # Config
    intent = parse("config supervision on")
    s.check_eq("config: action", "config", intent.action)
    s.check_eq("config: key", "supervision", intent.config_key)
    s.check_eq("config: value", "on", intent.config_value)

    # Help
    intent = parse("")
    s.check_eq("help empty: action", "help", intent.action)

    intent = parse("help")
    s.check_eq("help explicit: action", "help", intent.action)

    # Unknown text → create
    intent = parse("검색 기능 만들어줘")
    s.check_eq("unknown text: action", "create", intent.action)
    s.check_eq("unknown text: title", "검색 기능 만들어줘", intent.title)

    # Approve with hash prefix
    intent = parse("approve #12")
    s.check_eq("approve hash: action", "approve", intent.action)
    s.check_eq("approve hash: task_id", 12, intent.task_id)

    # Detail with hash prefix
    intent = parse("detail #5")
    s.check_eq("detail hash: action", "detail", intent.action)
    s.check_eq("detail hash: task_id", 5, intent.task_id)


# ── db tests ─────────────────────────────────────────────────────────────────

def test_db(s: Suite) -> None:
    from feature_factory import db

    # Use a temp DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        # Init
        db.init_db(test_db_path)
        s.check("db init succeeds", True)

        # Init is idempotent
        db.init_db(test_db_path)
        s.check("db init idempotent", True)

        # Config CRUD
        val = db.get_config("supervision", test_db_path)
        s.check_eq("default supervision", "on", val)

        db.set_config("supervision", "off", test_db_path)
        val = db.get_config("supervision", test_db_path)
        s.check_eq("updated supervision", "off", val)

        all_config = db.get_all_config(test_db_path)
        s.check("all_config has supervision", "supervision" in all_config)
        s.check("all_config has paused", "paused" in all_config)

        # Worker Assignment CRUD
        aid = db.create_assignment(1, 42, "planner", "spec", test_db_path)
        s.check_gt("assignment id > 0", aid, 0)

        assignment = db.get_active_assignment_for_task(42, test_db_path)
        s.check_not_none("assignment found", assignment)
        s.check_eq("assignment worker_id", 1, assignment.worker_id)
        s.check_eq("assignment role", "planner", assignment.role)
        s.check_eq("assignment status", "assigned", assignment.status)

        assigned_ids = db.get_assigned_worker_ids(test_db_path)
        s.check("worker 1 in assigned", 1 in assigned_ids)

        # Complete assignment
        db.complete_assignment(aid, "completed", test_db_path)
        assignment = db.get_active_assignment_for_task(42, test_db_path)
        s.check_none("completed assignment not active", assignment)

        assigned_ids = db.get_assigned_worker_ids(test_db_path)
        s.check("worker 1 no longer assigned", 1 not in assigned_ids)

        # Pending Approvals CRUD
        appr_id = db.create_approval(42, "spec_to_queued", 100, test_db_path)
        s.check_gt("approval id > 0", appr_id, 0)

        pending = db.get_pending_approvals(test_db_path)
        s.check_eq("1 pending approval", 1, len(pending))
        s.check_eq("approval task_id", 42, pending[0].task_id)
        s.check_eq("approval gate_type", "spec_to_queued", pending[0].gate_type)

        found = db.find_approval_by_msgbus_id(100, test_db_path)
        s.check_not_none("found by msgbus_id", found)
        s.check_eq("found approval_id", appr_id, found.id)

        not_found = db.find_approval_by_msgbus_id(999, test_db_path)
        s.check_none("not found for unknown msgbus_id", not_found)

        # Resolve approval
        db.resolve_approval(appr_id, "approved", test_db_path)
        pending = db.get_pending_approvals(test_db_path)
        s.check_eq("0 pending after resolve", 0, len(pending))

        # Event Log
        eid = db.log_event(42, "stage_start", {"stage": "spec"}, test_db_path)
        s.check_gt("event id > 0", eid, 0)

        events = db.get_events_for_task(42, test_db_path)
        s.check_eq("1 event for task", 1, len(events))
        s.check_eq("event type", "stage_start", events[0].event_type)

        recent = db.get_recent_events(10, test_db_path)
        s.check_gt("recent events > 0", len(recent), 0)

        # Multiple assignments for different workers
        db.create_assignment(2, 43, "coder", "designing", test_db_path)
        db.create_assignment(3, 44, "qa", "testing", test_db_path)
        assigned = db.get_assigned_worker_ids(test_db_path)
        s.check_eq("3 assigned workers (2,3)", 2, len(assigned))

        # Get by worker
        w2 = db.get_active_assignment_for_worker(2, test_db_path)
        s.check_not_none("worker 2 assignment", w2)
        s.check_eq("worker 2 task", 43, w2.task_id)

    finally:
        os.unlink(test_db_path)


# ── config tests ─────────────────────────────────────────────────────────────

def test_config(s: Suite) -> None:
    from feature_factory.config import (
        DAEMON_ID, TICK_INTERVAL, BASE_POOL_SIZE, MAX_POOL_SIZE,
        STAGES, APPROVAL_GATES, STAGE_ROLES,
    )

    s.check_eq("daemon id", "cc-factory", DAEMON_ID)
    s.check_gt("tick interval > 0", TICK_INTERVAL, 0)
    s.check_gt("base pool > 0", BASE_POOL_SIZE, 0)
    s.check_gt("max pool >= base", MAX_POOL_SIZE, BASE_POOL_SIZE - 1)
    s.check("stages is tuple", isinstance(STAGES, tuple))
    s.check("idea in stages", "idea" in STAGES)
    s.check("done in stages", "done" in STAGES)
    s.check_eq("4 approval gates", 4, len(APPROVAL_GATES))
    s.check("spec role exists", "spec" in STAGE_ROLES)
    s.check("coding role exists", "coding" in STAGE_ROLES)


# ── report tests (Phase 2) ───────────────────────────────────────────────────

def test_report_format_duration(s: Suite) -> None:
    from feature_factory.report import _format_duration

    s.check_eq("seconds", "30s", _format_duration(30))
    s.check_eq("zero", "0s", _format_duration(0))
    s.check_eq("59 seconds", "59s", _format_duration(59))
    s.check_eq("1 minute", "1m", _format_duration(60))
    s.check_eq("34 minutes", "34m", _format_duration(34 * 60))
    s.check_eq("59 minutes", "59m", _format_duration(59 * 60))
    s.check_eq("1 hour", "1h 0m", _format_duration(3600))
    s.check_eq("1h 30m", "1h 30m", _format_duration(5400))
    s.check_eq("3h 42m", "3h 42m", _format_duration(3 * 3600 + 42 * 60))


def test_report_parse_timestamp(s: Suite) -> None:
    from feature_factory.report import _parse_timestamp

    # Standard DB format
    dt = _parse_timestamp("2026-03-01 14:30:00")
    s.check_eq("year", 2026, dt.year)
    s.check_eq("month", 3, dt.month)
    s.check_eq("hour", 14, dt.hour)
    s.check_eq("minute", 30, dt.minute)
    s.check_not_none("has tzinfo", dt.tzinfo)

    # ISO format
    dt2 = _parse_timestamp("2026-03-01T14:30:00")
    s.check_eq("iso year", 2026, dt2.year)
    s.check_eq("iso hour", 14, dt2.hour)

    # Invalid format → returns now (doesn't crash)
    dt3 = _parse_timestamp("invalid-date")
    s.check_not_none("invalid returns datetime", dt3)
    s.check_not_none("invalid has tzinfo", dt3.tzinfo)


def test_report_build_stage_table(s: Suite) -> None:
    from feature_factory.report import _build_stage_table

    timeline = [
        {"event": "start", "stage": "spec", "at": "2026-03-01 14:00:00"},
        {"event": "end", "stage": "spec", "at": "2026-03-01 14:34:00"},
        {"event": "start", "stage": "designing", "at": "2026-03-01 14:36:00"},
        {"event": "end", "stage": "designing", "at": "2026-03-01 15:20:00"},
    ]

    rows = _build_stage_table(timeline)
    s.check_eq("2 stage rows", 2, len(rows))
    s.check_eq("first stage is spec", "spec", rows[0]["stage"])
    s.check_eq("spec duration", "34m", rows[0]["duration"])
    s.check_eq("second stage is designing", "designing", rows[1]["stage"])
    s.check_eq("designing duration", "44m", rows[1]["duration"])

    # End without start → "?" duration
    timeline_orphan = [
        {"event": "end", "stage": "testing", "at": "2026-03-01 16:00:00"},
    ]
    rows2 = _build_stage_table(timeline_orphan)
    s.check_eq("orphan end row", 1, len(rows2))
    s.check_eq("orphan duration is ?", "?", rows2[0]["duration"])


def test_report_build_approval_table(s: Suite) -> None:
    from feature_factory.report import _build_approval_table

    approvals = [
        {
            "gate": "spec_to_queued",
            "requested_at": "2026-03-01 14:30:00",
            "resolved_at": "2026-03-01 14:32:00",
            "resolution": "approved",
        },
        {
            "gate": "design_plan",
            "requested_at": "2026-03-01 15:00:00",
            "resolved_at": None,
            "resolution": None,
        },
    ]

    rows = _build_approval_table(approvals)
    s.check_eq("2 approval rows", 2, len(rows))
    s.check_eq("first gate", "spec_to_queued", rows[0]["gate"])
    s.check_eq("first result", "approved", rows[0]["result"])
    s.check_eq("first wait", "2m", rows[0]["wait"])
    s.check_eq("second result", "pending", rows[1]["result"])
    s.check_eq("second wait (no resolve)", "-", rows[1]["wait"])


def test_report_generate(s: Suite) -> None:
    """Test full report generation using a temp DB and temp output dir."""
    from feature_factory import db
    from feature_factory import report

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    report_dir = tempfile.mkdtemp(prefix="report-test-")

    try:
        db.init_db(test_db_path)

        # Seed events for task 99
        db.log_event(99, "stage_start", {"stage": "spec"}, test_db_path)
        db.log_event(99, "worker_assign", {"worker_id": 1, "role": "planner", "stage": "spec"}, test_db_path)
        db.log_event(99, "stage_end", {"stage": "spec"}, test_db_path)
        db.log_event(99, "approval_req", {"gate_type": "spec_to_queued"}, test_db_path)
        db.log_event(99, "approval_res", {"gate_type": "spec_to_queued", "resolution": "approved"}, test_db_path)
        db.log_event(99, "stage_start", {"stage": "designing"}, test_db_path)
        db.log_event(99, "stage_end", {"stage": "designing"}, test_db_path)

        # Monkey-patch DB path and report output path for isolation
        orig_get_events = db.get_events_for_task
        db.get_events_for_task = lambda tid, dp=test_db_path: orig_get_events(tid, dp)

        orig_get_report_path = report._get_report_path
        report._get_report_path = lambda name: str(Path(report_dir) / f"{name}.md")

        result = report.generate_report(99, "Test Feature")

        # Restore
        db.get_events_for_task = orig_get_events
        report._get_report_path = orig_get_report_path

        s.check_not_none("report generated", result)
        if result:
            content = Path(result).read_text(encoding="utf-8")
            s.check_contains("has title", "Test Feature", content)
            s.check_contains("has summary section", "## Summary", content)
            s.check_contains("has timeline section", "## Timeline", content)
            s.check_contains("has approval section", "## Approval Log", content)
            s.check_contains("has worker section", "## Worker Assignments", content)
            s.check_contains("has planner in workers", "planner", content)

        # No events → returns None
        db.get_events_for_task = lambda tid, dp=test_db_path: orig_get_events(tid, dp)
        none_result = report.generate_report(999, "No Events")
        db.get_events_for_task = orig_get_events
        s.check_none("no events returns None", none_result)

    finally:
        os.unlink(test_db_path)
        import shutil
        shutil.rmtree(report_dir, ignore_errors=True)


# ── health_check tests (Phase 2) ─────────────────────────────────────────────

def test_health_check_parse_timestamp(s: Suite) -> None:
    from feature_factory.health_check import _parse_timestamp

    dt = _parse_timestamp("2026-03-01 10:00:00")
    s.check_eq("hc year", 2026, dt.year)
    s.check_eq("hc hour", 10, dt.hour)
    s.check_not_none("hc tzinfo", dt.tzinfo)

    dt2 = _parse_timestamp("2026-03-01T10:00:00")
    s.check_eq("hc iso year", 2026, dt2.year)

    dt3 = _parse_timestamp("garbage")
    s.check_not_none("hc invalid returns datetime", dt3)


def test_health_check_stalled_detection(s: Suite) -> None:
    """Test stalled assignment detection via DB query (no tmux dependency)."""
    from feature_factory import db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # Create an assignment with an old timestamp (simulate stall)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        with db.connect(test_db_path) as conn:
            conn.execute(
                """INSERT INTO worker_assignments
                   (worker_id, task_id, role, stage, status, assigned_at)
                   VALUES (?, ?, ?, ?, 'assigned', ?)""",
                (10, 100, "coder", "coding", old_time),
            )

        # Create a recent assignment (should not be stalled)
        db.create_assignment(11, 101, "planner", "spec", test_db_path)

        # Query for stalled (STALL_TIMEOUT = 900 = 15 min)
        with db.connect(test_db_path) as conn:
            stalled_rows = conn.execute(
                """SELECT * FROM worker_assignments
                   WHERE status = 'assigned'
                   AND julianday('now') - julianday(assigned_at) > ? / 86400.0""",
                (900,),  # 15 min
            ).fetchall()

        s.check_eq("1 stalled assignment", 1, len(stalled_rows))
        s.check_eq("stalled worker_id", 10, stalled_rows[0]["worker_id"])

        # Verify recent one is not stalled
        all_assigned = db.get_assigned_worker_ids(test_db_path)
        s.check("both workers assigned", len(all_assigned) == 2)

    finally:
        os.unlink(test_db_path)


def test_health_check_tmux_session_exists(s: Suite) -> None:
    """Test _tmux_session_exists with a session name that definitely doesn't exist."""
    from feature_factory.health_check import _tmux_session_exists

    # A session with this name should never exist
    exists = _tmux_session_exists("cc-pool-test-nonexistent-999")
    s.check("nonexistent session returns False", not exists)


# ── recovery tests (Phase 2) ─────────────────────────────────────────────────

def test_recovery_db_state(s: Suite) -> None:
    """Test recovery DB operations — stale assignment detection and approval queries."""
    from feature_factory import db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # Simulate pre-crash state:
        # Worker 5 has active assignment but session is gone
        db.create_assignment(5, 50, "coder", "coding", test_db_path)
        # Worker 6 has active assignment
        db.create_assignment(6, 51, "planner", "spec", test_db_path)

        # Pending approval from before crash
        db.create_approval(50, "coding_plan", 200, test_db_path)
        db.create_approval(51, "spec_to_queued", 201, test_db_path)

        # Verify pre-recovery state
        assigned = db.get_assigned_worker_ids(test_db_path)
        s.check_eq("2 assigned before recovery", 2, len(assigned))

        pending = db.get_pending_approvals(test_db_path)
        s.check_eq("2 pending before recovery", 2, len(pending))

        # Simulate recovery: release worker 5 (pretend session gone)
        assignment = db.get_active_assignment_for_worker(5, test_db_path)
        s.check_not_none("worker 5 assignment exists", assignment)

        db.complete_assignment(assignment.id, "failed", test_db_path)
        db.log_event(50, "recovery_release", {
            "worker_id": 5,
            "reason": "worker_session_gone_on_startup",
        }, test_db_path)

        # After releasing worker 5
        assigned_after = db.get_assigned_worker_ids(test_db_path)
        s.check_eq("1 assigned after recovery", 1, len(assigned_after))
        s.check("worker 6 still assigned", 6 in assigned_after)

        # Verify recovery event was logged
        events = db.get_events_for_task(50, test_db_path)
        s.check_eq("1 recovery event", 1, len(events))
        s.check_eq("event type", "recovery_release", events[0].event_type)
        detail = json.loads(events[0].detail)
        s.check_eq("event worker_id", 5, detail["worker_id"])

        # Simulate re-sending approval: resolve old, create new
        old_appr = db.find_approval_by_msgbus_id(200, test_db_path)
        s.check_not_none("old approval found", old_appr)
        db.resolve_approval(old_appr.id, "timed_out", test_db_path)
        db.create_approval(50, "coding_plan", 300, test_db_path)

        pending_after = db.get_pending_approvals(test_db_path)
        s.check_eq("2 pending (1 re-sent + 1 original)", 2, len(pending_after))

        # The re-sent one should have new msgbus_id
        new_appr = db.find_approval_by_msgbus_id(300, test_db_path)
        s.check_not_none("re-sent approval found", new_appr)
        s.check_eq("re-sent task_id", 50, new_appr.task_id)

    finally:
        os.unlink(test_db_path)


def test_recovery_timed_out_approvals(s: Suite) -> None:
    """Test get_timed_out_approvals query."""
    from feature_factory import db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # Create an old approval (30+ min ago)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S")
        with db.connect(test_db_path) as conn:
            conn.execute(
                """INSERT INTO pending_approvals
                   (task_id, gate_type, msgbus_msg_id, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)""",
                (60, "design_plan", 400, old_time),
            )

        # Create a recent approval
        db.create_approval(61, "spec_to_queued", 401, test_db_path)

        # Query timed out (1800 = 30 min)
        timed_out = db.get_timed_out_approvals(1800, test_db_path)
        s.check_eq("1 timed out approval", 1, len(timed_out))
        s.check_eq("timed out task_id", 60, timed_out[0].task_id)

        # Query with larger timeout → none should match
        none_timed = db.get_timed_out_approvals(86400, test_db_path)  # 24 hours
        s.check_eq("none timed out with large timeout", 0, len(none_timed))

    finally:
        os.unlink(test_db_path)


# ── intent_parser Level 1 tests (Phase 3) ────────────────────────────────────

def test_intent_parser_l0_extended(s: Suite) -> None:
    """Test Level 0 natural language keyword detection (Phase 3 addition)."""
    from feature_factory.intent_parser import parse

    # NL status hints
    intent = parse("지금 어때")
    s.check_eq("nl status action", "status", intent.action)
    s.check_eq("nl status confidence", 0.9, intent.confidence)

    intent = parse("파이프라인 현황")
    s.check_eq("nl pipeline status", "status", intent.action)

    # NL list hints
    intent = parse("뭐 있어")
    s.check_eq("nl list action", "list", intent.action)

    # NL approve hints
    intent = parse("승인해 #7")
    s.check_eq("nl approve action", "approve", intent.action)
    s.check_eq("nl approve task_id", 7, intent.task_id)
    s.check_eq("nl approve confidence", 0.9, intent.confidence)

    intent = parse("고고")
    s.check_eq("nl approve no id action", "approve", intent.action)
    s.check_eq("nl approve no id confidence", 0.8, intent.confidence)

    # Ambiguous → falls to create (no LLM in test)
    intent = parse("여행 기능 만들어줘")
    s.check_eq("create fallback action", "create", intent.action)
    s.check_eq("create fallback title", "여행 기능 만들어줘", intent.title)

    # New fields
    s.check_eq("default parse_level", 0, intent.parse_level)
    s.check("confidence is float", isinstance(intent.confidence, float))


def test_intent_parser_ambiguity_detection(s: Suite) -> None:
    """Test _is_ambiguous heuristic."""
    from feature_factory.intent_parser import _is_ambiguous

    s.check("question mark is ambiguous", _is_ambiguous("이거 뭐야?"))
    s.check("korean question ending", _is_ambiguous("어떻게 되고 있을까"))
    s.check("보여줘 is ambiguous", _is_ambiguous("보여줘"))
    s.check("task ref + text", _is_ambiguous("#7 어떻게 되고 있어"))
    s.check("plain feature name not ambiguous", not _is_ambiguous("여행 기능"))
    s.check("short command not ambiguous", not _is_ambiguous("리마인더"))


def test_intent_parser_extract_json(s: Suite) -> None:
    """Test _extract_json helper."""
    from feature_factory.intent_parser import _extract_json

    # Direct JSON
    result = _extract_json('{"action": "status"}')
    s.check_eq("direct json", '{"action": "status"}', result)

    # Markdown fenced
    result = _extract_json('```json\n{"action": "list"}\n```')
    s.check_eq("fenced json", '{"action": "list"}', result)

    # Embedded in text
    result = _extract_json('Here is the intent: {"action": "help"} done.')
    s.check_eq("embedded json", '{"action": "help"}', result)

    # No JSON
    result = _extract_json("just plain text")
    s.check_none("no json returns None", result)


# ── token_gate tests (Phase 3) ───────────────────────────────────────────────

def test_token_gate_fallback(s: Suite) -> None:
    """Test token_gate fallback mode (Token Monitor unavailable)."""
    from feature_factory.token_gate import _fallback_budget, check_budget
    from feature_factory.config import MAX_POOL_SIZE

    # Under limit
    budget = _fallback_budget(1)
    s.check("fallback available", budget.available)
    s.check_eq("fallback source", "fallback", budget.source)
    s.check_eq("fallback max_workers", MAX_POOL_SIZE, budget.max_workers)
    s.check_eq("fallback util", 0.0, budget.utilization_pct)

    # At limit
    budget = _fallback_budget(MAX_POOL_SIZE)
    s.check("fallback at limit not available", not budget.available)

    # Over limit
    budget = _fallback_budget(MAX_POOL_SIZE + 1)
    s.check("fallback over limit not available", not budget.available)


def test_token_gate_evaluate_budget(s: Suite) -> None:
    """Test token_gate._evaluate_budget with simulated Token Monitor data."""
    from feature_factory.token_gate import _evaluate_budget

    # Low utilization — should allow scaling
    data = {"windows": [
        {"utilization": 30.0},
        {"utilization": 25.0},
    ]}
    budget = _evaluate_budget(data, 1)
    s.check("low util: available", budget.available)
    s.check_eq("low util: source", "token_monitor", budget.source)
    s.check_eq("low util: max util", 30.0, budget.utilization_pct)
    s.check("low util: headroom > 0", budget.headroom_pct > 0)

    # High utilization — soft limit
    data = {"windows": [{"utilization": 75.0}]}
    budget = _evaluate_budget(data, 1)
    s.check("soft limit: still available", budget.available)
    s.check_contains("soft limit: reason warns", "소프트 리밋", budget.reason)

    # Over hard limit — should block
    data = {"windows": [{"utilization": 90.0}]}
    budget = _evaluate_budget(data, 1)
    s.check("hard limit: not available", not budget.available)
    s.check_contains("hard limit: reason mentions", "하드 리밋", budget.reason)
    s.check_eq("hard limit: headroom 0", 0.0, budget.headroom_pct)

    # Exactly at hard limit
    data = {"windows": [{"utilization": 85.0}]}
    budget = _evaluate_budget(data, 1)
    s.check("at hard limit: not available", not budget.available)

    # Empty windows → fallback
    data = {"windows": []}
    budget = _evaluate_budget(data, 1)
    s.check_eq("empty windows: fallback source", "fallback", budget.source)


# ── concurrency config tests (Phase 3) ───────────────────────────────────────

def test_concurrency_config(s: Suite) -> None:
    """Test concurrency configuration constants."""
    from feature_factory.config import (
        MAX_CONCURRENT_FEATURES, STAGE_CONCURRENCY, STAGES,
    )

    s.check_gt("max concurrent > 0", MAX_CONCURRENT_FEATURES, 0)
    s.check("stage concurrency is dict", isinstance(STAGE_CONCURRENCY, dict))
    s.check("designing has limit", "designing" in STAGE_CONCURRENCY)
    s.check("coding has limit", "coding" in STAGE_CONCURRENCY)
    s.check("testing has limit", "testing" in STAGE_CONCURRENCY)

    # All concurrency limits are positive
    for stage, limit in STAGE_CONCURRENCY.items():
        s.check_gt(f"{stage} limit > 0", limit, 0)


# ── dashboard tests (Phase 3) ────────────────────────────────────────────────

def test_dashboard_render_compact(s: Suite) -> None:
    """Test compact status rendering."""
    from feature_factory.dashboard import render_compact_status

    # Empty pipeline
    result = render_compact_status({"items": []})
    s.check_contains("empty pipeline message", "empty", result)

    # With items — uses item data only (no external calls for rendering)
    items = [
        {"id": 1, "title": "여행 기능", "stage": "designing"},
        {"id": 2, "title": "검색 기능", "stage": "spec"},
        {"id": 3, "title": "완료된 거", "stage": "done"},
    ]
    result = render_compact_status({"items": items})
    s.check_contains("compact has FF prefix", "[FF]", result)
    s.check_contains("compact has designing", "designing", result)
    s.check_contains("compact has spec", "spec", result)
    # done items should not appear in stage listing
    s.check_not_contains("compact no done stage", "done(", result)


def test_dashboard_render_pipeline(s: Suite) -> None:
    """Test pipeline stage bar rendering."""
    from feature_factory.dashboard import _render_pipeline

    active = [
        {"id": 1, "stage": "designing"},
        {"id": 2, "stage": "designing"},
        {"id": 3, "stage": "spec"},
    ]
    result = _render_pipeline(active)
    s.check_contains("pipeline has designing count", "designing 2/", result)
    s.check_contains("pipeline has spec count", "spec 1/", result)


def test_dashboard_render_recent_events(s: Suite) -> None:
    """Test recent events rendering with temp DB."""
    from feature_factory import db
    from feature_factory.dashboard import _render_recent_events

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # No events
        orig_get = db.get_recent_events
        db.get_recent_events = lambda limit=5, dp=test_db_path: orig_get(limit, dp)

        result = _render_recent_events()
        s.check_contains("no events message", "none", result)

        # Add events
        db.log_event(1, "stage_start", {"stage": "spec"}, test_db_path)
        db.log_event(1, "worker_assign", {"worker_id": 1}, test_db_path)

        result = _render_recent_events()
        s.check_contains("has Recent header", "Recent", result)
        s.check_contains("has stage_start", "stage_start", result)

        db.get_recent_events = orig_get
    finally:
        os.unlink(test_db_path)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    all_results = []

    suites = [
        ("intent_parser", test_intent_parser),
        ("db", test_db),
        ("config", test_config),
        ("report_duration", test_report_format_duration),
        ("report_timestamp", test_report_parse_timestamp),
        ("report_stage_table", test_report_build_stage_table),
        ("report_approval_table", test_report_build_approval_table),
        ("report_generate", test_report_generate),
        ("health_timestamp", test_health_check_parse_timestamp),
        ("health_stalled", test_health_check_stalled_detection),
        ("health_tmux", test_health_check_tmux_session_exists),
        ("recovery_db", test_recovery_db_state),
        ("recovery_timeout", test_recovery_timed_out_approvals),
        # Phase 3
        ("intent_l0_extended", test_intent_parser_l0_extended),
        ("intent_ambiguity", test_intent_parser_ambiguity_detection),
        ("intent_extract_json", test_intent_parser_extract_json),
        ("token_fallback", test_token_gate_fallback),
        ("token_evaluate", test_token_gate_evaluate_budget),
        ("concurrency_config", test_concurrency_config),
        ("dashboard_compact", test_dashboard_render_compact),
        ("dashboard_pipeline", test_dashboard_render_pipeline),
        ("dashboard_events", test_dashboard_render_recent_events),
    ]

    for name, fn in suites:
        results = run_suite(name, fn)
        all_results.extend(results)

    # Print results
    passed = sum(1 for r in all_results if r.result == "PASS")
    failed = sum(1 for r in all_results if r.result == "FAIL")

    for r in all_results:
        icon = "✓" if r.result == "PASS" else "✗"
        line = f"  {icon} [{r.suite}] {r.label}"
        if r.detail:
            line += f"  — {r.detail}"
        print(line)

    print(f"\n{'='*60}")
    print(f"  Total: {len(all_results)}  Passed: {passed}  Failed: {failed}")
    print(f"{'='*60}")

    # Write JSONL
    output_path = Path(__file__).parent.parent.parent / "storage" / "test-results" / "feature-factory.jsonl"
    write_jsonl(all_results, output_path)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
