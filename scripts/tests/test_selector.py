"""Tests for ai_boss.selector — 페르소나 선택 로직."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_boss.selector import (
    select_bosses_for_message,
    select_bosses_for_checkin,
)

ALL_BOSSES = ["jinsu", "miyoung", "junghoon"]


# ── select_bosses_for_message ────────────────────────────────────────────────


class TestSelectBossesForMessage:

    def test_default_to_jinsu_when_no_match(self):
        result = select_bosses_for_message("안녕하세요", ALL_BOSSES)
        assert result == ["jinsu"]

    def test_jinsu_keywords(self):
        result = select_bosses_for_message("PR 올렸어, 마감이 내일이야", ALL_BOSSES)
        assert "jinsu" in result

    def test_miyoung_keywords(self):
        result = select_bosses_for_message("요즘 좀 힘들고 번아웃 올 것 같아", ALL_BOSSES)
        assert "miyoung" in result

    def test_junghoon_keywords(self):
        result = select_bosses_for_message("아키텍처 설계 리뷰 좀 해줘", ALL_BOSSES)
        assert "junghoon" in result

    def test_multiple_bosses_triggered(self):
        result = select_bosses_for_message(
            "코드 리팩토링 마감이 내일인데 스트레스 받아", ALL_BOSSES,
        )
        assert len(result) >= 2

    def test_all_hands_trigger(self):
        result = select_bosses_for_message("전체 피드백 줘", ALL_BOSSES)
        assert set(result) == set(ALL_BOSSES)

    def test_respects_active_bosses_filter(self):
        result = select_bosses_for_message("코드 리뷰 해줘", ["jinsu"])
        assert "junghoon" not in result

    def test_default_when_active_list_excludes_jinsu(self):
        result = select_bosses_for_message("안녕", ["miyoung", "junghoon"])
        assert len(result) >= 1  # fallback to first available

    def test_empty_text(self):
        result = select_bosses_for_message("", ALL_BOSSES)
        assert result == ["jinsu"]

    def test_case_insensitive(self):
        result = select_bosses_for_message("PR 올렸어", ALL_BOSSES)
        assert "jinsu" in result


# ── select_bosses_for_checkin ────────────────────────────────────────────────


class TestSelectBossesForCheckin:

    def test_morning_returns_jinsu(self):
        result = select_bosses_for_checkin("morning", ALL_BOSSES)
        assert result == ["jinsu"]

    def test_evening_returns_jinsu(self):
        result = select_bosses_for_checkin("evening", ALL_BOSSES)
        assert result == ["jinsu"]

    def test_weekly_returns_all(self):
        result = select_bosses_for_checkin("weekly", ALL_BOSSES)
        assert set(result) == set(ALL_BOSSES)

    def test_monthly_returns_miyoung_junghoon(self):
        result = select_bosses_for_checkin("monthly", ALL_BOSSES)
        assert "miyoung" in result
        assert "junghoon" in result

    def test_unknown_type_returns_default(self):
        result = select_bosses_for_checkin("unknown", ALL_BOSSES)
        assert result == ["jinsu"]

    def test_respects_active_filter(self):
        result = select_bosses_for_checkin("weekly", ["jinsu"])
        assert result == ["jinsu"]
