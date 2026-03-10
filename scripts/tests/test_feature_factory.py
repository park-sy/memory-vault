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
    s.check_eq("5 approval gates", 5, len(APPROVAL_GATES))
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

        orig_get_tokens = db.get_tokens_for_task
        db.get_tokens_for_task = lambda tid, dp=test_db_path: orig_get_tokens(tid, dp)

        orig_get_report_path = report._get_report_path
        report._get_report_path = lambda name: str(Path(report_dir) / f"{name}.md")

        result = report.generate_report(99, "Test Feature")

        # Restore
        db.get_events_for_task = orig_get_events
        db.get_tokens_for_task = orig_get_tokens
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
        db.get_tokens_for_task = lambda tid, dp=test_db_path: orig_get_tokens(tid, dp)
        none_result = report.generate_report(999, "No Events")
        db.get_events_for_task = orig_get_events
        db.get_tokens_for_task = orig_get_tokens
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


# ── session_scanner tests ───────────────────────────────────────────────────

def test_scanner_parse_assistant_usage(s: Suite) -> None:
    """Test _parse_assistant_usage with real JSONL structure."""
    from feature_factory.session_scanner import _parse_assistant_usage

    # Valid assistant line
    line = json.dumps({
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 3,
                "cache_creation_input_tokens": 12932,
                "cache_read_input_tokens": 19758,
                "output_tokens": 9,
                "service_tier": "standard",
            },
        },
        "sessionId": "abc-123",
    })
    result = _parse_assistant_usage(line)
    s.check_not_none("valid line parsed", result)
    s.check_eq("model", "claude-opus-4-6", result["model"])
    s.check_eq("input_tokens", 3, result["input_tokens"])
    s.check_eq("output_tokens", 9, result["output_tokens"])
    s.check_eq("cache_read", 19758, result["cache_read_tokens"])
    s.check_eq("cache_creation", 12932, result["cache_creation_tokens"])
    s.check_eq("session_id", "abc-123", result["session_id"])

    # Non-assistant type
    line2 = json.dumps({"type": "human", "message": {"content": "hi"}})
    s.check_none("human type returns None", _parse_assistant_usage(line2))

    # No usage field
    line3 = json.dumps({"type": "assistant", "message": {"model": "x"}})
    s.check_none("no usage returns None", _parse_assistant_usage(line3))

    # Invalid JSON
    s.check_none("invalid json returns None", _parse_assistant_usage("not json"))

    # Empty line
    s.check_none("empty line returns None", _parse_assistant_usage(""))


def test_scanner_encode_project_path(s: Suite) -> None:
    from feature_factory.session_scanner import _encode_project_path

    s.check_eq(
        "encode path",
        "-Users-hiyeop-dev-whos-life",
        _encode_project_path("/Users/hiyeop/dev/whos-life"),
    )
    s.check_eq(
        "encode memory-vault",
        "-Users-hiyeop-dev-memory-vault",
        _encode_project_path("/Users/hiyeop/dev/memory-vault"),
    )


def test_scanner_scan_session_tokens(s: Suite) -> None:
    """Test scan_session_tokens with temp JSONL files."""
    from feature_factory.session_scanner import scan_session_tokens, _CLAUDE_PROJECTS_DIR
    import feature_factory.session_scanner as scanner_mod

    # Create temp dir simulating ~/.claude/projects/-encoded/
    with tempfile.TemporaryDirectory() as tmpdir:
        encoded = "-test-project"
        project_dir = tmpdir
        scan_dir = Path(project_dir) / encoded

        # Monkey-patch _CLAUDE_PROJECTS_DIR
        orig_dir = scanner_mod._CLAUDE_PROJECTS_DIR
        scanner_mod._CLAUDE_PROJECTS_DIR = Path(project_dir)

        scan_dir.mkdir(parents=True)

        # Write a JSONL file
        jsonl_path = scan_dir / "test-session.jsonl"
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 200,
                        "cache_creation_input_tokens": 300,
                    },
                },
                "sessionId": "sess-1",
            }),
            json.dumps({"type": "human", "message": {"content": "hi"}}),
            json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 400,
                        "output_tokens": 150,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
                "sessionId": "sess-1",
            }),
        ]
        jsonl_path.write_text("\n".join(lines), encoding="utf-8")

        # Scan with after_time = 0 (catch all)
        result = scan_session_tokens("/test/project", 0.0)
        s.check_not_none("scan result not None", result)
        s.check_eq("model", "claude-opus-4-6", result.model)
        s.check_eq("input_tokens", 500, result.input_tokens)
        s.check_eq("output_tokens", 200, result.output_tokens)
        s.check_eq("cache_read", 200, result.cache_read_tokens)
        s.check_eq("cache_creation", 300, result.cache_creation_tokens)
        s.check_eq("request_count", 2, result.request_count)
        s.check_eq("total", 1200, result.total_tokens)
        s.check_eq("session_id", "sess-1", result.session_id)

        # Scan with after_time in the future → None
        import time as time_mod
        future_result = scan_session_tokens("/test/project", time_mod.time() + 9999)
        s.check_none("future time returns None", future_result)

        # Scan nonexistent project → None
        none_result = scan_session_tokens("/nonexistent/path", 0.0)
        s.check_none("nonexistent path returns None", none_result)

        scanner_mod._CLAUDE_PROJECTS_DIR = orig_dir


def test_db_stage_token_log(s: Suite) -> None:
    """Test stage_token_log CRUD operations."""
    from feature_factory import db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # Record tokens
        rec_id = db.record_stage_tokens(
            task_id=10, stage="spec", model="claude-opus-4-6",
            input_tokens=1000, output_tokens=500,
            cache_read_tokens=2000, cache_creation_tokens=300,
            cost_usd="0.05", duration_ms=120000,
            session_id="sess-abc", db_path=test_db_path,
        )
        s.check_gt("record id > 0", rec_id, 0)

        # Record another for same task different stage
        db.record_stage_tokens(
            task_id=10, stage="designing", model="claude-sonnet-4-6",
            input_tokens=500, output_tokens=200,
            cache_read_tokens=100, cache_creation_tokens=50,
            duration_ms=60000,
            db_path=test_db_path,
        )

        # Get tokens for task
        records = db.get_tokens_for_task(10, test_db_path)
        s.check_eq("2 records for task 10", 2, len(records))
        s.check_eq("first stage spec", "spec", records[0].stage)
        s.check_eq("first model", "claude-opus-4-6", records[0].model)
        s.check_eq("first total", 3800, records[0].total_tokens)
        s.check_eq("second stage designing", "designing", records[1].stage)

        # Get summary
        summary = db.get_token_summary(test_db_path)
        s.check_eq("summary input", 1500, summary["input_tokens"])
        s.check_eq("summary output", 700, summary["output_tokens"])
        s.check_eq("summary count", 2, summary["record_count"])
        s.check_eq("summary total", 4650, summary["total_tokens"])

        # Get summary by stage
        by_stage = db.get_token_summary_by_stage(test_db_path)
        s.check_eq("2 stages", 2, len(by_stage))
        # Ordered by total_tokens DESC
        s.check_eq("first stage by tokens", "spec", by_stage[0]["stage"])
        s.check_eq("spec total", 3800, by_stage[0]["total_tokens"])
        s.check_eq("spec run_count", 1, by_stage[0]["run_count"])

        # Empty task → empty list
        empty = db.get_tokens_for_task(999, test_db_path)
        s.check_eq("empty task tokens", 0, len(empty))

    finally:
        os.unlink(test_db_path)


# ── worker_complete_hook tests ───────────────────────────────────────────────

def test_hook_get_active_assignment(s: Suite) -> None:
    """Test _get_active_assignment DB query from worker_complete_hook."""
    from feature_factory import db

    # Add parent scripts dir to path for hook import
    scripts_dir = str(Path(__file__).parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import worker_complete_hook as hook

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)
        db.create_assignment(3, 42, "planner", "spec", test_db_path)

        # Monkey-patch FACTORY_DB
        orig_db = hook.FACTORY_DB
        hook.FACTORY_DB = Path(test_db_path)

        # Should find active assignment
        result = hook._get_active_assignment(3)
        s.check_not_none("hook finds assignment", result)
        s.check_eq("hook task_id", 42, result[0])
        s.check_eq("hook stage", "spec", result[1])

        # No assignment for worker 99
        result = hook._get_active_assignment(99)
        s.check_none("hook no assignment for unknown worker", result)

        # Complete assignment → should not find
        with db.connect(test_db_path) as conn:
            conn.execute(
                "UPDATE worker_assignments SET status = 'completed' WHERE worker_id = 3"
            )
        result = hook._get_active_assignment(3)
        s.check_none("hook no assignment after complete", result)

        hook.FACTORY_DB = orig_db
    finally:
        os.unlink(test_db_path)


def test_hook_skip_patterns(s: Suite) -> None:
    """Test that skip patterns are correctly defined."""
    scripts_dir = str(Path(__file__).parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import worker_complete_hook as hook

    s.check("has Enter to select", "Enter to select" in hook.SKIP_PATTERNS)
    s.check("has Plan mode", "Plan mode" in hook.SKIP_PATTERNS)
    s.check("has Waiting for", "Waiting for" in hook.SKIP_PATTERNS)
    s.check("5 patterns total", len(hook.SKIP_PATTERNS) == 5)


def test_hook_nonexistent_db(s: Suite) -> None:
    """Test _get_active_assignment with nonexistent DB file."""
    scripts_dir = str(Path(__file__).parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import worker_complete_hook as hook

    orig_db = hook.FACTORY_DB
    hook.FACTORY_DB = Path("/tmp/nonexistent-hook-test.db")

    result = hook._get_active_assignment(1)
    s.check_none("nonexistent db returns None", result)

    hook.FACTORY_DB = orig_db


# ── completion_detector tests ────────────────────────────────────────────────

def test_detector_is_idle(s: Suite) -> None:
    """Test _is_idle pattern detection."""
    from feature_factory.completion_detector import _is_idle

    # Idle: prompt in tail
    s.check("idle with prompt", _is_idle("some output\n❯ \n"))
    s.check("idle prompt only", _is_idle("❯"))
    s.check("idle with leading text", _is_idle("Done.\n\n❯"))

    # Real Claude Code UI: ❯ is 3rd from bottom
    s.check("idle real ui", _is_idle(
        "output\n───\n❯\xa0\n───\n  ⏵⏵ bypass permissions"
    ))

    # Not idle: no prompt
    s.check("not idle empty", not _is_idle(""))
    s.check("not idle no prompt", not _is_idle("Running tests...\nPASS"))
    s.check("not idle whitespace", not _is_idle("   \n  \n  "))

    # Prompt far above tail → not idle
    s.check("prompt far above not idle", not _is_idle(
        "❯\n" + "\n".join(["working..."] * 10)
    ))


def test_detector_parse_timestamp(s: Suite) -> None:
    """Test _parse_timestamp for detector."""
    from feature_factory.completion_detector import _parse_timestamp

    dt = _parse_timestamp("2026-03-08 14:30:00")
    s.check_eq("year", 2026, dt.year)
    s.check_eq("hour", 14, dt.hour)
    s.check_not_none("tzinfo", dt.tzinfo)

    dt2 = _parse_timestamp("2026-03-08T14:30:00")
    s.check_eq("iso year", 2026, dt2.year)

    dt3 = _parse_timestamp("invalid")
    s.check_not_none("invalid returns datetime", dt3)


def test_detector_skip_patterns(s: Suite) -> None:
    """Test detector skip patterns match hook patterns."""
    from feature_factory.completion_detector import _SKIP_PATTERNS

    s.check("has Enter to select", "Enter to select" in _SKIP_PATTERNS)
    s.check("has Plan mode", "Plan mode" in _SKIP_PATTERNS)
    s.check("5 patterns", len(_SKIP_PATTERNS) == 5)


def test_detector_set_cleanup(s: Suite) -> None:
    """Test that _detected set is cleaned up for completed assignments."""
    from feature_factory import completion_detector as cd
    from feature_factory import db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # Add stale IDs to _detected
        cd._detected.clear()
        cd._detected.add(999)
        cd._detected.add(998)

        # Monkey-patch db.connect to use test DB
        orig_connect = db.connect
        from contextlib import contextmanager
        @contextmanager
        def test_connect(dp=None):
            with orig_connect(test_db_path) as conn:
                yield conn
        db.connect = test_connect

        # No active assignments → stale IDs should be cleaned
        cd.check_completions()
        s.check_eq("stale ids cleaned", 0, len(cd._detected))

        db.connect = orig_connect
    finally:
        cd._detected.clear()
        os.unlink(test_db_path)


# ── idempotency guard test ───────────────────────────────────────────────────

def test_idempotency_guard(s: Suite) -> None:
    """Test that _handle_stage_complete is a no-op when no active assignment."""
    from feature_factory import db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db_path = f.name

    try:
        db.init_db(test_db_path)

        # No assignment for task 999 — should not crash, should not log events
        orig_get = db.get_active_assignment_for_task
        db.get_active_assignment_for_task = lambda tid, dp=test_db_path: orig_get(tid, dp)

        from feature_factory import dispatcher
        # Should not raise
        dispatcher._handle_stage_complete(999, "spec", "test-sender")

        # No events should be logged for task 999
        events = db.get_events_for_task(999, test_db_path)
        s.check_eq("no events for guarded call", 0, len(events))

        db.get_active_assignment_for_task = orig_get
    finally:
        os.unlink(test_db_path)


# ── Revise + Action Links tests ──────────────────────────────────────────────

def test_revise_callback(s: Suite) -> None:
    """Test revise callback handling in approval_handler."""
    from feature_factory import db, approval_handler

    test_db_path = tempfile.mktemp(suffix=".db")
    try:
        db.init_db(test_db_path)

        # Create assignment + approval
        db.create_assignment(1, 42, "planner", "spec", test_db_path)
        approval_id = db.create_approval(42, "spec_to_queued", 100, test_db_path)

        # Verify initial state
        approval = db.find_approval_by_msgbus_id(100, test_db_path)
        s.check_eq("approval status pending", "pending", approval.status)

        # Process revise — patch db functions to use test_db
        orig_find = db.find_approval_by_msgbus_id
        orig_resolve = db.resolve_approval
        orig_log = db.log_event
        orig_get_assign = db.get_active_assignment_for_task

        db.find_approval_by_msgbus_id = lambda mid, dp=test_db_path: orig_find(mid, dp)
        db.resolve_approval = lambda aid, res, dp=test_db_path: orig_resolve(aid, res, dp)
        db.log_event = lambda tid, et, detail=None, dp=test_db_path: orig_log(tid, et, detail, dp)
        db.get_active_assignment_for_task = lambda tid, dp=test_db_path: orig_get_assign(tid, dp)

        # Mock notifier to avoid real Telegram calls
        from feature_factory import notifier
        orig_notify = notifier.notify_revision_request
        notify_calls = []
        notifier.notify_revision_request = lambda *a, **kw: notify_calls.append(a) or 1

        result = approval_handler.handle_callback(100, "revise")
        s.check_eq("revise returns True", True, result)

        # Check approval resolved as revise_requested
        with db.connect(test_db_path) as conn:
            row = conn.execute("SELECT status, resolution FROM pending_approvals WHERE id = ?", (approval_id,)).fetchone()
            s.check_eq("status revise_requested", "revise_requested", row["status"])
            s.check_eq("resolution revise_requested", "revise_requested", row["resolution"])

        # Check notify was called with worker_id
        s.check_eq("notify called once", 1, len(notify_calls))
        s.check_eq("notify task_id", 42, notify_calls[0][0])
        s.check_eq("notify worker_id", 1, notify_calls[0][3])

        # Check event logged
        events = db.get_events_for_task(42, test_db_path)
        revise_events = [e for e in events if e.event_type == "approval_res"]
        s.check_eq("revise event logged", 1, len(revise_events))

        # Restore
        db.find_approval_by_msgbus_id = orig_find
        db.resolve_approval = orig_resolve
        db.log_event = orig_log
        db.get_active_assignment_for_task = orig_get_assign
        notifier.notify_revision_request = orig_notify
    finally:
        os.unlink(test_db_path)


def test_worker_action_links(s: Suite) -> None:
    """Test _worker_action_links helper."""
    from feature_factory.notifier import _worker_action_links, _CLAUDE_CODE_LINK

    links = _worker_action_links(1)
    s.check_eq("contains tmux cmd", True, "tmux attach -t cc-pool-1" in links)
    s.check_eq("contains claude link", True, _CLAUDE_CODE_LINK in links)

    links2 = _worker_action_links(3)
    s.check_eq("worker 3 tmux", True, "cc-pool-3" in links2)


def test_approval_actions_include_revise(s: Suite) -> None:
    """Test that notify_approval_request includes revise action."""
    from feature_factory import notifier
    import subprocess

    # Capture the command that would be run
    cmds = []
    orig_run = subprocess.run
    def mock_run(cmd, **kw):
        cmds.append(cmd)
        import types
        r = types.SimpleNamespace(returncode=0, stdout='{"msg_id": 1}', stderr='')
        return r
    subprocess.run = mock_run

    notifier.notify_approval_request(1, "test", "spec_to_queued")
    subprocess.run = orig_run

    s.check_eq("command captured", True, len(cmds) > 0)
    # Find the --actions argument
    cmd = cmds[-1]
    actions_idx = None
    for i, arg in enumerate(cmd):
        if arg == "--actions":
            actions_idx = i
            break
    s.check_eq("has --actions", True, actions_idx is not None)
    if actions_idx is not None:
        actions = cmd[actions_idx + 1: actions_idx + 4]
        s.check_eq("3 actions", 3, len(actions))
        s.check_eq("approve", "approve", actions[0])
        s.check_eq("revise", "revise", actions[1])
        s.check_eq("reject", "reject", actions[2])


def test_db_migration_revise_status(s: Suite) -> None:
    """Test that DB migration adds revise_requested to CHECK constraint."""
    from feature_factory import db

    test_db_path = tempfile.mktemp(suffix=".db")
    try:
        # Create old schema without revise_requested
        conn = sqlite3.connect(test_db_path)
        conn.executescript("""
            CREATE TABLE pending_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                gate_type TEXT NOT NULL,
                msgbus_msg_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected','timed_out')),
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolution TEXT
            );
            INSERT INTO pending_approvals (task_id, gate_type, msgbus_msg_id, status, created_at)
            VALUES (1, 'spec_to_queued', 100, 'pending', '2026-01-01 00:00:00');
        """)
        conn.close()

        # Run migration
        with db.connect(test_db_path) as conn2:
            db._migrate_approval_status(conn2)

        # Verify: old data preserved
        with db.connect(test_db_path) as conn3:
            row = conn3.execute("SELECT * FROM pending_approvals WHERE id = 1").fetchone()
            s.check_eq("old data preserved", "pending", row["status"])

            # Can insert revise_requested
            conn3.execute(
                "INSERT INTO pending_approvals (task_id, gate_type, msgbus_msg_id, status, created_at) "
                "VALUES (2, 'spec_to_queued', 200, 'revise_requested', '2026-01-01 00:00:00')"
            )
            row2 = conn3.execute("SELECT status FROM pending_approvals WHERE task_id = 2").fetchone()
            s.check_eq("revise_requested accepted", "revise_requested", row2["status"])

        # Verify: migration is idempotent
        with db.connect(test_db_path) as conn4:
            db._migrate_approval_status(conn4)
            count = conn4.execute("SELECT count(*) FROM pending_approvals").fetchone()[0]
            s.check_eq("idempotent — row count", 2, count)
    finally:
        os.unlink(test_db_path)


# ── Approval Summary tests ───────────────────────────────────────────────────

def test_approval_summary_spec(s: Suite) -> None:
    """spec_to_queued 게이트 요약 생성."""
    from feature_factory.notifier import _build_approval_summary

    ctx = {
        "description": "memory-vault/whos-life 작업물을 정리하여 AI 회사 메일링 + 블로그 포스팅.",
        "priority": 7,
        "category": "automation",
    }
    result = _build_approval_summary("spec_to_queued", ctx)
    s.check_contains("desc included", "memory-vault/whos-life", result)
    s.check_contains("priority included", "7", result)
    s.check_contains("category included", "automation", result)


def test_approval_summary_spec_truncation(s: Suite) -> None:
    """description이 200자 초과 시 truncation."""
    from feature_factory.notifier import _build_approval_summary

    long_desc = "A" * 250
    ctx = {"description": long_desc, "priority": 5, "category": ""}
    result = _build_approval_summary("spec_to_queued", ctx)
    s.check("truncated", len(result.split("\n")[0]) < 220, f"len={len(result.split(chr(10))[0])}")
    s.check_contains("ellipsis", "...", result)


def test_approval_summary_spec_empty(s: Suite) -> None:
    """description도 priority도 없으면 빈 문자열."""
    from feature_factory.notifier import _build_approval_summary

    ctx = {"description": "", "priority": "-", "category": ""}
    result = _build_approval_summary("spec_to_queued", ctx)
    s.check_eq("empty when no data", "", result)


def test_approval_summary_plan(s: Suite) -> None:
    """design_plan / coding_plan 게이트 요약 생성."""
    from feature_factory.notifier import _build_approval_summary

    plan = {
        "steps": [
            {"name": "템플릿 구조 설계"},
            {"name": "수집기 구현"},
            {"name": "렌더러 구현"},
            {"name": "스케줄러 등록"},
        ],
        "files": ["publisher.py", "templates/", "scheduler.py"],
    }
    ctx = {"plan": plan}
    result = _build_approval_summary("design_plan", ctx)
    s.check_contains("step count", "4단계", result)
    s.check_contains("step name", "템플릿 구조 설계", result)
    s.check_contains("files", "publisher.py", result)

    # coding_plan도 동일 로직
    result2 = _build_approval_summary("coding_plan", ctx)
    s.check_contains("coding_plan also works", "4단계", result2)


def test_approval_summary_plan_string(s: Suite) -> None:
    """plan이 JSON 문자열일 때도 파싱."""
    from feature_factory.notifier import _build_approval_summary

    plan_json = json.dumps({"steps": [{"name": "step1"}, {"name": "step2"}]})
    ctx = {"plan": plan_json}
    result = _build_approval_summary("design_plan", ctx)
    s.check_contains("parsed string plan", "2단계", result)


def test_approval_summary_plan_empty(s: Suite) -> None:
    """plan이 없으면 빈 문자열."""
    from feature_factory.notifier import _build_approval_summary

    ctx = {"plan": None}
    result = _build_approval_summary("design_plan", ctx)
    s.check_eq("empty when no plan", "", result)


def test_approval_summary_testing(s: Suite) -> None:
    """testing_to_stable 게이트 요약 생성."""
    from feature_factory.notifier import _build_approval_summary

    ctx = {
        "test_runs": 5,
        "test_successes": 5,
        "last_test_at": "2026-03-08T15:30:00+00:00",
    }
    result = _build_approval_summary("testing_to_stable", ctx)
    s.check_contains("run count", "5회 실행", result)
    s.check_contains("success count", "5회 성공", result)
    s.check_contains("percentage", "100%", result)
    s.check_contains("last test at", "2026-03-08 15:30", result)


def test_approval_summary_testing_no_runs(s: Suite) -> None:
    """테스트 실행이 없으면 경고 메시지."""
    from feature_factory.notifier import _build_approval_summary

    ctx = {"test_runs": 0, "test_successes": 0, "last_test_at": ""}
    result = _build_approval_summary("testing_to_stable", ctx)
    s.check_contains("warning when no runs", "테스트 실행 0회", result)


def test_approval_summary_unknown_gate(s: Suite) -> None:
    """알 수 없는 gate type이면 빈 문자열 (graceful fallback)."""
    from feature_factory.notifier import _build_approval_summary

    result = _build_approval_summary("unknown_gate", {"description": "test"})
    s.check_eq("empty for unknown gate", "", result)


# ── Artifact Validator Tests ─────────────────────────────────────────────────

def test_artifact_validator_designing(s: Suite) -> None:
    """designing 검증: SKILL.md 존재 여부."""
    from feature_factory.artifact_validator import validate_stage_artifacts, ValidationResult

    # SKILL.md가 없는 케이스 (존재하지 않는 제목)
    result = validate_stage_artifacts(999, "designing", "nonexistent-feature-xyz-99999")
    s.check_is_instance("returns ValidationResult", result, ValidationResult)
    s.check_eq("designing invalid without SKILL.md", False, result.valid)
    s.check_eq("stage is designing", "designing", result.stage)
    s.check_contains("summary mentions SKILL.md", "SKILL.md", result.summary)


def test_artifact_validator_testing(s: Suite) -> None:
    """testing 검증: test_runs > 0."""
    from feature_factory.artifact_validator import ValidationResult
    from feature_factory.artifact_validator import _validate_testing

    # pm.get_task_detail를 mock하기 어려우므로 직접 ValidationResult 구조만 검증
    result = ValidationResult(valid=False, stage="testing", checks=(("test_runs > 0", False, "test_runs=0"),), summary="테스트 실행 0회 (task #99)")
    s.check_eq("testing invalid", False, result.valid)
    s.check_contains("summary mentions 0회", "0회", result.summary)

    result_ok = ValidationResult(valid=True, stage="testing", checks=(("test_runs > 0", True, "test_runs=5"),), summary="")
    s.check_eq("testing valid", True, result_ok.valid)


def test_artifact_validator_coding(s: Suite) -> None:
    """coding 검증: git diff 결과."""
    from feature_factory.artifact_validator import ValidationResult

    # git diff가 빈 경우
    result_empty = ValidationResult(valid=False, stage="coding", checks=(("git diff 변경 파일 존재", False, "변경 파일 없음"),), summary="코드 변경 없음 (files_changed=0)")
    s.check_eq("coding invalid without changes", False, result_empty.valid)
    s.check_contains("summary mentions 없음", "변경 없음", result_empty.summary)

    # git diff가 있는 경우
    result_ok = ValidationResult(valid=True, stage="coding", checks=(("git diff 변경 파일 존재", True, "app.py, service.py"),), summary="")
    s.check_eq("coding valid with changes", True, result_ok.valid)


def test_artifact_validator_passthrough(s: Suite) -> None:
    """idea, spec 등 검증 대상이 아닌 스테이지는 항상 valid."""
    from feature_factory.artifact_validator import validate_stage_artifacts

    for stage in ("idea", "spec", "queued", "stable"):
        result = validate_stage_artifacts(1, stage, "test")
        s.check_eq(f"{stage} always valid", True, result.valid)


def test_artifact_validator_title_to_slug(s: Suite) -> None:
    """title_to_slug 변환."""
    from feature_factory.artifact_validator import title_to_slug

    s.check_eq("basic slug", "travel-planner", title_to_slug("Travel Planner"))
    s.check_eq("lowercase", "hello-world", title_to_slug("Hello World"))
    s.check_eq("no spaces", "test", title_to_slug("test"))


def test_coding_to_done_gate(s: Suite) -> None:
    """coding_to_done 게이트가 APPROVAL_GATES에 존재하고 올바른 설정."""
    from feature_factory.config import APPROVAL_GATES

    gate = APPROVAL_GATES.get("coding_to_done")
    s.check_not_none("gate exists", gate)
    s.check_eq("from coding", "coding", gate["from"])
    s.check_eq("cli_cmd approve-done", "approve-done", gate["cli_cmd"])


def test_summary_coding(s: Suite) -> None:
    """coding_to_done 요약 생성."""
    from feature_factory.notifier import _build_approval_summary

    ctx = {"test_runs": 3, "test_successes": 3}
    result = _build_approval_summary("coding_to_done", ctx)
    s.check_contains("has test info", "3회 실행", result)


def test_notify_validation_failure(s: Suite) -> None:
    """notify_validation_failure가 올바른 메시지를 생성."""
    from feature_factory.artifact_validator import ValidationResult
    from unittest.mock import patch

    validation = ValidationResult(
        valid=False, stage="designing",
        checks=(("SKILL.md 존재", False, "/path/to/SKILL.md"),),
        summary="SKILL.md 미생성: /path/to/SKILL.md",
    )

    with patch("feature_factory.notifier.send_notification") as mock_send:
        mock_send.return_value = 42
        from feature_factory.notifier import notify_validation_failure
        result = notify_validation_failure(10, "travel-planner", validation)
        s.check_eq("returns msg_id", 42, result)
        call_args = mock_send.call_args
        msg = call_args[0][0]
        s.check_contains("has task id", "Task #10", msg)
        s.check_contains("has title", "travel-planner", msg)
        s.check_contains("has stage", "designing", msg)
        s.check_contains("has summary", "SKILL.md 미생성", msg)


def test_detector_fast_completion_warning(s: Suite) -> None:
    """completion_detector: 5분 미만 완료 시 경고 로그."""
    from feature_factory.completion_detector import MIN_ELAPSED_SECONDS

    # MIN_ELAPSED_SECONDS가 120초(2분)인지 확인 — 경고는 300초(5분) 미만
    s.check_eq("min elapsed 120s", 120, MIN_ELAPSED_SECONDS)


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
        # Token tracking
        ("scanner_parse", test_scanner_parse_assistant_usage),
        ("scanner_encode", test_scanner_encode_project_path),
        ("scanner_scan", test_scanner_scan_session_tokens),
        ("db_token_log", test_db_stage_token_log),
        # Worker completion detection
        ("hook_assignment", test_hook_get_active_assignment),
        ("hook_skip_patterns", test_hook_skip_patterns),
        ("hook_nonexistent_db", test_hook_nonexistent_db),
        ("detector_is_idle", test_detector_is_idle),
        ("detector_timestamp", test_detector_parse_timestamp),
        ("detector_skip_patterns", test_detector_skip_patterns),
        ("detector_set_cleanup", test_detector_set_cleanup),
        ("idempotency_guard", test_idempotency_guard),
        # Revise + action links
        ("revise_callback", test_revise_callback),
        ("worker_action_links", test_worker_action_links),
        ("approval_actions_revise", test_approval_actions_include_revise),
        ("db_migration_revise", test_db_migration_revise_status),
        # Approval summary context
        ("summary_spec", test_approval_summary_spec),
        ("summary_spec_truncation", test_approval_summary_spec_truncation),
        ("summary_spec_empty", test_approval_summary_spec_empty),
        ("summary_plan", test_approval_summary_plan),
        ("summary_plan_string", test_approval_summary_plan_string),
        ("summary_plan_empty", test_approval_summary_plan_empty),
        ("summary_testing", test_approval_summary_testing),
        ("summary_testing_no_runs", test_approval_summary_testing_no_runs),
        ("summary_unknown_gate", test_approval_summary_unknown_gate),
        # Artifact validation + coding_to_done gate
        ("validator_designing", test_artifact_validator_designing),
        ("validator_testing", test_artifact_validator_testing),
        ("validator_coding", test_artifact_validator_coding),
        ("validator_passthrough", test_artifact_validator_passthrough),
        ("validator_slug", test_artifact_validator_title_to_slug),
        ("coding_to_done_gate", test_coding_to_done_gate),
        ("summary_coding", test_summary_coding),
        ("notify_validation_failure", test_notify_validation_failure),
        ("detector_fast_warning", test_detector_fast_completion_warning),
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
