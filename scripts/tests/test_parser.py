"""Tests for ai_boss.parser — LLM 응답 파싱."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_boss.parser import parse_boss_response, BossMessage


class TestParseBossResponse:

    def test_valid_json_array(self):
        raw = '[{"boss": "jinsu", "text": "오늘 뭐 해?"}, {"boss": "miyoung", "text": "화이팅!"}]'
        result = parse_boss_response(raw)
        assert len(result) == 2
        assert result[0] == BossMessage(boss="jinsu", text="오늘 뭐 해?")
        assert result[1] == BossMessage(boss="miyoung", text="화이팅!")

    def test_single_json_object(self):
        raw = '{"boss": "junghoon", "text": "코드 좋아"}'
        result = parse_boss_response(raw)
        assert len(result) == 1
        assert result[0].boss == "junghoon"

    def test_json_in_code_block(self):
        raw = '```json\n[{"boss": "jinsu", "text": "잘했어"}]\n```'
        result = parse_boss_response(raw)
        assert len(result) == 1
        assert result[0].text == "잘했어"

    def test_json_mixed_with_text(self):
        raw = 'Here is the response:\n[{"boss": "jinsu", "text": "좋아"}]\nEnd.'
        result = parse_boss_response(raw)
        assert len(result) == 1
        assert result[0].boss == "jinsu"

    def test_fallback_to_jinsu_on_plain_text(self):
        raw = "그냥 텍스트 응답"
        result = parse_boss_response(raw)
        assert len(result) == 1
        assert result[0].boss == "jinsu"
        assert result[0].text == "그냥 텍스트 응답"

    def test_empty_string(self):
        result = parse_boss_response("")
        assert result == []

    def test_whitespace_only(self):
        result = parse_boss_response("   \n  ")
        assert result == []

    def test_invalid_json(self):
        raw = '{invalid json}'
        result = parse_boss_response(raw)
        assert len(result) == 1  # fallback
        assert result[0].boss == "jinsu"

    def test_empty_array(self):
        raw = '[]'
        result = parse_boss_response(raw)
        assert result == []

    def test_array_with_missing_text(self):
        raw = '[{"boss": "jinsu"}]'
        result = parse_boss_response(raw)
        assert result == []  # text가 없으면 빈 리스트

    def test_array_with_non_dict_items(self):
        raw = '["hello", 42]'
        result = parse_boss_response(raw)
        assert result == []

    def test_preserves_korean(self):
        raw = '[{"boss": "miyoung", "text": "요즘 좀 쉬어도 괜찮아 😊"}]'
        result = parse_boss_response(raw)
        assert "쉬어도" in result[0].text
