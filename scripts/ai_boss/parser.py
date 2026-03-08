"""Message Parser — LLM JSON 응답 파서 (Level 0: 코드).

LLM 응답을 BossMessage 리스트로 변환한다.
파싱 실패 시 fallback으로 raw text를 진수 발언으로 처리.
"""

import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class BossMessage:
    boss: str
    text: str


def parse_boss_response(raw: str) -> List[BossMessage]:
    """LLM JSON 응답을 BossMessage 리스트로 파싱.

    Expected format:
        [{"boss": "jinsu", "text": "..."}, ...]

    Args:
        raw: LLM 응답 문자열 (JSON or plain text).

    Returns:
        BossMessage 리스트. 파싱 실패 시 raw text를 jinsu 메시지로 fallback.
    """
    cleaned = raw.strip()

    # JSON 블록 추출 (```json ... ``` 래핑 제거)
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # 첫 줄과 마지막 줄의 ``` 제거
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # JSON 배열 시도
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return _parse_message_list(data)
        if isinstance(data, dict) and "boss" in data and "text" in data:
            return [BossMessage(boss=data["boss"], text=data["text"])]
    except (json.JSONDecodeError, TypeError):
        pass

    # JSON 객체가 텍스트에 섞여있을 때 — [ 부터 ] 까지 추출 시도
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, list):
                return _parse_message_list(data)
        except (json.JSONDecodeError, TypeError):
            pass

    # 최종 fallback: raw text를 jinsu 메시지로
    return [BossMessage(boss="jinsu", text=cleaned)] if cleaned else []


def _parse_message_list(data: list) -> List[BossMessage]:
    """JSON 리스트를 BossMessage 리스트로 변환."""
    messages = []
    for item in data:
        if not isinstance(item, dict):
            continue
        boss = item.get("boss", "jinsu")
        text = item.get("text", "")
        if text:
            messages.append(BossMessage(boss=str(boss), text=str(text)))
    return messages if messages else []
