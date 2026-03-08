"""Tests for ai_boss.db — DB CRUD 연산."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_boss import db


@pytest.fixture
def tmp_db():
    """임시 DB 파일로 테스트."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(path)
    yield path
    os.unlink(path)


# ── Config ───────────────────────────────────────────────────────────────────


class TestConfig:

    def test_seed_config(self, tmp_db):
        val = db.get_config("morning_checkin_time", tmp_db)
        assert val == "09:00"

    def test_set_and_get(self, tmp_db):
        db.set_config("test_key", "test_value", tmp_db)
        assert db.get_config("test_key", tmp_db) == "test_value"

    def test_upsert(self, tmp_db):
        db.set_config("morning_checkin_time", "10:00", tmp_db)
        assert db.get_config("morning_checkin_time", tmp_db) == "10:00"

    def test_get_all_config(self, tmp_db):
        config = db.get_all_config(tmp_db)
        assert "checkin_enabled" in config
        assert "active_bosses" in config

    def test_get_active_bosses(self, tmp_db):
        bosses = db.get_active_bosses(tmp_db)
        assert "jinsu" in bosses
        assert len(bosses) == 3

    def test_missing_key_returns_none(self, tmp_db):
        assert db.get_config("nonexistent", tmp_db) is None


# ── Tasks ────────────────────────────────────────────────────────────────────


class TestTasks:

    def test_create_and_get(self, tmp_db):
        task_id = db.create_task("Test task", "daily", db_path=tmp_db)
        task = db.get_task(task_id, tmp_db)
        assert task is not None
        assert task.title == "Test task"
        assert task.horizon == "daily"
        assert task.status == "active"

    def test_create_with_options(self, tmp_db):
        task_id = db.create_task(
            "Important task", "weekly",
            priority=2, proposed_by="jinsu", due_date="2026-03-15",
            db_path=tmp_db,
        )
        task = db.get_task(task_id, tmp_db)
        assert task.priority == 2
        assert task.proposed_by == "jinsu"
        assert task.due_date == "2026-03-15"

    def test_get_active_tasks(self, tmp_db):
        db.create_task("Task A", "daily", priority=3, db_path=tmp_db)
        db.create_task("Task B", "daily", priority=1, db_path=tmp_db)
        tasks = db.get_active_tasks(tmp_db)
        assert len(tasks) == 2
        assert tasks[0].priority <= tasks[1].priority  # priority ASC

    def test_update_status(self, tmp_db):
        task_id = db.create_task("Task", "daily", db_path=tmp_db)
        db.update_task_status(task_id, "completed", tmp_db)
        task = db.get_task(task_id, tmp_db)
        assert task.status == "completed"
        assert task.completed_at is not None

    def test_block_task(self, tmp_db):
        task_id = db.create_task("Task", "daily", db_path=tmp_db)
        db.block_task(task_id, "API 장애", tmp_db)
        task = db.get_task(task_id, tmp_db)
        assert task.status == "blocked"
        assert task.blocked_reason == "API 장애"

    def test_get_tasks_by_horizon(self, tmp_db):
        db.create_task("Daily", "daily", db_path=tmp_db)
        db.create_task("Weekly", "weekly", db_path=tmp_db)
        daily = db.get_tasks_by_horizon("daily", tmp_db)
        assert len(daily) == 1
        assert daily[0].title == "Daily"


# ── Feedback ─────────────────────────────────────────────────────────────────


class TestFeedback:

    def test_add_and_get(self, tmp_db):
        fb_id = db.add_feedback("jinsu", "잘하고 있어", db_path=tmp_db)
        recent = db.get_recent_feedback(10, tmp_db)
        assert len(recent) == 1
        assert recent[0].boss == "jinsu"
        assert recent[0].content == "잘하고 있어"

    def test_feedback_with_task(self, tmp_db):
        task_id = db.create_task("Task", "daily", db_path=tmp_db)
        db.add_feedback("miyoung", "화이팅!", task_id=task_id, db_path=tmp_db)
        recent = db.get_recent_feedback(10, tmp_db)
        assert recent[0].task_id == task_id

    def test_get_by_boss(self, tmp_db):
        db.add_feedback("jinsu", "msg1", db_path=tmp_db)
        db.add_feedback("miyoung", "msg2", db_path=tmp_db)
        jinsu_fb = db.get_feedback_by_boss("jinsu", 10, tmp_db)
        assert len(jinsu_fb) == 1
        assert jinsu_fb[0].boss == "jinsu"


# ── Checkin Log ──────────────────────────────────────────────────────────────


class TestCheckinLog:

    def test_log_and_get(self, tmp_db):
        cid = db.log_checkin("morning", ["jinsu"], tokens_used=1500, db_path=tmp_db)
        recent = db.get_recent_checkins(10, tmp_db)
        assert len(recent) == 1
        assert recent[0].checkin_type == "morning"
        assert json.loads(recent[0].bosses) == ["jinsu"]

    def test_mark_responded(self, tmp_db):
        cid = db.log_checkin("morning", ["jinsu"], db_path=tmp_db)
        db.mark_user_responded(cid, tmp_db)
        recent = db.get_recent_checkins(10, tmp_db)
        assert recent[0].user_responded == 1

    def test_count_unresponded(self, tmp_db):
        for _ in range(3):
            db.log_checkin("morning", ["jinsu"], db_path=tmp_db)
        assert db.count_unresponded_checkins(5, tmp_db) == 3

    def test_unresponded_resets_on_response(self, tmp_db):
        # 1번 로그: 미응답
        db.log_checkin("morning", ["jinsu"], db_path=tmp_db)
        # 2번 로그: 응답
        cid2 = db.log_checkin("afternoon", ["jinsu"], db_path=tmp_db)
        db.mark_user_responded(cid2, tmp_db)
        # 3번 로그: 미응답 (가장 최근)
        db.log_checkin("evening", ["jinsu"], db_path=tmp_db)
        # count_unresponded는 최신부터 역순으로 연속 미응답만 셈
        # 3번(미응답) → 카운트 1 → 2번(응답) → 멈춤
        assert db.count_unresponded_checkins(5, tmp_db) == 1


# ── Statistics ───────────────────────────────────────────────────────────────


class TestStatistics:

    def test_task_stats(self, tmp_db):
        db.create_task("A", "daily", db_path=tmp_db)
        t2 = db.create_task("B", "weekly", db_path=tmp_db)
        db.update_task_status(t2, "completed", tmp_db)
        stats = db.get_task_stats(tmp_db)
        assert stats["by_status"]["active"] == 1
        assert stats["by_status"]["completed"] == 1

    def test_checkin_stats(self, tmp_db):
        cid = db.log_checkin("morning", ["jinsu"], tokens_used=1000, db_path=tmp_db)
        db.mark_user_responded(cid, tmp_db)
        db.log_checkin("evening", ["jinsu"], tokens_used=500, db_path=tmp_db)
        stats = db.get_checkin_stats(tmp_db)
        assert stats["total_checkins"] == 2
        assert stats["responded"] == 1
        assert stats["total_tokens"] == 1500
        assert 0.4 < stats["response_rate"] < 0.6


# ── Growth Metrics ───────────────────────────────────────────────────────────


class TestGrowthMetrics:

    def test_record_and_get(self, tmp_db):
        db.record_metric("completion_rate", 0.85, "2026-W10", db_path=tmp_db)
        metrics = db.get_metrics_by_type("completion_rate", 10, tmp_db)
        assert len(metrics) == 1
        assert metrics[0]["value"] == 0.85
        assert metrics[0]["period"] == "2026-W10"
