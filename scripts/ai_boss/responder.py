"""Responder — 상엽 Telegram 메시지에 대한 상사 응답 생성.

bridge가 boss 그룹 메시지를 cc-boss로 라우팅하면,
이 모듈이 메시지 분석 → 페르소나 선택 → 응답 생성 → 전송한다.

사용법:
    python3 scripts/ai_boss/responder.py "상엽의 메시지"
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# tmux/launchd 환경에서 claude CLI를 찾기 위한 PATH 보정
_EXTRA_PATH = str(Path.home() / ".local" / "bin")
if _EXTRA_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_EXTRA_PATH}:{os.environ.get('PATH', '')}"

from ai_boss import db
from ai_boss.selector import select_bosses_for_message
from ai_boss.prompt_builder import build_response_prompt
from ai_boss.parser import parse_boss_response
from ai_boss.sender import send_boss_messages


def _call_claude(prompt: str) -> tuple:
    """Claude CLI를 -p --output-format json 모드로 호출.

    Returns:
        (text, usage_dict) 튜플.
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
        return result.stdout.strip(), {}


def respond_to_message(
    user_message: str,
    db_path: str = db.DB_PATH,
) -> dict:
    """상엽 메시지에 대한 상사 응답 생성 + 전송.

    1. 메시지 분석 → 페르소나 선택
    2. 프롬프트 조합
    3. Claude CLI 호출
    4. 응답 파싱
    5. Telegram 전송
    6. DB 기록

    Returns:
        실행 결과 요약 dict.
    """
    db.init_db(db_path)

    # 상사 선택
    active_bosses = db.get_active_bosses(db_path)
    bosses = select_bosses_for_message(user_message, active_bosses)
    if not bosses:
        return {"status": "no_bosses"}

    # 프롬프트 조합
    prompt = build_response_prompt(user_message, bosses, db_path)

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
            context=user_message[:200],
            db_path=db_path,
        )

    # 가장 최근 체크인의 user_responded 마킹
    recent_checkins = db.get_recent_checkins(1, db_path)
    if recent_checkins:
        db.mark_user_responded(recent_checkins[0].id, db_path)

    actual_tokens = (
        usage.get("input_tokens", 0)
        + usage.get("output_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )

    return {
        "status": "ok",
        "bosses": bosses,
        "messages_sent": sent,
        "tokens_used": actual_tokens,
        "usage": usage,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: responder.py <message>", file=sys.stderr)
        sys.exit(1)

    message = " ".join(sys.argv[1:])

    try:
        result = respond_to_message(message)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
