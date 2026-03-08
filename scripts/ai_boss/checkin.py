#!/usr/bin/env python3
"""Checkin Script — 스케줄러에서 호출되는 메인 실행 스크립트.

Usage:
    python3 scripts/ai_boss/checkin.py morning
    python3 scripts/ai_boss/checkin.py evening
    python3 scripts/ai_boss/checkin.py weekly
    python3 scripts/ai_boss/checkin.py monthly
"""

import json
import subprocess
import sys
from pathlib import Path

# Allow importing sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_boss import db
from ai_boss.selector import select_bosses_for_checkin
from ai_boss.prompt_builder import build_checkin_prompt
from ai_boss.parser import parse_boss_response
from ai_boss.sender import send_boss_messages


def _call_claude(prompt: str) -> tuple:
    """Claude CLI를 -p --output-format json 모드로 호출.

    Returns:
        (text, usage_dict) 튜플.
        usage_dict: {"input_tokens": int, "output_tokens": int, ...} 또는 빈 dict.
    """
    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--no-session-persistence",
            "--model", "haiku",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (rc={result.returncode}): {result.stderr[:200]}")

    try:
        data = json.loads(result.stdout)
        text = data.get("result", "")
        usage = data.get("usage", {})
        return text, usage
    except (json.JSONDecodeError, KeyError):
        # Fallback: treat stdout as plain text
        return result.stdout.strip(), {}


def run_checkin(checkin_type: str, db_path: str = db.DB_PATH) -> dict:
    """체크인 실행 — 전체 파이프라인.

    1. DB에서 활성 태스크 + 최근 피드백 조회
    2. 체크인 타입에 맞는 상사 선택
    3. 프롬프트 조합
    4. Claude CLI 호출
    5. 응답 파싱
    6. Telegram 전송
    7. DB 기록

    Returns:
        실행 결과 요약 dict.
    """
    # 체크인 활성화 체크
    db.init_db(db_path)
    enabled = db.get_config("checkin_enabled", db_path)
    if enabled and enabled.lower() in ("false", "0", "no"):
        return {"status": "disabled", "checkin_type": checkin_type}

    # 미응답 연속 횟수 체크 (5회 이상이면 스킵)
    unresponded = db.count_unresponded_checkins(5, db_path)
    if unresponded >= 5:
        return {"status": "skipped_unresponded", "consecutive": unresponded}

    # 상사 선택
    active_bosses = db.get_active_bosses(db_path)
    bosses = select_bosses_for_checkin(checkin_type, active_bosses)
    if not bosses:
        return {"status": "no_bosses", "checkin_type": checkin_type}

    # 프롬프트 조합
    prompt = build_checkin_prompt(checkin_type, bosses, db_path)

    # Claude CLI 호출
    raw_response, usage = _call_claude(prompt)

    # 응답 파싱
    messages = parse_boss_response(raw_response)
    if not messages:
        return {"status": "parse_failed", "raw": raw_response[:200]}

    # Telegram 전송
    sent = send_boss_messages(messages)

    # 피드백 DB 기록
    for msg in messages:
        db.add_feedback(
            boss=msg.boss,
            content=msg.text,
            checkin_type=checkin_type,
            db_path=db_path,
        )

    # 체크인 로그 기록
    actual_tokens = (
        usage.get("input_tokens", 0)
        + usage.get("output_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )
    checkin_id = db.log_checkin(
        checkin_type=checkin_type,
        bosses=bosses,
        tokens_used=actual_tokens,
        db_path=db_path,
    )

    return {
        "status": "ok",
        "checkin_type": checkin_type,
        "bosses": bosses,
        "messages_sent": sent,
        "checkin_id": checkin_id,
        "tokens_used": actual_tokens,
        "usage": usage,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: checkin.py <morning|evening|weekly|monthly>", file=sys.stderr)
        sys.exit(1)

    checkin_type = sys.argv[1]
    valid_types = ("morning", "evening", "weekly", "monthly")
    if checkin_type not in valid_types:
        print(f"Invalid type: {checkin_type}. Valid: {valid_types}", file=sys.stderr)
        sys.exit(1)

    try:
        result = run_checkin(checkin_type)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
