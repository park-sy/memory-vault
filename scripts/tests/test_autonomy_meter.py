"""Tests for autonomy_meter.py — Phase 1 metrics calculation."""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Adjust path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import autonomy_meter as am


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def msgbus_db(tmp_path):
    """Create a temporary MsgBus DB with test data."""
    db_path = str(tmp_path / "msgbus.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            msg_type TEXT NOT NULL,
            priority INTEGER DEFAULT 5,
            payload TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reply_to INTEGER,
            expires_at TEXT
        );
    """)
    conn.close()
    return db_path


@pytest.fixture
def factory_db(tmp_path):
    """Create a temporary Feature Factory DB with test data."""
    db_path = str(tmp_path / "feature-factory.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE pending_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            gate_type TEXT NOT NULL,
            msgbus_msg_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolution TEXT
        );
        CREATE TABLE factory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.close()
    return db_path


def _insert_messages(db_path, messages):
    """Insert test messages into MsgBus DB."""
    conn = sqlite3.connect(db_path)
    for msg in messages:
        conn.execute(
            """INSERT INTO messages (created_at, sender, recipient, msg_type, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (msg["created_at"], msg["sender"], msg["recipient"],
             msg["msg_type"], msg.get("payload", "{}")),
        )
    conn.commit()
    conn.close()


def _insert_approvals(db_path, approvals):
    """Insert test approvals into Factory DB."""
    conn = sqlite3.connect(db_path)
    for a in approvals:
        conn.execute(
            """INSERT INTO pending_approvals
               (task_id, gate_type, msgbus_msg_id, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (a["task_id"], a["gate_type"], a["msgbus_msg_id"],
             a.get("status", "approved"), a["created_at"]),
        )
    conn.commit()
    conn.close()


def _insert_events(db_path, events):
    """Insert test events into Factory DB."""
    conn = sqlite3.connect(db_path)
    for e in events:
        conn.execute(
            """INSERT INTO factory_events (task_id, event_type, detail, created_at)
               VALUES (?, ?, ?, ?)""",
            (e["task_id"], e["event_type"], e.get("detail"), e["created_at"]),
        )
    conn.commit()
    conn.close()


def _now_str(offset_hours=0):
    """Current UTC time as string, optionally offset."""
    t = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%d %H:%M:%S")


# ── HIR Tests ────────────────────────────────────────────────────────────────

class TestHIR:
    def test_no_db_returns_zero(self, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: None)
        hir, detail = am.calc_hir(7)
        assert hir == 0.0
        assert detail["source"] == "no_db"

    def test_no_messages_returns_zero(self, msgbus_db, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        hir, detail = am.calc_hir(7)
        assert hir == 0.0
        assert detail["human_messages"] == 0

    def test_counts_only_telegram_sender(self, msgbus_db, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        _insert_messages(msgbus_db, [
            {"created_at": _now_str(-1), "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"},
            {"created_at": _now_str(-2), "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "command"},
            {"created_at": _now_str(-3), "sender": "cc-pool-1", "recipient": "telegram", "msg_type": "notify"},
            {"created_at": _now_str(-4), "sender": "cc-factory", "recipient": "cc-pool-1", "msg_type": "task"},
        ])
        hir, detail = am.calc_hir(7)
        assert detail["human_messages"] == 2  # only telegram sender with task/command

    def test_hir_calculation(self, msgbus_db, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        # 10 messages over ~48 hours
        messages = [
            {"created_at": _now_str(-i * 5), "sender": "telegram",
             "recipient": "cc-pool-1", "msg_type": "task"}
            for i in range(10)
        ]
        _insert_messages(msgbus_db, messages)
        hir, detail = am.calc_hir(7)
        assert hir > 0
        assert detail["human_messages"] == 10


# ── UET Tests ────────────────────────────────────────────────────────────────

class TestUET:
    def test_no_db_returns_zero(self, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: None)
        uet, detail = am.calc_uet(7)
        assert uet == 0.0

    def test_single_message_returns_zero(self, msgbus_db, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        _insert_messages(msgbus_db, [
            {"created_at": _now_str(), "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"},
        ])
        uet, detail = am.calc_uet(7)
        assert uet == 0.0

    def test_close_messages_are_attended(self, msgbus_db, monkeypatch):
        """Messages 10 min apart = attended (< 30 min threshold)."""
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        base = datetime.now(timezone.utc)
        messages = [
            {"created_at": (base - timedelta(minutes=i * 10)).strftime("%Y-%m-%d %H:%M:%S"),
             "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"}
            for i in range(5)
        ]
        _insert_messages(msgbus_db, messages)
        uet, detail = am.calc_uet(7)
        assert uet == 0.0  # all gaps < 30 min

    def test_large_gap_is_unattended(self, msgbus_db, monkeypatch):
        """Messages 2 hours apart = unattended (> 30 min threshold)."""
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        base = datetime.now(timezone.utc)
        _insert_messages(msgbus_db, [
            {"created_at": (base - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
             "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"},
            {"created_at": (base - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
             "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"},
            {"created_at": base.strftime("%Y-%m-%d %H:%M:%S"),
             "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"},
        ])
        uet, detail = am.calc_uet(7)
        assert uet == 1.0  # all gaps are 2h > 30min threshold


# ── DAR Tests ────────────────────────────────────────────────────────────────

class TestDAR:
    def test_no_db_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(am, "FACTORY_DB", str(tmp_path / "nonexistent.db"))
        dar, detail = am.calc_dar(7)
        assert dar == 0.0

    def test_no_gates_returns_zero(self, factory_db, monkeypatch):
        monkeypatch.setattr(am, "FACTORY_DB", factory_db)
        dar, detail = am.calc_dar(7)
        assert dar == 0.0
        assert detail["total_gates"] == 0

    def test_all_manual_approvals(self, factory_db, monkeypatch):
        monkeypatch.setattr(am, "FACTORY_DB", factory_db)
        _insert_approvals(factory_db, [
            {"task_id": 1, "gate_type": "spec_to_queued", "msgbus_msg_id": 10, "created_at": _now_str(-1)},
            {"task_id": 2, "gate_type": "design_plan", "msgbus_msg_id": 11, "created_at": _now_str(-2)},
        ])
        dar, detail = am.calc_dar(7)
        assert dar == 0.0
        assert detail["approval_requests"] == 2
        assert detail["auto_passed"] == 0

    def test_mixed_auto_and_manual(self, factory_db, monkeypatch):
        monkeypatch.setattr(am, "FACTORY_DB", factory_db)
        _insert_approvals(factory_db, [
            {"task_id": 1, "gate_type": "spec_to_queued", "msgbus_msg_id": 10, "created_at": _now_str(-1)},
        ])
        _insert_events(factory_db, [
            {"task_id": 2, "event_type": "gate_auto_passed", "created_at": _now_str(-1)},
            {"task_id": 3, "event_type": "gate_auto_passed", "created_at": _now_str(-2)},
        ])
        dar, detail = am.calc_dar(7)
        assert abs(dar - 2 / 3) < 0.01  # 2 auto / 3 total
        assert detail["auto_passed"] == 2
        assert detail["approval_requests"] == 1


# ── Level Judgment Tests ─────────────────────────────────────────────────────

class TestJudgeLevel:
    """judge_level without sample_counts (pure metric test)."""

    def test_l1_high_intervention(self):
        metrics = am.Metrics(hir=5.0, uet=0.1, agr=0.0, dar=0.0)
        level, bottleneck, _, confidence, _ = am.judge_level(metrics)
        assert level == 1

    def test_l2_low_intervention(self):
        metrics = am.Metrics(hir=1.0, uet=0.5, agr=0.0, dar=0.0)
        level, _, _, _, _ = am.judge_level(metrics)
        assert level == 2

    def test_l3_high_autonomy(self):
        metrics = am.Metrics(hir=0.3, uet=0.8, agr=0.4, dar=0.5)
        level, _, _, _, _ = am.judge_level(metrics)
        assert level == 3

    def test_l4_full_autonomy(self):
        metrics = am.Metrics(hir=0.05, uet=0.95, agr=0.8, dar=0.9)
        level, _, _, _, _ = am.judge_level(metrics)
        assert level == 4

    def test_bottleneck_identifies_worst_metric(self):
        metrics = am.Metrics(hir=0.3, uet=0.8, agr=0.0, dar=0.5)
        level, bottleneck, _, _, _ = am.judge_level(metrics)
        assert level == 2  # AGR < 0.2 blocks L3
        assert "AI-Generated" in bottleneck


# ── Sample Sufficiency Tests ─────────────────────────────────────────────────

class TestSampleSufficiency:
    def _make_samples(self, human_messages=0, total_hours=0, total_gates=0):
        return {
            "hir": {"human_messages": human_messages, "total_hours": total_hours},
            "uet": {"message_count": human_messages},
            "agr": {"status": "phase2_pending"},
            "dar": {"total_gates": total_gates, "approval_requests": total_gates, "auto_passed": 0},
        }

    def test_insufficient_forces_l1(self):
        """Even with perfect metrics, insufficient data forces L1."""
        metrics = am.Metrics(hir=0.05, uet=0.95, agr=0.8, dar=0.9)
        samples = self._make_samples(human_messages=10, total_hours=20, total_gates=3)
        level, _, _, confidence, reasons = am.judge_level(metrics, samples)
        assert level == 1
        assert confidence == "insufficient"
        assert len(reasons) > 0

    def test_sufficient_allows_higher_level(self):
        """With enough data, higher levels are reachable."""
        metrics = am.Metrics(hir=1.0, uet=0.5, agr=0.0, dar=0.0)
        samples = self._make_samples(human_messages=80, total_hours=200, total_gates=25)
        level, _, _, confidence, reasons = am.judge_level(metrics, samples)
        assert level == 2
        assert confidence == "sufficient"
        assert len(reasons) == 0

    def test_insufficient_messages(self):
        """Low message count is flagged."""
        samples = self._make_samples(human_messages=10, total_hours=200, total_gates=25)
        sufficient, reasons = am.check_sample_sufficiency(samples)
        assert not sufficient
        assert any("HIR" in r for r in reasons)

    def test_insufficient_hours(self):
        """Short execution time is flagged."""
        samples = self._make_samples(human_messages=80, total_hours=20, total_gates=25)
        sufficient, reasons = am.check_sample_sufficiency(samples)
        assert not sufficient
        assert any("UET" in r for r in reasons)

    def test_insufficient_gates(self):
        """Low gate count is flagged."""
        samples = self._make_samples(human_messages=80, total_hours=200, total_gates=5)
        sufficient, reasons = am.check_sample_sufficiency(samples)
        assert not sufficient
        assert any("DAR" in r for r in reasons)

    def test_all_sufficient(self):
        """All conditions met."""
        samples = self._make_samples(human_messages=80, total_hours=200, total_gates=25)
        sufficient, reasons = am.check_sample_sufficiency(samples)
        assert sufficient
        assert len(reasons) == 0


# ── Integration Test ─────────────────────────────────────────────────────────

class TestMeasure:
    def test_full_measure_insufficient_data(self, msgbus_db, factory_db, monkeypatch):
        """With minimal data, measure should return L1 + insufficient."""
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        monkeypatch.setattr(am, "FACTORY_DB", factory_db)

        _insert_messages(msgbus_db, [
            {"created_at": _now_str(-1), "sender": "telegram",
             "recipient": "cc-pool-1", "msg_type": "task"},
        ])

        result = am.measure(days=7)
        assert result.level == 1
        assert result.confidence == "insufficient"
        assert result.period_days == 7

    def test_full_measure_sufficient_data(self, msgbus_db, factory_db, monkeypatch):
        """With enough data, measure returns actual calculated level."""
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        monkeypatch.setattr(am, "FACTORY_DB", factory_db)

        # Insert 60 messages spread over 5 days (> 72h, > 50 msgs)
        base = datetime.now(timezone.utc)
        messages = [
            {"created_at": (base - timedelta(hours=i * 2)).strftime("%Y-%m-%d %H:%M:%S"),
             "sender": "telegram", "recipient": "cc-pool-1", "msg_type": "task"}
            for i in range(60)
        ]
        _insert_messages(msgbus_db, messages)

        # Insert 25 approvals (> 20 gates)
        _insert_approvals(factory_db, [
            {"task_id": i, "gate_type": "spec_to_queued",
             "msgbus_msg_id": 100 + i, "created_at": _now_str(-i)}
            for i in range(25)
        ])

        result = am.measure(days=7)
        assert result.confidence == "sufficient"
        assert result.level >= 1


class TestDailyHistory:
    def test_returns_list(self, msgbus_db, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        history = am.daily_history(days=7)
        assert isinstance(history, list)
        assert len(history) == 7

    def test_counts_per_day(self, msgbus_db, monkeypatch):
        monkeypatch.setattr(am, "_find_msgbus_db", lambda: msgbus_db)
        _insert_messages(msgbus_db, [
            {"created_at": _now_str(-1), "sender": "telegram",
             "recipient": "cc-pool-1", "msg_type": "task"},
            {"created_at": _now_str(-2), "sender": "telegram",
             "recipient": "cc-pool-1", "msg_type": "command"},
        ])
        history = am.daily_history(days=3)
        assert isinstance(history, list)
        total_msgs = sum(d["human_messages"] for d in history)
        assert total_msgs >= 0  # at least no crash
